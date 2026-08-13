"""The course platform: where a task's data comes from, and where its answer goes."""

import json
from collections.abc import Sequence

from pydantic import BaseModel, SecretStr

from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.domain.http.request import HTTPMethod, HTTPRequest

__all__ = ["PlatformClient"]


class PlatformClient:
    """Downloads a task's input and submits its answer.

    Attributes:
        http_client: What sends. Retrying, backoff and the cache belong to it.
        api_key: Our key. It identifies us in the URL of a download and in the body of a
            submission, which is why both places take it from here rather than from a caller.
        base_url: Where the platform listens, without a trailing slash.

    Example:
        >>> reply = await PlatformClient(http_client, key, url).submit("people", answer)
    """

    def __init__(self, http_client: ResilientHTTPClient, api_key: SecretStr, base_url: str) -> None:
        self.http_client = http_client
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def download(self, filename: str) -> str:
        """Fetch one of the platform's data files.

        Cached, because the file does not change and a task is run many times while its code
        is still being written. Our key sits in the path, and `compute_cache_key` hashes the
        whole URL — only credential *headers* are left out of a request's identity. So a
        rotated key means a cold cache rather than a stale answer, and the key itself never
        reaches the filesystem: what is stored is a digest.

        Args:
            filename: The file's name, as the task names it.

        Returns:
            The file, decoded as text.

        Raises:
            HTTPError: If the platform refuses the request — a wrong key answers here.
            RetryExhaustedError: If it kept failing until a budget ran out.
        """
        address = f"{self.base_url}/data/{self.api_key.get_secret_value()}/{filename}"
        response = await self.http_client.send(HTTPRequest(HTTPMethod.GET, address), should_cache=True)
        return response.text

    async def submit(self, task: str, answer: Sequence[BaseModel]) -> str:
        """Send an answer, and hand back what the platform said about it.

        Not cached and not repeated: submitting twice is a second attempt at a task, not the
        same request sent again, so the client's own RFC 9110 guard is left as it is.

        Args:
            task: The task's name on the platform.
            answer: What we found, one model per record.

        Returns:
            The platform's reply, verbatim. What marks the task as solved is in there.

        Raises:
            HTTPError: If the platform rejects the submission outright.
            UnsafeToRepeatError: If the submission failed in a way that might have been
                processed, and so must not be sent again automatically.
        """
        payload = {
            "apikey": self.api_key.get_secret_value(),
            "task": task,
            "answer": [item.model_dump(mode="json") for item in answer],
        }
        request = HTTPRequest(
            HTTPMethod.POST,
            f"{self.base_url}/verify",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False).encode(),
        )
        return (await self.http_client.send(request)).text
