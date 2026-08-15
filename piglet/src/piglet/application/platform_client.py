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

    async def ask(self, endpoint: str, question: BaseModel) -> str:
        """Put a question to one of the platform's API endpoints.

        Our key joins the question here rather than at the call site, for the same reason it
        does in the two methods around this one: a caller that has to remember to add a
        credential is a caller that will one day forget.

        Not cached. These endpoints answer about people rather than about files, and an answer
        remembered for a day would outlive the question that is actually being asked.

        Args:
            endpoint: The endpoint's name under `/api/`.
            question: What to ask, without the key. A model rather than a mapping, so the
                platform's own spelling of a field lives in a `serialization_alias` beside
                every other wire name instead of in a dictionary literal at the call site.

        Returns:
            The answer as text, for the caller to read into a shape of its own.

        Raises:
            HTTPError: If the platform refuses. Its own explanation is on `body_preview`, which
                is the only place the reason for a refusal survives.
            RetryExhaustedError: If it kept failing until a budget ran out.
        """
        request = HTTPRequest(
            HTTPMethod.POST,
            f"{self.base_url}/api/{endpoint}",
            headers={"Content-Type": "application/json"},
            body=json.dumps(
                {"apikey": self.api_key.get_secret_value(), **question.model_dump(mode="json", by_alias=True)},
                ensure_ascii=False,
            ).encode(),
        )
        # Asking twice is asking the same question twice: these endpoints report, they do not
        # change anything, and RFC 9110 has no way of knowing that about a POST.
        return (await self.http_client.send(request, is_safe_to_repeat=True)).text

    async def submit(self, task: str, answer: BaseModel | Sequence[BaseModel]) -> str:
        """Send an answer, and hand back what the platform said about it.

        Not cached and not repeated: submitting twice is a second attempt at a task, not the
        same request sent again, so the client's own RFC 9110 guard is left as it is.

        Args:
            task: The task's name on the platform.
            answer: What we found — a list of records, or a single object where the task asks
                for one. The distinction is the platform's and is carried through unchanged: a
                task expecting one object rejects a list of one.

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
            "answer": _as_json(answer),
        }
        request = HTTPRequest(
            HTTPMethod.POST,
            f"{self.base_url}/verify",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False).encode(),
        )
        return (await self.http_client.send(request)).text


def _as_json(answer: BaseModel | Sequence[BaseModel]) -> object:
    """Turn what a task found into the shape its `answer` field takes.

    Aliases are honoured, because the platform's field names are not ours: a model spelling a
    field `access_level` sends it as `accessLevel` when it declares that alias, and PEP 8 does
    not have to lose to a wire format.

    Args:
        answer: One record or several.

    Returns:
        A JSON object for one, a JSON array for several.
    """
    if isinstance(answer, BaseModel):
        return answer.model_dump(mode="json", by_alias=True)
    return [item.model_dump(mode="json", by_alias=True) for item in answer]
