import re
import sys
import time
import serial
import logging
import argparse


PROMPT_STOP_AUTOBOOT = "to stop Auto-Boot"
PROMPT_PASSWORD = "Password for uboot cmd line :"
PROMPT_UBOOT_READY = "ar7240>"


def parse_args():
    parser = argparse.ArgumentParser(description="Huawei APXXXXDN Autoflasher")
    parser.add_argument("port", type=str, help="Serial port")
    parser.add_argument("--speed", type=int, default=9600, help="Baudrate")
    parser.add_argument(
        "--password",
        "-p",
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


def wait_for_prompt_match(ser, prompt_regex):
    buffer = ""
    while True:
        # There might be weird things happening over serial
        # (eg. the AP resets before everything is transmitted).
        # Therefore, we have to ignore decoding errors here.
        bytes_to_read = 1 if ser.inWaiting() == 0 else ser.inWaiting()
        new_read = ser.read(bytes_to_read).decode("utf-8", errors="ignore")
        if logging.getLogger().level == logging.DEBUG:
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
    m = wait_for_prompt_match(
        ser, f"{PROMPT_STOP_AUTOBOOT}|{PROMPT_PASSWORD}|{PROMPT_UBOOT_READY}"
    )
    if m == PROMPT_STOP_AUTOBOOT:
        time.sleep(0.5)
        ser.write(b"f\n")
        wait_for_prompt_match(ser, PROMPT_PASSWORD)
    elif m == PROMPT_PASSWORD:
        ser.write(f"{password}\n".encode("utf-8"))
        wait_for_prompt_match(ser, PROMPT_UBOOT_READY)
    logging.info("U-Boot ready")


def configure_ramboot(ser):
    pass


def main():
    args = parse_args()
    logging.basicConfig(level=args.loglevel)
    with serial.Serial(args.port, args.speed, timeout=1) as ser:
        ensure_uboot_ready(ser, args.password)

    if args.loglevel == logging.DEBUG:
        print()


if __name__ == "__main__":
    main()
