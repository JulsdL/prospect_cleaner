import logging
from logging.config import dictConfig

_LOG_LEVEL = "INFO"

dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "std": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "std",
        }
    },
    "root": {
        "level": _LOG_LEVEL,
        "handlers": ["console"],
    },
})

logger = logging.getLogger("hublead")
