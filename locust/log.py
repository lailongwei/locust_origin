import os.path
import logging
import logging.config
import socket

HOSTNAME = socket.gethostname()

# Global flag that we set to True if any unhandled exception occurs in a greenlet
# Used by main.py to set the process return code to non-zero
unhandled_greenlet_exception = False


class LogReader(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []

    def emit(self, record):
        self.logs.append(self.format(record))


def setup_logging(loglevel, logfile=None, console_loglevel: str | None = None, file_loglevel: str | None = None):
    loglevel = loglevel.upper()

    if console_loglevel is None:
        console_loglevel = loglevel
    if file_loglevel is None:
        file_loglevel = loglevel

    min_loglevel_value = min(logging.getLevelName(console_loglevel), logging.getLevelName(file_loglevel))
    if logging.getLevelName(loglevel) < min_loglevel_value:
        loglevel = logging.getLevelName(min_loglevel_value)

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": f"[%(asctime)s] {HOSTNAME}/%(levelname)-5s/%(name)s: %(message)s",
            },
            "plain": {
                "format": "%(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": console_loglevel,
            },
            "console_plain": {
                "class": "logging.StreamHandler",
                "formatter": "plain",
                "level": console_loglevel,
            },
            "log_reader": {
                "class": "locust.log.LogReader",
                "formatter": "default",
                "level": console_loglevel,
            },
        },
        "loggers": {
            "locust": {
                "handlers": ["console"],
                "level": loglevel,
                "propagate": False,
            },
            "locust.teddy": {
                "handlers": ["console"],
                "level": loglevel,
                "propagate": False,
            },
            "locust.network": {
                "handlers": [],
                "level": loglevel,
                "propagate": False,
            },
            "locust.stats_logger": {
                "handlers": ["console_plain"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": loglevel,
        },
    }
    if logfile:
        # if a file has been specified add a file logging handler and set
        # the locust and root loggers to use it
        LOGGING_CONFIG["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": logfile,
            "formatter": "default",
            "mode": "a",
            "maxBytes": 1024 * 1024 * 512,
            "encoding": "utf-8",
            "backupCount": 10,
            "level": file_loglevel,
        }

        LOGGING_CONFIG["handlers"]["network_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.splitext(logfile)[0] + '_network' + os.path.splitext(logfile)[1],
            "formatter": "default",
            "mode": "a",
            "maxBytes": 1024 * 1024 * 512,
            "encoding": "utf-8",
            "backupCount": 10,
            "level": file_loglevel,
            "delay": True
        }

        LOGGING_CONFIG["loggers"]["locust"]["handlers"] = ["console", "file"]
        LOGGING_CONFIG["loggers"]["locust.teddy"]["handlers"] = ["console", "file"]
        LOGGING_CONFIG["loggers"]["locust.network"]["handlers"] = ["console", "file"]
        LOGGING_CONFIG["root"]["handlers"] = ["console", "file"]

    logging.config.dictConfig(LOGGING_CONFIG)


def greenlet_exception_logger(logger, level=logging.CRITICAL):
    """
    Return a function that can be used as argument to Greenlet.link_exception() that will log the
    unhandled exception to the given logger.
    """

    def exception_handler(greenlet):
        if greenlet.exc_info[0] == SystemExit:
            logger.log(
                min(logging.INFO, level),  # dont use higher than INFO for this, because it sounds way to urgent
                "sys.exit(%s) called (use log level DEBUG for callstack)" % greenlet.exc_info[1],
            )
            logger.log(logging.DEBUG, "Unhandled exception in greenlet: %s", greenlet, exc_info=greenlet.exc_info)
        else:
            logger.log(level, "Unhandled exception in greenlet: %s", greenlet, exc_info=greenlet.exc_info)
        global unhandled_greenlet_exception
        unhandled_greenlet_exception = True

    return exception_handler
