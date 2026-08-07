"""Everything the program reads from outside itself, in one object."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from piglet.adapters.logging.setup import LogLevel

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Configuration read from the environment, falling back to `.env`, then to defaults.

    Secrets are `SecretStr`: printing the object, or logging it, cannot leak them.

    Attributes:
        openrouter_api_key: Key for the model provider. Empty until `.env` is filled.
        data_dir: Root of everything the program writes.
        cache_enabled: Whether cached responses may be read and written at all.
        cache_ttl_seconds: How long a cached response stays valid.
        http_timeout_seconds: Deadline for a single HTTP attempt.
        retry_max_attempts: How many attempts one request gets, the first included.
        log_level: Lowest level written to the log.

    Example:
        >>> settings = Settings()
        >>> settings.cache_dir
        PosixPath('data/cache')
    """

    model_config = SettingsConfigDict(
        env_prefix="PIGLET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: SecretStr = SecretStr("")
    data_dir: Path = Path("data")
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86_400
    http_timeout_seconds: float = 30.0
    retry_max_attempts: int = 4
    log_level: LogLevel = "info"

    @property
    def cache_dir(self) -> Path:
        """Directory holding cached HTTP responses."""
        return self.data_dir / "cache"

    @property
    def log_dir(self) -> Path:
        """Directory holding the JSONL logs, one file per day."""
        return self.data_dir / "logs"
