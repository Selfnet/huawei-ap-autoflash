import logging


def debug_logging_enabled():
    return logging.getLogger().level == logging.DEBUG
