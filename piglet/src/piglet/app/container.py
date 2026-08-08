"""The composition root: objects are wired here by hand, and nowhere else.

There is no container with autowiring. Everything below is an explicit constructor
call, so the whole object graph can be read in one screen — and a caller that wants a
different transport or no cache at all simply builds one itself.
"""

import asyncio

import httpx

from piglet.adapters.cache.filesystem_cache import FilesystemResponseCache
from piglet.adapters.http.httpx_transport import HttpxTransport
from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.adapters.logging.setup import bind_run_id, configure_logging
from piglet.app.config import Settings
from piglet.domain.http.retry_policy import RetryPolicy
from piglet.domain.http.service_profile import ServiceProfile

__all__ = ["build_http_client", "start_run"]


def start_run(settings: Settings) -> str:
    """Open the log for this run and give the run an identity.

    Args:
        settings: Where the log goes, how loud it is, and which values it must hide.

    Returns:
        The run id, which every entry of this run will carry.
    """
    configure_logging(settings.log_dir, settings.log_level, secrets=[settings.openrouter_api_key])
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
    retry_policy = RetryPolicy(max_attempts=settings.retry_max_attempts)
    return ResilientHTTPClient(transport, retry_policy, profile or ServiceProfile(), asyncio.sleep, cache)
