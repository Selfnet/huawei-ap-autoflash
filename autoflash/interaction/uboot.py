import re
import time
import logging
import ipaddress

PROMPT_STOP_AUTOBOOT = r"Press f or F  to stop Auto-Boot"
PROMPT_SKIP_BUS_TEST = r"Press j or J to stop Bus-Test"
PROMPT_PASSWORD = r"Password for uboot cmd line :"
PROMPT_UBOOT_READY = r"ar7240>"
PROMPT_NEW_PASSWORD = r"New password:"
PROMPT_CONFIRM_PASSWORD = r"Confirm  password:"


def ensure_ready(reader, password, logger: logging.Logger | None = None):
    """
    The script can be started at two points in time:
        1. Before the AP is powered on. Then, we have to stop auto-boot AND enter the password
        2. After the AP has been powered on for a while. Then, we only have to enter the password.
           We only get the prompt when we press enter.
        3. The password has already been entered. We only get the prompt when we press enter.
    """
    log = logger or logging.getLogger(__name__)
    reader.write(b"\n")
    for _ in range(4):
        m = reader.wait_for_prompt_match(
            "|".join(
                [
                    PROMPT_STOP_AUTOBOOT,
                    PROMPT_PASSWORD,
                    PROMPT_UBOOT_READY,
                    PROMPT_SKIP_BUS_TEST,
                    PROMPT_NEW_PASSWORD,
                    PROMPT_CONFIRM_PASSWORD,
                ]
            ),
        )
        if m == PROMPT_SKIP_BUS_TEST:
            time.sleep(0.2)
            reader.write(b"j")
        elif m == PROMPT_STOP_AUTOBOOT:
            time.sleep(0.2)
            reader.write(b"f")
        elif m == PROMPT_PASSWORD:
            time.sleep(0.2)
            reader.write(f"{password}\n".encode("utf-8"))
        elif m == PROMPT_NEW_PASSWORD or m == PROMPT_CONFIRM_PASSWORD:
            time.sleep(0.2)
            reader.write(f"{password}\n".encode("utf-8"))
        elif m == PROMPT_UBOOT_READY:
            break
        else:
            reader.log_buffer_as_error()
            raise Exception("Unexpected prompt")

    log.info("U-Boot ready")


def send_uboot_cmd(reader, cmd: str, wait_for_prompt=True):
    reader.write(f"{cmd}\n".encode("utf-8"))
    if wait_for_prompt:
        reader.wait_for_prompt_match(PROMPT_UBOOT_READY)


def configure_ramboot(
    reader,
    tftp_ip: ipaddress.IPv4Address,
    ap_ip: ipaddress.IPv4Address,
    filename: str,
    logger: logging.Logger | None = None,
):
    log = logger or logging.getLogger(__name__)
    log.info(
        f"Configuring ramboot with TFTP server '{tftp_ip}', AP IP '{ap_ip}', filename '{filename}'"
    )
    send_uboot_cmd(reader, "")
    time.sleep(1)
    send_uboot_cmd(reader, "")
    send_uboot_cmd(reader, f"setenv serverip {tftp_ip}")
    send_uboot_cmd(reader, f"setenv ipaddr {ap_ip}")
    send_uboot_cmd(reader, f"setenv rambootfile {filename}")


def run_ramboot(reader, logger: logging.Logger | None = None):
    log = logger or logging.getLogger(__name__)
    log.info("Starting ramboot")
    # We should wait a bit for the LAN interface to be (really) ready.
    # Otherwise, the TFTP connection might abort during ramboot image transfer.
    time.sleep(5)
    send_uboot_cmd(reader, "run ramboot", wait_for_prompt=False)

    ramboot_failed = r"Execute .* Fail"
    result = reader.wait_for_prompt_match(
        "|".join(["Linux version", ramboot_failed]),
        timeout=50,
    )

    if re.match(ramboot_failed, result):
        reader.log_buffer_as_error()
        raise Exception("Ramboot failed. Is TFTP server started?")

    log.info("Ramboot successfully started")
