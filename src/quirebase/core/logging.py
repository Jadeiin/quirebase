from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_context: ContextVar[dict[str, str] | None] = ContextVar("quirebase_log_context", default=None)


@contextmanager
def log_context(**values: str | None) -> Iterator[None]:
    current = dict(_context.get() or {})
    current.update({key: value for key, value in values.items() if value})
    token = _context.set(current)
    try:
        yield
    finally:
        _context.reset(token)


class _Formatter(logging.Formatter):
    def __init__(self, *, json_output: bool, color: bool = True) -> None:
        super().__init__()
        self.json_output = json_output
        self.color = color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **(_context.get() or {}),
        }
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        if self.json_output:
            return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
        context = " ".join(f"{key}={value}" for key, value in (_context.get() or {}).items())
        suffix = f" [{context}]" if context else ""
        timestamp = datetime.now(UTC).astimezone().strftime("%m/%d/%y %H:%M:%S")
        level = f"{record.levelname:<8}"
        if self.color:
            colors = {
                "DEBUG": "36",
                "INFO": "32",
                "WARNING": "33",
                "ERROR": "31",
                "CRITICAL": "1;31",
            }
            level = f"\033[{colors.get(record.levelname, '0')}m{level}\033[0m"
        rendered = f"[{timestamp}] {level} {record.getMessage()}{suffix}"
        if record.exc_info:
            rendered = f"{rendered}\n{fields['exception']}"
        return rendered


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(json_output=json_output, color=not json_output))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    prefixes = ("quirebase", "uvicorn", "dbos", "mcp")
    names = set(prefixes)
    names.update(name for name in logging.Logger.manager.loggerDict if name.startswith(prefixes))
    for name in names:
        logger = logging.getLogger(name)
        logger.setLevel(level.upper())
        logger.handlers.clear()
        logger.propagate = True
