"""What the course platform needs to know us, kept out of the tooling layer's settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["PlatformSettings"]


class PlatformSettings(BaseSettings):
    """Credentials and addresses for the AI_devs platform.

    A settings object of its own rather than more fields on `piglet.app.config.Settings`,
    because nothing under `app/`, `adapters/` or `domain/` may know this course exists. Here it
    may, which is the whole purpose of this layer.

    Attributes:
        api_hub: The key, read from `API_HUB`. It travels in the URL path of every download,
            so it must also reach the log's redactor — a URL is written to the log on every
            attempt.
        base_url: Where the platform listens.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_hub: SecretStr = SecretStr("")
    base_url: str = "https://hub.ag3nts.org"
