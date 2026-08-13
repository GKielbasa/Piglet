"""The composition root: objects are wired here by hand, and nowhere else.

There is no container with autowiring. Everything below is an explicit constructor
call, so the whole object graph can be read in one screen — and a caller that wants a
different transport or no cache at all simply builds one itself.
"""

import asyncio
from collections.abc import Sequence

import httpx
from pydantic import SecretStr

from piglet.adapters.cache.filesystem_cache import FilesystemResponseCache
from piglet.adapters.http.httpx_transport import HttpxTransport
from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.adapters.llm.openrouter_chat import OpenRouterChatModel
from piglet.adapters.llm.recording_chat import RecordingChatModel
from piglet.adapters.logging.setup import bind_run_id, configure_logging
from piglet.app.config import Settings
from piglet.domain.http.retry_policy import RetryPolicy
from piglet.domain.http.service_profile import ServiceProfile
from piglet.domain.ports import ChatModel

__all__ = ["build_chat_model", "build_http_client", "build_llm_http_client", "start_run"]


def start_run(settings: Settings, secrets: Sequence[SecretStr] = ()) -> str:
    """Open the log for this run and give the run an identity.

    Args:
        settings: Where the log goes, how loud it is, and which values it must hide.
        secrets: Further values that must never reach the log. A caller that holds
            credentials of its own passes them here — a key travelling in a URL path is
            written to the log by every attempt otherwise.

    Returns:
        The run id, which every entry of this run will carry.
    """
    configure_logging(settings.log_dir, settings.log_level, secrets=[settings.openrouter_api_key, *secrets])
    return bind_run_id()


def build_http_client(settings: Settings, profile: ServiceProfile | None = None) -> ResilientHTTPClient:
    """Assemble the HTTP client described by the configuration.

    Args:
        settings: Timeouts, retry budget and cache switches.
        profile: What this service's statuses mean. None takes the standard set, which
            is right until a service disagrees; one integration then passes its own here
            rather than editing anything.

    Returns:
        A client to be used as an async context manager, so its connection pool is
        released when the block ends.
    """
    transport = HttpxTransport(httpx.AsyncClient(timeout=settings.http_timeout_seconds))
    cache = FilesystemResponseCache(settings.cache_dir, settings.cache_ttl_seconds) if settings.cache_enabled else None
    retry_policy = RetryPolicy(
        max_attempts=settings.retry_max_attempts, max_total_seconds=settings.http_deadline_seconds
    )
    return ResilientHTTPClient(transport, retry_policy, profile or ServiceProfile(), asyncio.sleep, cache)


def build_llm_http_client(settings: Settings) -> ResilientHTTPClient:
    """Assemble the client model calls travel through.

    Its own client rather than the one above, for two reasons. A completion needs minutes where
    a file needs seconds. And it carries no cache at all: a provider reports a failure that
    happened mid-generation inside a successful response, which the cache would otherwise
    remember and serve back for as long as the entry lived.

    The standard `ServiceProfile` is right here without a line of configuration — OpenRouter's
    documented statuses are exactly the ones it already knows.

    Args:
        settings: Timeouts, the retry budget and the provider's address.

    Returns:
        A client to be used as an async context manager, so its connection pool is released
        when the block ends.
    """
    transport = HttpxTransport(httpx.AsyncClient(timeout=settings.llm_timeout_seconds))
    retry_policy = RetryPolicy(
        max_attempts=settings.retry_max_attempts, max_total_seconds=settings.llm_deadline_seconds
    )
    return ResilientHTTPClient(transport, retry_policy, ServiceProfile(), asyncio.sleep)


def build_chat_model(settings: Settings, http_client: ResilientHTTPClient, run_id: str) -> ChatModel:
    """Assemble the model client for one run.

    Args:
        settings: Credentials, the provider's address, and whether exchanges are kept.
        http_client: The cacheless client from `build_llm_http_client`.
        run_id: Identity of this run. One run's exchanges share a directory.

    Returns:
        The provider's client, wrapped so that every exchange is written down — or the bare
        client when the configuration says the exchanges must not be kept.
    """
    model: ChatModel = OpenRouterChatModel(
        http_client, settings.openrouter_api_key, settings.llm_model, settings.llm_base_url
    )
    if not settings.record_exchanges:
        return model
    return RecordingChatModel(model, settings.runs_dir / run_id)
