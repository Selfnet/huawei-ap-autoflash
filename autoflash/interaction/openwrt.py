import re
import os
import time
import logging
import ipaddress
import subprocess
from .. import network

PROMPT_OPENWRT_SHELL = r"root@\S+:\S+#"
PROMPT_SYSUPGRADE_COMPLETE = r"Rebooting system..."


def wait_for_shell_ready(reader, logger: logging.Logger | None = None):
    log = logger or logging.getLogger(__name__)
    for _ in range(100):
        reader.write(b"\n")
        time.sleep(1)
        chunk = reader.read_available()
        if re.search(PROMPT_OPENWRT_SHELL, chunk):
            log.info("OpenWRT shell ready")
            # Silence kernel log messages going to the serial console.
            # Otherwise late-boot messages (module loads, ath10k init, link
            # state changes, ...) interleave with our subsequent commands
            # and trigger UART input overruns on the AP, mangling the
            # commands we send.
            reader.write(b"dmesg -n 1\n")
            reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL, timeout=10)
            return

    raise Exception("Timeout waiting for OpenWrt shell ready")


def wait_for_lan_ready(reader, logger: logging.Logger | None = None):
    log = logger or logging.getLogger(__name__)
    log.info("Waiting for OpenWrt's 'br-lan' LAN interface to be ready")

    reader.write(b"\n")
    reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL)

    # Bash oneliner that waits until the output of the command `ip link show br-lan` contains "br-lan"
    reader.write(b'while ! ip link show br-lan | grep -q "br-lan"; do sleep 3; done\n')

    reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL, timeout=180)
    time.sleep(5)

    log.info("OpenWrt LAN ready")


def wait_for_pingable(
    reader, ip: ipaddress.IPv4Address, logger: logging.Logger | None = None
):
    log = logger or logging.getLogger(__name__)
    log.info(f"Waiting for AP @ {ip} to be pingable")
    timeout = 180
    for elapsed in range(timeout):
        # Drain serial so it lands in debug log instead of being lost.
        reader.read_available()
        if network.ip_responds_to_ping(ip):
            log.info(f"AP @ {ip} is pingable now (after {elapsed}s)")
            return
        if elapsed and elapsed % 10 == 0:
            log.info(
                f"Still waiting for AP @ {ip} to be pingable ({elapsed}/{timeout}s)"
            )
        time.sleep(1)

    raise Exception(f"Timeout waiting for AP @ {ip} to be pingable after {timeout}s")


def _send_shell_cmd(reader, cmd: str, timeout: float = 30):
    """Send a single shell command and wait for the next OpenWrt prompt."""
    reader.write(f"{cmd}\n".encode("utf-8"))
    reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL, timeout=timeout)


def _capture_shell_cmd(reader, cmd: str, timeout: float = 30) -> str:
    """Send a shell command, wait for the prompt, and return the output
    that came back (best-effort, taken from the prompt-match buffer).
    """
    reader.reset_buffer()
    reader.write(f"{cmd}\n".encode("utf-8"))
    reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL, timeout=timeout)
    return reader.buffer


def set_lan_ip(reader, ip: ipaddress.IPv4Address, logger: logging.Logger | None = None):
    log = logger or logging.getLogger(__name__)
    log.info(f"Setting LAN IP to {ip}/24")

    # Make sure we are at a stable shell prompt before doing anything.
    reader.write(b"\n")
    reader.wait_for_prompt_match(PROMPT_OPENWRT_SHELL)

    _send_shell_cmd(reader, f"uci set network.lan.ipaddr={ip}")
    # Without an explicit netmask UCI ends up binding the address as /32,
    # which leaves the AP unable to reply to traffic from peers on the same
    # /24 (it has no route back to them).
    _send_shell_cmd(reader, "uci set network.lan.netmask=255.255.255.0")
    _send_shell_cmd(reader, "uci commit network")

    # /etc/init.d/network restart prints a bunch of kernel messages and may
    # take a few seconds for the prompt to come back; allow longer.
    log.info("Restarting network on AP")
    _send_shell_cmd(reader, "/etc/init.d/network restart", timeout=60)

    # Verify the new IP is actually bound to br-lan. If `set_lan_ip` is
    # called before br-lan is back up, the IP set may have silently failed
    # or the restart may not have re-applied it. We retry a few times.
    log.info(f"Verifying br-lan has {ip}/24")
    target = f"inet {ip}/24"
    for attempt in range(15):
        time.sleep(1)
        out = _capture_shell_cmd(reader, "ip -4 addr show br-lan", timeout=15)
        if target in out:
            log.info(f"br-lan now has {ip}")
            return
        log.debug(f"br-lan does not yet have {ip} (attempt {attempt + 1}/15)")
    raise Exception(
        f"Failed to bring up br-lan with {ip} on AP. "
        f"Last `ip addr show br-lan` output:\n{out}"
    )


def flash_openwrt(
    reader,
    ap_ip: ipaddress.IPv4Address,
    sysupgrade_file: str,
    logger: logging.Logger | None = None,
    debug: bool = False,
):
    log = logger or logging.getLogger(__name__)
    log.info("Copying sysupgrade image to AP using scp")

    scp_command = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-O",  # Enable legacy scp mode, otherwise we get "ash: /usr/libexec/sftp-server: not found"
        sysupgrade_file,
        f"root@{ap_ip}:/tmp",
    ]

    try:
        subprocess.check_call(scp_command)
    except subprocess.CalledProcessError:
        log.error("Failed to copy sysupgrade image using scp")
        raise

    options = "-n"  # Don't save config
    if debug:
        options += " -v"

    sysupgrade_file_name = os.path.basename(sysupgrade_file)
    log.info(f"Running sysupgrade with OpenWrt image {sysupgrade_file_name}")
    reader.write(f"sysupgrade {options} /tmp/{sysupgrade_file_name}\n".encode("utf-8"))
