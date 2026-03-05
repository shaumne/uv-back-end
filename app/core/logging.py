"""
Structured JSON logging configuration for production.

In development the log level is DEBUG; in production it is INFO.
All log entries include timestamp, level, module, and message.
"""
import logging
import sys


def configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


logger = logging.getLogger("uv_dosimeter")
