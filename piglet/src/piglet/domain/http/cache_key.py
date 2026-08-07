"""The identity of a request: the same question always gets the same key."""

import hashlib
from typing import NewType

from piglet.domain.http.request import HTTPRequest

__all__ = ["CacheKey", "compute_cache_key"]

CacheKey = NewType("CacheKey", str)

# Credentials say who is asking, not what is being asked. Two requests differing only
# by their key ask the same question — and a key must never end up in a file name.
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key"})


def compute_cache_key(request: HTTPRequest) -> CacheKey:
    """Derive a stable identifier for a request.

    Two requests share a key when their method, address, body and non-credential
    headers match, whatever order the headers arrived in.

    Args:
        request: The request to identify.

    Returns:
        A hex digest, safe to use as a file name.
    """
    digest = hashlib.sha256()
    digest.update(f"{request.method}\n{request.url}\n".encode())
    identifying_headers = sorted(
        (name.lower(), value) for name, value in request.headers.items() if name.lower() not in _CREDENTIAL_HEADERS
    )
    for name, value in identifying_headers:
        digest.update(f"{name}:{value}\n".encode())
    digest.update(b"\n")
    digest.update(request.body or b"")
    return CacheKey(digest.hexdigest())
