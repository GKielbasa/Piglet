"""Everything the program reads from outside itself, in one object."""

from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from piglet.adapters.logging.setup import LogLevel

__all__ = ["PROJECT_ROOT", "Settings"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
"""The directory holding `pyproject.toml`, `prompts/`, `data/` and `.env`.

Found from this file's own location, so every path the program uses points at the same place
whichever directory it was started from.
"""


class Settings(BaseSettings):
    """Configuration read from the environment, falling back to `.env`, then to defaults.

    Secrets are `SecretStr`: printing the object, or logging it, cannot leak them.

    Attributes:
        openrouter_api_key: Key for the model provider. Empty until `.env` is filled.
        data_dir: Root of everything the program writes.
        cache_enabled: Whether cached responses may be read and written at all.
        cache_ttl_seconds: How long a cached response stays valid.
        http_timeout_seconds: Deadline for a single HTTP attempt.
        http_deadline_seconds: Deadline for one request including every retry, so a
            service that answers slowly cannot hold a run open indefinitely.
        retry_max_attempts: How many attempts one request gets, the first included.
        llm_model: Which model answers when a call names none.
        llm_base_url: Where the model provider listens.
        llm_timeout_seconds: Deadline for a single model call. Far longer than its HTTP sibling:
            a file arrives in seconds, a batch of twenty records can take minutes.
        llm_deadline_seconds: Deadline for one model call including every retry.
        prompts_dir: Where prompt files live, one markdown file per prompt.
        record_exchanges: Whether what was said to a model, and what it said back, is written
            to disk. The log records what a call cost; this records what it contained, and it
            cannot be reconstructed afterwards. Switch it off where the prompts carry data
            that must not be kept.
        log_level: Lowest level written to the log.

    Example:
        >>> settings = Settings()
        >>> settings.cache_dir
        PosixPath('data/cache')
    """

    model_config = SettingsConfigDict(
        env_prefix="PIGLET_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: SecretStr = SecretStr("")
    data_dir: Path = PROJECT_ROOT / "data"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86_400
    http_timeout_seconds: float = 30.0
    http_deadline_seconds: float = 120.0
    retry_max_attempts: int = 4
    llm_model: str = "openai/gpt-4.1-mini"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = 120.0
    llm_deadline_seconds: float = 300.0
    prompts_dir: Path = PROJECT_ROOT / "prompts"
    record_exchanges: bool = True
    log_level: LogLevel = "info"

    @field_validator("data_dir", "prompts_dir")
    @classmethod
    def _anchor_to_the_project(cls, value: Path) -> Path:
        """Read a relative override as relative to the project, never to the shell's location."""
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def cache_dir(self) -> Path:
        """Directory holding cached HTTP responses."""
        return self.data_dir / "cache"

    @property
    def log_dir(self) -> Path:
        """Directory holding the JSONL logs, one file per day."""
        return self.data_dir / "logs"

    @property
    def runs_dir(self) -> Path:
        """Directory holding what was said in each run, one subdirectory per run."""
        return self.data_dir / "runs"

    @property
    def answers_dir(self) -> Path:
        """Directory holding what each finished run answered, one document per name.

        Written so a later run can read it: the answer to one question is regularly the input to
        the next, and the alternative is doing the first piece of work again to get at it.
        """
        return self.data_dir / "answers"
