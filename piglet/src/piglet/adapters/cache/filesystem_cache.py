"""Responses remembered as files: one JSON document per request identity."""

import base64
import json
import time
from pathlib import Path

from piglet.domain.http.cache_key import CacheKey
from piglet.domain.http.response import HTTPResponse

__all__ = ["FilesystemResponseCache"]


class FilesystemResponseCache:
    """Stores responses on disk, one file per key, until they grow stale.

    The body is base64 inside the document, so an image or a zip survives the round
    trip byte for byte instead of being mangled by a text encoding.

    Attributes:
        directory: Where the files live. Created on the first write.
        ttl_seconds: How long a stored response stays valid.

    Example:
        >>> cache = FilesystemResponseCache(Path("data/cache"), ttl_seconds=3600)
    """

    def __init__(self, directory: Path, ttl_seconds: int) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_seconds

    async def get(self, key: CacheKey) -> HTTPResponse | None:
        """Read a remembered response.

        Args:
            key: Identity of the request.

        Returns:
            The stored response, or None when nothing is stored, the entry has expired,
            or the file cannot be read as one.
        """
        # Blocking reads of a small local file: a thread hop would cost more than the
        # read itself. This becomes a real question only if the cache moves off disk.
        try:
            document = json.loads(self._path_for(key).read_text(encoding="utf-8"))
            if time.time() - float(document["stored_at"]) > self.ttl_seconds:
                return None
            return HTTPResponse(
                status_code=int(document["status_code"]),
                headers=dict(document["headers"]),
                body=base64.b64decode(document["body_base64"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            # A half-written or hand-edited file is a miss, not a crash: the answer is
            # one network call away, and refusing to serve it helps nobody.
            return None

    async def store(self, key: CacheKey, response: HTTPResponse) -> None:
        """Remember a response under a key.

        Args:
            key: Identity of the request.
            response: What to remember.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        document = {
            "stored_at": time.time(),
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body_base64": base64.b64encode(response.body).decode("ascii"),
        }
        self._path_for(key).write_text(json.dumps(document), encoding="utf-8")

    def _path_for(self, key: CacheKey) -> Path:
        """Map a key to the file that holds it.

        Args:
            key: Identity of the request.

        Returns:
            Path of the document, whether or not it exists.
        """
        return self.directory / f"{key}.json"
