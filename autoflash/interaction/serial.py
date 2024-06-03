import re
import sys
from ..log import debug_logging_enabled


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
