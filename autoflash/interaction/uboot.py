import re
import time
import logging
import ipaddress
import autoflash.interaction.serial as serial
from ..log import debug_logging_enabled

PROMPT_STOP_AUTOBOOT = r"Press f or F  to stop Auto-Boot"
PROMPT_SKIP_BUS_TEST = r"Press j or J to stop Bus-Test"
PROMPT_PASSWORD = r"Password for uboot cmd line :"
PROMPT_UBOOT_READY = r"ar7240>"


def ensure_ready(ser, password):
    """
    The script can be started at two points in time:
        1. Before the AP is powered on. Then, we have to stop auto-boot AND enter the password
        2. After the AP has been powered on for a while. Then, we only have to enter the password.
           We only get the prompt when we press enter.
        3. The password has already been entered. We only get the prompt when we press enter.
    """
    ser.write(b"\n")
    for _ in range(4):
        m = serial.wait_for_prompt_match(
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
            serial.log_buffer_as_error()
            raise Exception("Unexpected prompt")

    if debug_logging_enabled():
        print()

    logging.info("U-Boot ready")


def send_uboot_cmd(ser, cmd: str, wait_for_prompt=True):
    ser.write(f"{cmd}\n".encode("utf-8"))
    if wait_for_prompt:
        serial.wait_for_prompt_match(ser, PROMPT_UBOOT_READY)


def configure_ramboot(
    ser, tftp_ip: ipaddress.IPv4Address, ap_ip: ipaddress.IPv4Address, filename: str
):
    logging.info(
        f"Configuring ramboot with TFTP server '{tftp_ip}', AP IP '{ap_ip}', filename '{filename}'"
    )
    send_uboot_cmd(ser, f"setenv serverip {tftp_ip}")
    send_uboot_cmd(ser, f"setenv ipaddr {ap_ip}")
    send_uboot_cmd(ser, f"setenv rambootfile {filename}")


def run_ramboot(ser):
    logging.info("Starting ramboot")
    # We should wait a bit for the LAN interface to be (really) ready.
    # Otherwise, the TFTP connection might abort during ramboot image transfer.
    time.sleep(5)
    send_uboot_cmd(ser, "run ramboot", wait_for_prompt=False)

    ramboot_failed = r"Execute .* Fail"
    result = serial.wait_for_prompt_match(
        ser,
        "|".join(["Linux version", ramboot_failed]),
        timeout=20,
    )

    if re.match(ramboot_failed, result):
        serial.log_buffer_as_error()
        raise Exception("Ramboot failed. Is TFTP server started?")

    logging.info("Ramboot successfully started")
