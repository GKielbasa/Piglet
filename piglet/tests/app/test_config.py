import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from piglet.app.config import Settings


@pytest.fixture(autouse=True)
def empty_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings reads `.env` relative to the working directory, so every test runs in
    # an empty one — otherwise the author's own `.env` would decide the assertions.
    for name in list(os.environ):
        if name.startswith("PIGLET_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_secrets_are_secretstr_and_do_not_leak_in_repr() -> None:
    settings = Settings(openrouter_api_key=SecretStr("or-2f9c-live-value"))

    assert isinstance(settings.openrouter_api_key, SecretStr)
    assert settings.openrouter_api_key.get_secret_value() == "or-2f9c-live-value"
    assert "or-2f9c-live-value" not in repr(settings)
    assert "or-2f9c-live-value" not in str(settings)


def test_defaults_are_safe() -> None:
    settings = Settings()

    assert settings.cache_enabled is True
    assert settings.cache_dir == Path("data") / "cache"
    assert settings.log_dir == Path("data") / "logs"


def test_the_http_deadline_has_a_default() -> None:
    assert Settings().http_deadline_seconds == 120.0


def test_the_http_deadline_can_be_set_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIGLET_HTTP_DEADLINE_SECONDS", "5")

    assert Settings().http_deadline_seconds == 5.0


def test_env_file_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "PIGLET_CACHE_ENABLED=false\nPIGLET_RETRY_MAX_ATTEMPTS=7\nPIGLET_DATA_DIR=/srv/piglet\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.cache_enabled is False
    assert settings.retry_max_attempts == 7
    assert settings.data_dir == Path("/srv/piglet")
