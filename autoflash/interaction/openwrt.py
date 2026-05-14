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
    for _ in range(180):
        # Drain serial so it lands in debug log instead of being lost.
        reader.read_available()
        if network.ip_responds_to_ping(ip):
            log.info(f"AP @ {ip} is pingable now")
            return
        time.sleep(1)

    raise Exception(f"Timeout waiting for AP @ {ip} to be pingable")


def set_lan_ip(reader, ip: ipaddress.IPv4Address, logger: logging.Logger | None = None):
    log = logger or logging.getLogger(__name__)
    log.info(f"Setting LAN IP to {ip}")
    reader.write(f"uci set network.lan.ipaddr={ip}\n".encode("utf-8"))
    reader.write(b"uci commit network\n")
    reader.write(b"/etc/init.d/network restart\n")


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
