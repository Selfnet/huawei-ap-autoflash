import random
import logging
import tempfile
import argparse
from autoflash import OPENWRT_DEFAULT_LAN_IP
from autoflash import run_autoflash
from pathlib import Path


def flash_autoconf(
    images_dir: Path, serial_port: str, baudrate: int, bootloader_password: str
):
    with Path(tempfile.TemporaryDirectory()) as tmpdir:
        logging.info(f"Using temporary directory {tmpdir}")

        metadata_file = random.choice(list(images_dir.glob("*.json")))
        sysupgrade_file = metadata_file.with_suffix(".bin")

        logging.info(f"Using metadata file {metadata_file}")

        metadata_file.rename(tmpdir / metadata_file.name)
        sysupgrade_file.rename(tmpdir / sysupgrade_file.name)

        run_autoflash(
            ramboot_file_name="ramboot.bin",
            sysupgrade_path=sysupgrade_file,
            port=serial_port,
            speed=baudrate,
            password=bootloader_password,
            ap_ip=OPENWRT_DEFAULT_LAN_IP,  # TODO: Support multiple APs in parallel
        )


def parse_args():
    parser = argparse.ArgumentParser(
        prog="autoflash", description="Huawei APXXXXDN Autoflasher"
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        required=True,
        help="Directory containing images and metadata files",
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

    flash_autoconf(
        images_dir=args.images_dir,
        serial_port=args.port,
        baudrate=args.speed,
        bootloader_password=args.password,
    )


if __name__ == "__main__":
    main()
