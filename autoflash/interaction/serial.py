import re
import time
import logging


class PromptTimeoutError(Exception):
    def __init__(self, regex: str, buffer: str):
        super().__init__(f"Timeout waiting for prompt: '{regex}'")
        self.regex = regex
        self.buffer = buffer


class SerialReader:
    """Wraps a pyserial Serial object and owns a per-instance read buffer.

    Each AP gets its own SerialReader, so parallel workers don't share
    buffer state. The wrapper also routes raw serial bytes to a logger at
    DEBUG level instead of writing them to stdout, so per-AP log files /
    GUI panels stay clean.
    """

    def __init__(self, ser, logger: logging.Logger | None = None):
        self.ser = ser
        self.logger = logger or logging.getLogger(__name__)
        self.buffer = ""

    def write(self, data: bytes):
        self.ser.write(data)

    def in_waiting(self) -> int:
        return self.ser.inWaiting()

    def read_available(self) -> str:
        n = self.ser.inWaiting()
        if n == 0:
            n = 1
        chunk = self.ser.read(n).decode("utf-8", errors="ignore")
        if chunk:
            self.logger.debug("serial<< %r", chunk)
        return chunk

    def reset_buffer(self):
        self.buffer = ""

    def log_buffer_as_error(self):
        for line in self.buffer.splitlines():
            self.logger.error(line)

    def wait_for_prompt_match(self, prompt_regex: str, timeout: float = 60) -> str:
        self.buffer = ""
        start = time.time()
        while time.time() - start < timeout:
            self.buffer += self.read_available()
            match = re.search(prompt_regex, self.buffer)
            if match:
                return match.group(0)

        self.log_buffer_as_error()
        raise PromptTimeoutError(prompt_regex, self.buffer)
