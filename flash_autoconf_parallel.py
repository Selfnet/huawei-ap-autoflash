"""Headless parallel-flash CLI driver.

Use this for command-line driven runs (smoke testing the orchestrator
without a GUI). Prints status events to stdout. The Tkinter GUI will
plug into the same Context/run_parallel via a different status callback.
"""

import argparse
import logging
import sys
from pathlib import Path

import autoflash.log as alog
from autoflash.parallel import Context, run_parallel, make_timestamp
from autoflash.printer_queue import PrinterQueue


def parse_args():
    p = argparse.ArgumentParser(
        prog="flash_autoconf_parallel",
        description="Flash multiple Huawei APs in parallel using autoconf images",
    )
    p.add_argument("-i", "--images-dir", type=Path, required=True)
    p.add_argument(
        "-n",
        "--parallel",
        type=int,
        required=True,
        help="Number of APs to flash in parallel (e.g. 4). "
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


def status_print(ap, event, **fields):
    extra = " ".join(f"{k}={v}" for k, v in fields.items() if k != "metadata")
    print(f"[ap{ap}] {event} {extra}".rstrip(), flush=True)


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
        ap_indices = list(range(args.parallel))

    printer_q = PrinterQueue(host=args.labelprinter)
    printer_q.start()

    ctx = Context(
        images_dir=args.images_dir,
        logs_dir=args.logs_dir,
        baudrate=args.speed,
        bootloader_password=args.password,
        printer=printer_q,
        timestamp=make_timestamp(),
    )

    print(f"Will flash APs {ap_indices} in parallel.")
    print(f"Serial ports: {[f'/dev/ttyUSB{i}' for i in ap_indices]}")
    print(f"Switch ports: {[f'ge-0/0/{i}' for i in ap_indices]}")
    print(f"Logs in: {args.logs_dir}/")
    input("Connect APs and press Enter to begin... ")

    try:
        results = run_parallel(ap_indices, ctx, status=status_print)
    finally:
        printer_q.stop()

    print()
    print("Summary:")
    for i in sorted(results):
        print(f"  ap{i}: {'OK' if results[i] else 'FAILED'}")
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
