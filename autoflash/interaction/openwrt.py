import re
import os
import sys
import time
import logging
import ipaddress
import subprocess
from . import serial
from .. import network
from ..log import debug_logging_enabled

PROMPT_OPENWRT_SHELL = r"root@\S+:\S+#"
PROMPT_SYSUPGRADE_COMPLETE = r"Rebooting system..."


def wait_for_shell_ready(ser):
    for _ in range(100):
        ser.write(b"\n")
        time.sleep(1)
        read = ser.read(ser.inWaiting()).decode("utf-8", errors="ignore")
        if debug_logging_enabled() and read != "\n":
            print(read, end="")
            sys.stdout.flush()
        if re.search(PROMPT_OPENWRT_SHELL, read):
            if debug_logging_enabled():
                print()

            logging.info("OpenWRT shell ready")
            return

    raise Exception("Timeout waiting for OpenWrt shell ready")


def wait_for_lan_ready(ser):
    logging.info("Waiting for OpenWrt's 'br-lan' LAN interface to be ready")

    ser.write(b"\n")
    serial.wait_for_prompt_match(ser, PROMPT_OPENWRT_SHELL)

    # Bash oneliner that waits until the output of the command `ip link show br-lan` contains "br-lan"
    ser.write(b'while ! ip link show br-lan | grep -q "br-lan"; do sleep 3; done\n')

    serial.wait_for_prompt_match(ser, PROMPT_OPENWRT_SHELL, timeout=180)
    time.sleep(5)
    if debug_logging_enabled():
        print()

    logging.info("OpenWrt LAN ready")


def wait_for_pingable(ser, ip: ipaddress.IPv4Address):
    logging.info(f"Waiting for AP @ {ip} to be pingable")
    for _ in range(180):
        if debug_logging_enabled():
            print(ser.read(ser.inWaiting()).decode("utf-8", errors="ignore"), end="")

        if network.ip_responds_to_ping(ip):
            logging.info(f"AP @ {ip} is pingable now")
            return
        time.sleep(1)

    raise Exception(f"Timeout waiting for AP @ {ip} to be pingable")


def set_lan_ip(ser, ip: ipaddress.IPv4Address):
    logging.info(f"Setting LAN IP to {ip}")
    ser.write(f"uci set network.lan.ipaddr={ip}\n".encode("utf-8"))
    ser.write(b"uci commit network\n")
    ser.write(b"/etc/init.d/network restart\n")


def flash_openwrt(ser, ap_ip: ipaddress.IPv4Address, sysupgrade_file: str):
    logging.info("Copying sysupgrade image to AP using scp")

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
        logging.error("Failed to copy sysupgrade image using scp")
        raise

    options = "-n"  # Don't save config
    if debug_logging_enabled():
        options += " -v"

    sysupgrade_file_name = os.path.basename(sysupgrade_file)
    logging.info(f"Running sysupgrade with OpenWrt image {sysupgrade_file_name}")
    ser.write(f"sysupgrade {options} /tmp/{sysupgrade_file_name}\n".encode("utf-8"))
