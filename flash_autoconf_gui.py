"""Tkinter GUI entrypoint for parallel AP flashing."""

import argparse
import logging
import sys
from pathlib import Path

import autoflash.log as alog
from autoflash.gui.app import App


def parse_args():
    p = argparse.ArgumentParser(
        prog="flash_autoconf_gui",
        description="GUI: flash multiple Huawei APs in parallel using autoconf images",
    )
    p.add_argument("-i", "--images-dir", type=Path, required=True)
    p.add_argument(
        "-n",
        "--parallel",
        type=int,
        required=True,
        help="Number of APs to flash in parallel (max 8). "
        "Will use /dev/ttyUSB0..N-1 and ge-0/0/0..N-1.",
    )
    p.add_argument(
        "--ports",
        type=str,
        default=None,
        help="Comma-separated explicit AP indices, e.g. '0,2,3'. Overrides -n.",
    )
    p.add_argument("-s", "--speed", type=int, default=9600)
    p.add_argument(
        "-p",
        "--password",
        type=str,
        default="dasuboot",
        help="Bootloader password (default dasuboot)",
    )
    p.add_argument(
        "-l",
        "--labelprinter",
        type=str,
        default=None,
        help="Hostname of the label printer (omit to skip)",
    )
    p.add_argument("--logs-dir", type=Path, default=Path("logs"))
    p.add_argument(
        "-d",
        "--debug",
        action="store_const",
        const=logging.DEBUG,
        default=logging.INFO,
        dest="loglevel",
    )
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=args.loglevel,
        format=alog.FORMAT,
        datefmt=alog.DATEFMT,
        stream=sys.stderr,
    )

    if args.ports:
        ap_indices = [int(x) for x in args.ports.split(",")]
    else:
        if args.parallel < 1 or args.parallel > 8:
            sys.exit("--parallel must be between 1 and 8")
        ap_indices = list(range(args.parallel))

    app = App(
        ap_indices=ap_indices,
        images_dir=args.images_dir,
        logs_dir=args.logs_dir,
        baudrate=args.speed,
        bootloader_password=args.password,
        labelprinter_host=args.labelprinter,
    )
    app.run()


if __name__ == "__main__":
    main()
