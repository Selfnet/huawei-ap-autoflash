import re
import sys
import time
import logging
from ..log import debug_logging_enabled

_buffer = ""


def log_buffer_as_error():
    for line in _buffer.splitlines():
        logging.error(line)


def wait_for_prompt_match(ser, prompt_regex, timeout=60):
    global _buffer
    _buffer = ""
    start = time.time()
    while time.time() - start < timeout:
        # There might be weird things happening over serial
        # (eg. the AP resets before everything is transmitted).
        # Therefore, we have to ignore decoding errors here.
        bytes_to_read = 1 if ser.inWaiting() == 0 else ser.inWaiting()
        new_read = ser.read(bytes_to_read).decode("utf-8", errors="ignore")
        if debug_logging_enabled():
            print(new_read, end="")
            sys.stdout.flush()

        _buffer += new_read

        match = re.search(prompt_regex, _buffer)
        if match:
            return match.group(0)

    log_buffer_as_error()
    raise Exception(f"Timeout waiting for prompt: '{prompt_regex}'")
