import json
import random
import shutil
import logging
import tempfile
import argparse
from autoflash import TFTP_IP
from autoflash import run_autoflash
from autoflash.ips import get_free_ip
from pathlib import Path
import autoflash.log as log
from labelprinter import labels, printer


def flash_autoconf(
    images_dir: Path,
    serial_port: str,
    baudrate: int,
    bootloader_password: str,
    labelprinter: str = None,
):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        logging.info(f"Using temporary directory {tmpdir}")

        metadata_file = random.choice(list(images_dir.glob("*.json")))
        sysupgrade_file = metadata_file.with_suffix(".bin")

        logging.info(f"Using metadata file {metadata_file}")

        shutil.move(metadata_file, tmpdir / metadata_file.name)
        shutil.move(sysupgrade_file, tmpdir / sysupgrade_file.name)
        metadata_file = tmpdir / metadata_file.name
        sysupgrade_file = tmpdir / sysupgrade_file.name

        metadata = json.loads(metadata_file.read_text())

        if labelprinter:
            wifi_label = labels.render_wifi(
                ssid=metadata["ssid"], password=metadata["wifi_password"]
            )
            printer.print_to_ip(wifi_label, labelprinter)

            login_label = labels.render_login(
                ip="192.168.0.1",
                password=metadata["root_password"],
                bootloader_pw=bootloader_password,
            )
            printer.print_to_ip(surf=login_label, ip=labelprinter)
        else:
            logging.info("No labelprinter set, skipping label printing")

        run_autoflash(
            ramboot_file_name="ramboot.bin",
            sysupgrade_path=sysupgrade_file,
            port=serial_port,
            speed=baudrate,
            password=bootloader_password,
            ap_ip=get_free_ip(reserved_ips=[TFTP_IP]),
        )

        sysupgrade_file.unlink()
        metadata_file.unlink()


def parse_args():
    parser = argparse.ArgumentParser(
        prog="autoflash", description="Huawei APXXXXDN Autoflasher"
    )
    parser.add_argument(
        "-i",
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
        "-s", "--speed", type=int, default=9600, help="Baudrate, default is 9600"
    )
    parser.add_argument(
        "-p",
        "--password",
        type=str,
        default="dasuboot",
        help="Bootloader Password",
    )
    parser.add_argument(
        "-l",
        "--labelprinter",
        type=str,
        help="Hostname of the labelprinter to print labels. If not set, no labels will be printed.",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="Enable debug logging, ie. show serial output",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.INFO,
    )

    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=args.loglevel, format=log.FORMAT, datefmt=log.DATEFMT)

    flash_autoconf(
        images_dir=args.images_dir,
        serial_port=args.port,
        baudrate=args.speed,
        bootloader_password=args.password,
        labelprinter=args.labelprinter,
    )


if __name__ == "__main__":
    main()
