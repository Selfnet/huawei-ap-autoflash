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
PROMPT_CONFIRM_OLD_PASSWORD = r"Confirm old password\s*:"
PROMPT_ENTER_NEW_PASSWORD = r"Please enter new password\s*:"
PROMPT_CONFIRM_NEW_PASSWORD = r"Please confirm new password\s*:"
PASSWORD_CHANGED = r"The password is changed successfully\."
PASSWORD_WRONG = r"Password is wrong, System will reboot"


class WrongBootloaderPasswordError(Exception):
    """Raised when none of the supplied bootloader passwords works."""


def ensure_ready(
    reader,
    passwords: list[str],
    new_password: str,
    logger: logging.Logger | None = None,
) -> str | None:
    """
    The script can be started at two points in time:
        1. Before the AP is powered on. Then, we have to stop auto-boot AND enter the password
        2. After the AP has been powered on for a while. Then, we only have to enter the password.
           We only get the prompt when we press enter.
        3. The password has already been entered. We only get the prompt when we press enter.
    """
    log = logger or logging.getLogger(__name__)
    reader.write(b"\n")
    password_index = 0
    for _ in range(8):
        m = reader.wait_for_prompt_match(
            "|".join(
                [
                    PROMPT_STOP_AUTOBOOT,
                    PROMPT_PASSWORD,
                    PROMPT_UBOOT_READY,
                    PROMPT_SKIP_BUS_TEST,
                    PROMPT_NEW_PASSWORD,
                    PROMPT_CONFIRM_PASSWORD,
                    PASSWORD_WRONG,
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
            if password_index == len(passwords):
                reader.log_buffer_as_error()
                raise WrongBootloaderPasswordError(
                    "None of the supplied U-Boot passwords worked. The AP "
                    "allows at most three attempts before rebooting."
                )
            time.sleep(0.2)
            reader.write(f"{passwords[password_index]}\n".encode("utf-8"))
            password_index += 1
        elif m == PROMPT_NEW_PASSWORD or m == PROMPT_CONFIRM_PASSWORD:
            time.sleep(0.2)
            reader.write(f"{new_password}\n".encode("utf-8"))
        elif m == PROMPT_UBOOT_READY:
            log.info("U-Boot ready")
            return passwords[password_index - 1] if password_index else None
        elif m == PASSWORD_WRONG:
            reader.log_buffer_as_error()
            raise WrongBootloaderPasswordError(
                "None of the supplied U-Boot passwords worked. The AP is rebooting."
            )
        else:
            reader.log_buffer_as_error()
            raise Exception("Unexpected prompt")

    raise Exception("U-Boot did not become ready after several prompts")


def send_uboot_cmd(reader, cmd: str, wait_for_prompt=True):
    reader.write(f"{cmd}\n".encode("utf-8"))
    if wait_for_prompt:
        reader.wait_for_prompt_match(PROMPT_UBOOT_READY)


def change_password(
    reader,
    old_password: str,
    new_password: str,
    logger: logging.Logger | None = None,
):
    log = logger or logging.getLogger(__name__)
    log.info("Changing U-Boot password")
    reader.write(b"passwd\n")
    reader.wait_for_prompt_match(PROMPT_CONFIRM_OLD_PASSWORD)
    reader.write(f"{old_password}\n".encode("utf-8"))
    reader.wait_for_prompt_match(PROMPT_ENTER_NEW_PASSWORD)
    reader.write(f"{new_password}\n".encode("utf-8"))
    reader.wait_for_prompt_match(PROMPT_CONFIRM_NEW_PASSWORD)
    reader.write(f"{new_password}\n".encode("utf-8"))
    reader.wait_for_prompt_match(
        rf"{PASSWORD_CHANGED}\s*{PROMPT_UBOOT_READY}"
    )
    log.info("U-Boot password changed")


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
