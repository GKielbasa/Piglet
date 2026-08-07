"""structlog configuration: one JSON object per line, one file per day.

Logs are data, not prose. Offline evaluation reads them back long after the run,
so the format has to survive being parsed by a machine rather than a human.
"""

import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import uuid4

import structlog
from pydantic import SecretStr
from structlog.typing import EventDict, Processor, WrappedLogger

__all__ = ["LogLevel", "bind_run_id", "configure_logging"]

LogLevel = Literal["debug", "info", "warning", "error"]

_LEVEL_NUMBERS: dict[LogLevel, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_REDACTION_MARK = "***"


def configure_logging(log_dir: Path, level: LogLevel = "info", secrets: Sequence[SecretStr] = ()) -> None:
    """Send every log entry as one JSON line to a file named after today's date.

    Args:
        log_dir: Directory for the JSONL files. Created when missing.
        level: Lowest level that gets written. Defaults to "info".
        secrets: Values that must never reach the log. Every occurrence is replaced
            by `***`, including inside a URL that carries a key in its path.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    # The stream stays open for the life of the process — a context manager would
    # close it before the first entry is written. Line buffering keeps the file
    # readable while the program is still running.
    stream = (log_dir / f"{date.today().isoformat()}.jsonl").open("a", encoding="utf-8", buffering=1)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _build_redactor(secrets),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=stream),
        wrapper_class=structlog.make_filtering_bound_logger(_LEVEL_NUMBERS[level]),
        cache_logger_on_first_use=True,
    )


def bind_run_id(run_id: str | None = None) -> str:
    """Attach a correlation id to every entry logged from here on.

    One run of the program produces many entries across many modules; without a
    shared id there is no way to tell one run's entries from another's.

    Args:
        run_id: The id to bind. A random one is generated when omitted.

    Returns:
        The bound id, so the caller can report or store it.
    """
    resolved = run_id or uuid4().hex
    structlog.contextvars.bind_contextvars(run_id=resolved)
    return resolved


def _build_redactor(secrets: Sequence[SecretStr]) -> Processor:
    """Build a processor replacing every known secret value with `***`.

    Args:
        secrets: The values to hide. Empty ones are ignored — an empty needle
            would otherwise match between every pair of characters.

    Returns:
        A structlog processor that rewrites string fields in place.
    """
    needles = tuple(secret.get_secret_value() for secret in secrets if secret.get_secret_value())

    def redact(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        """Replace every occurrence of a known secret in the entry's string fields."""
        if not needles:
            return event_dict
        for key, value in event_dict.items():
            if isinstance(value, str):
                redacted = value
                for needle in needles:
                    redacted = redacted.replace(needle, _REDACTION_MARK)
                event_dict[key] = redacted
        return event_dict

    return redact
