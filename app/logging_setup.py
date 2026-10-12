from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("clinic_antiviral")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    expected_path = str(log_path.resolve()).casefold()
    for handler in list(logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        if str(Path(handler.baseFilename).resolve()).casefold() == expected_path:
            return logger
        logger.removeHandler(handler)
        handler.close()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
