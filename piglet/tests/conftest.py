import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from piglet.app.config import Settings
from piglet.application.platform_settings import PlatformSettings


@pytest.fixture(autouse=True)
def empty_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Both settings classes read the project's own `.env`, so every test is pointed at an empty
    # directory instead. Otherwise the author's own `.env` — their real key included — decides
    # the assertions of every test that builds a Settings(), and the suite passes or fails by
    # what is on this machine rather than by what the code does.
    for name in list(os.environ):
        if name.startswith("PIGLET_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / ".env")
    monkeypatch.setitem(PlatformSettings.model_config, "env_file", tmp_path / ".env")
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def clean_structlog() -> Iterator[None]:
    # structlog configuration is global; without a reset one test's log file would
    # keep collecting the next test's entries.
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
