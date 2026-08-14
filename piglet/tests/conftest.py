import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog


@pytest.fixture(autouse=True)
def empty_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings reads `.env` relative to the working directory, so every test runs in an empty
    # one. Otherwise the author's own `.env` — their real key included — decides the assertions
    # of every test that builds a Settings(), and the suite passes or fails by what is on this
    # machine rather than by what the code does.
    for name in list(os.environ):
        if name.startswith("PIGLET_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def clean_structlog() -> Iterator[None]:
    # structlog configuration is global; without a reset one test's log file would
    # keep collecting the next test's entries.
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
