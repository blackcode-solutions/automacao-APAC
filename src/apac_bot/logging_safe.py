from __future__ import annotations

import logging
import re
from typing import Optional

# Padrões grosseiros para evitar vazamento acidental em mensagens.
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CNS_RE = re.compile(r"\b\d{15}\b")


def redact(text: str) -> str:
    text = _CPF_RE.sub("[CPF]", text)
    text = _CNS_RE.sub("[CNS]", text)
    return text


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("apac_bot")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        handler.addFilter(_RedactFilter())
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


def short_id(value: Optional[str], n: int = 8) -> str:
    if not value:
        return "-"
    return value[:n]
