import os
import re
import sys
import time
import config
import serial
import logging
import argparse
import ipaddress
import subprocess
import network_utils


PROMPT_STOP_AUTOBOOT = r"Press f or F  to stop Auto-Boot"
PROMPT_SKIP_BUS_TEST = r"Press j or J to stop Bus-Test"
PROMPT_PASSWORD = r"Password for uboot cmd line :"
PROMPT_UBOOT_READY = r"ar7240>"
PROMPT_OPENWRT_SHELL = r"root@\S+:\S+#"
PROMPT_SYSUPGRADE_COMPLETE = r"Rebooting system..."

OPENWRT_DEFAULT_LAN_IP = ipaddress.IPv4Address("192.168.1.1")


def parse_args():
    parser = argparse.ArgumentParser(description="Huawei APXXXXDN Autoflasher")
    parser.add_argument(
        "ramboot_file_name",
        type=str,
        help="Ramboot filename (only!), eg. openwrt-ath79-generic-huawei_apXXXXdn-initramfs-kernel.bin",
    )
    parser.add_argument(
        "sysupgrade_file_path",
        type=str,
        help="Sysupgrade file path, eg. openwrt-ath79-generic-huawei_apXXXXdn-squashfs-sysupgrade.bin",
    )
    parser.add_argument(
        "--port",
        type=str,
        default="/dev/ttyUSB0",
        help="Serial port, default is /dev/ttyUSB0",
    )
    parser.add_argument(
        "--speed", type=int, default=9600, help="Baudrate, default is 9600"
    )
    parser.add_argument(
        "-p",
        "--password",
        type=str,
        default="admin@huawei.com",
        help="Bootloader Password",
    )
    parser.add_argument(
        "--ap-ip",
        type=ipaddress.IPv4Address,
        default=OPENWRT_DEFAULT_LAN_IP,
        help="IP address for the AP",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="Enable debug logging, ie. show serial output",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.WARNING,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose logging",
        action="store_const",
        dest="loglevel",
        const=logging.INFO,
    )

    return parser.parse_args()


def debug_logging_enabled():
    return logging.getLogger().level == logging.DEBUG


def wait_for_prompt_match(ser, prompt_regex):
    buffer = ""
    while True:
        # There might be weird things happening over serial
        # (eg. the AP resets before everything is transmitted).
        # Therefore, we have to ignore decoding errors here.
        bytes_to_read = 1 if ser.inWaiting() == 0 else ser.inWaiting()
        new_read = ser.read(bytes_to_read).decode("utf-8", errors="ignore")
        if debug_logging_enabled():
            print(new_read, end="")
            sys.stdout.flush()

        buffer += new_read

        match = re.search(prompt_regex, buffer)
        if match:
            return match.group(0)


def ensure_uboot_ready(ser, password):
    """
    The script can be started at two points in time:
        1. Before the AP is powered on. Then, we have to stop auto-boot AND enter the password
        2. After the AP has been powered on for a while. Then, we only have to enter the password.
           We only get the prompt when we press enter.
        3. The password has already been entered. We only get the prompt when we press enter.
    """
    ser.write(b"\n")
    for _ in range(4):
        m = wait_for_prompt_match(
            ser,
            "|".join(
                [
                    PROMPT_STOP_AUTOBOOT,
                    PROMPT_PASSWORD,
                    PROMPT_UBOOT_READY,
                    PROMPT_SKIP_BUS_TEST,
                ]
            ),
        )
        if m == PROMPT_SKIP_BUS_TEST:
            time.sleep(0.2)
            ser.write(b"j")
        elif m == PROMPT_STOP_AUTOBOOT:
            time.sleep(0.2)
            ser.write(b"f")
        elif m == PROMPT_PASSWORD:
            time.sleep(0.2)
            ser.write(f"{password}\n".encode("utf-8"))
        elif m == PROMPT_UBOOT_READY:
            break
        else:
            raise Exception("Unexpected prompt")

    print()
    logging.info("U-Boot ready")


def send_uboot_cmd(ser, cmd: str, wait_for_prompt=True):
    ser.write(f"{cmd}\n".encode("utf-8"))
    if wait_for_prompt:
        wait_for_prompt_match(ser, PROMPT_UBOOT_READY)


def configure_ramboot(
    ser, tftp_ip: ipaddress.IPv4Address, ap_ip: ipaddress.IPv4Address, filename: str
):
    send_uboot_cmd(ser, f"setenv serverip {tftp_ip}")
    send_uboot_cmd(ser, f"setenv ipaddr {ap_ip}")
    send_uboot_cmd(ser, f"setenv rambootfile {filename}")


def run_ramboot(ser):
    # We should wait a bit for the LAN interface to be (really) ready.
    # Otherwise, the TFTP connection might abort during ramboot image transfer.
    time.sleep(5)
    send_uboot_cmd(ser, "run ramboot", wait_for_prompt=False)


def wait_for_openwrt_shell_ready(ser):
    for _ in range(100):
        ser.write(b"\n")
        time.sleep(1)
        read = ser.read(ser.inWaiting()).decode("utf-8", errors="ignore")
        if debug_logging_enabled():
            print(read, end="")
            sys.stdout.flush()
        if re.search(PROMPT_OPENWRT_SHELL, read):
            print()
            logging.info("OpenWRT shell ready")
            return

    raise Exception("Timeout waiting for OpenWrt shell ready")


def wait_for_openwrt_lan_ready(ser):
    # Bash oneliner that waits until the output of the command `ip link show br-lan` contains "br-lan"
    ser.write(b'while ! ip link show br-lan | grep -q "br-lan"; do sleep 3; done\n')

    wait_for_prompt_match(ser, PROMPT_OPENWRT_SHELL)
    time.sleep(5)
    print()
    logging.info("OpenWrt LAN ready")


def wait_for_ap_pingable(ser, ip: ipaddress.IPv4Address):
    logging.info(f"Waiting for AP @ {ip} to be pingable")
    for _ in range(180):
        if debug_logging_enabled():
            print(ser.read(ser.inWaiting()).decode("utf-8", errors="ignore"), end="")

        if network_utils.ip_responds_to_ping(ip):
            logging.info(f"AP @ {ip} is pingable now")
            return
        time.sleep(1)

    raise Exception(f"Timeout waiting for AP @ {ip} to be pingable")


def set_openwrt_lan_ip(ser, ip: ipaddress.IPv4Address):
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


def main():
    args = parse_args()
    logging.basicConfig(level=args.loglevel)
    with serial.Serial(args.port, args.speed, timeout=1) as ser:
        # Ramboot
        ensure_uboot_ready(ser, args.password)
        configure_ramboot(ser, config.tftp_ip, args.ap_ip, args.ramboot_file_name)
        run_ramboot(ser)

        # Flash OpenWrt
        wait_for_openwrt_shell_ready(ser)
        wait_for_openwrt_lan_ready(ser)
        if args.ap_ip != OPENWRT_DEFAULT_LAN_IP:
            set_openwrt_lan_ip(ser, args.ap_ip)
        wait_for_ap_pingable(ser, args.ap_ip)
        flash_openwrt(ser, args.ap_ip, args.sysupgrade_file_path)

        # Wait for sysupgrade to finish
        wait_for_openwrt_shell_ready(ser)
        wait_for_openwrt_lan_ready(ser)
        if args.ap_ip != OPENWRT_DEFAULT_LAN_IP:
            set_openwrt_lan_ip(ser, args.ap_ip)
        wait_for_ap_pingable(ser, args.ap_ip)

    if args.loglevel == logging.DEBUG:
        print()


if __name__ == "__main__":
    main()
