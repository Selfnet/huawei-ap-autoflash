import logging
import argparse
import ipaddress
from . import OPENWRT_DEFAULT_LAN_IP
from . import run_autoflash


def parse_args():
    parser = argparse.ArgumentParser(
        prog="autoflash", description="Huawei APXXXXDN Autoflasher"
    )
    parser.add_argument(
        "ramboot_file_name",
        type=str,
        help="Ramboot filename (only!), eg. openwrt-ath79-generic-huawei_apXXXXdn-initramfs-kernel.bin",
    )
    parser.add_argument(
        "--sysupgrade-path",
        type=str,
        help="Sysupgrade file path, eg. openwrt-ath79-generic-huawei_apXXXXdn-squashfs-sysupgrade.bin. "
        "If not provided, the script will only ramboot the AP.",
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


def main():
    args = parse_args()
    logging.basicConfig(level=args.loglevel)

    run_autoflash(
        args.ramboot_file_name,
        args.sysupgrade_path,
        args.port,
        args.speed,
        args.password,
        args.ap_ip,
    )

    if args.loglevel == logging.DEBUG:
        print()


if __name__ == "__main__":
    main()
