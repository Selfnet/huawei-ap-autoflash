import logging


FORMAT = "%(asctime)s - %(levelname)s: %(message)s"
DATEFMT = "%d.%m.%Y %H:%M:%S"


def debug_logging_enabled():
    return logging.getLogger().level == logging.DEBUG
