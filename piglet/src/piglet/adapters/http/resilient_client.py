"""One request in, one response out — retries, cache and a log entry per attempt."""

import time
from types import TracebackType
from typing import Self

import structlog
from structlog.typing import FilteringBoundLogger

from piglet.domain.http.cache_key import CacheKey, compute_cache_key
from piglet.domain.http.request import HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import RetryPolicy
from piglet.domain.ports import HTTPTransport, ResponseCache, Sleeper
from piglet.errors import HTTPError, RetryExhaustedError

__all__ = ["ResilientHTTPClient"]


class ResilientHTTPClient:
    """Sends a request and keeps at it while the failure looks transient.

    Every attempt leaves a log entry, so a run can be reconstructed afterwards from
    the log alone. Caching is decided per call: the same address may be worth
    remembering in one place and pointless to remember in another.

    Attributes:
        transport: What actually sends.
        retry_policy: Decides whether to try again and how long to wait first.
        sleep: How waiting happens. Injected so a test can record it instead.
        cache: Where answers are remembered, or None when caching is switched off.
        logger: Where attempts are recorded.

    Example:
        >>> async with ResilientHTTPClient(transport, RetryPolicy(), asyncio.sleep) as client:
        ...     answer = await client.send(HTTPRequest(HTTPMethod.GET, "https://example.com"))
    """

    def __init__(
        self,
        transport: HTTPTransport,
        retry_policy: RetryPolicy,
        sleep: Sleeper,
        cache: ResponseCache | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self.transport = transport
        self.retry_policy = retry_policy
        self.sleep = sleep
        self.cache = cache
        self.logger = logger or structlog.get_logger()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.transport.aclose()

    async def send(self, request: HTTPRequest, should_cache: bool = False) -> HTTPResponse:
        """Send a request, retrying while the policy says the failure may pass.

        Args:
            request: What to send.
            should_cache: Whether this answer may be read from and written to the cache.

        Returns:
            The successful response.

        Raises:
            HTTPError: If the first answer was a failure the policy will not repeat —
                the request itself is wrong, so trying again changes nothing.
            RetryExhaustedError: If the failure looked transient but outlived every
                attempt the policy allowed.
            TransportError: If no response arrived at all.
        """
        key = compute_cache_key(request) if should_cache and self.cache is not None else None
        remembered = await self._recall(request, key)
        if remembered is not None:
            return remembered

        delay_used_seconds = 0.0
        attempt = 0
        while True:
            attempt += 1
            response = await self._send_once(request, attempt)

            if response.is_success:
                if key is not None and self.cache is not None:
                    await self.cache.store(key, response)
                return response

            decision = self.retry_policy.decide(response, attempt, delay_used_seconds)
            if not decision.should_retry:
                if attempt == 1:
                    raise HTTPError(request.url, response.status_code)
                raise RetryExhaustedError(request.url, attempt, response.status_code)

            await self.sleep(decision.delay_seconds)
            delay_used_seconds += decision.delay_seconds

    async def _send_once(self, request: HTTPRequest, attempt: int) -> HTTPResponse:
        """Make one attempt and record how it went.

        Args:
            request: What to send.
            attempt: Which attempt this is, counting from 1.

        Returns:
            Whatever came back.
        """
        started = time.perf_counter()
        response = await self.transport.send(request)
        self.logger.info(
            "http_attempt_finished",
            url=request.url,
            method=request.method.value,
            status_code=response.status_code,
            attempt=attempt,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            cache_hit=False,
        )
        return response

    async def _recall(self, request: HTTPRequest, key: CacheKey | None) -> HTTPResponse | None:
        """Look for a remembered answer and record the hit.

        Args:
            request: The request being answered, for the log entry.
            key: Identity of the request, or None when this call skips the cache.

        Returns:
            The remembered response, or None when there is nothing to serve.
        """
        if key is None or self.cache is None:
            return None
        remembered = await self.cache.get(key)
        if remembered is None:
            return None
        self.logger.info(
            "http_attempt_finished",
            url=request.url,
            method=request.method.value,
            status_code=remembered.status_code,
            attempt=0,
            duration_ms=0.0,
            cache_hit=True,
        )
        return remembered
