import logging
import time
from pathlib import Path

import pytest
import structlog
from structlog.testing import CapturingLogger
from structlog.typing import FilteringBoundLogger

from piglet.adapters.cache.filesystem_cache import FilesystemResponseCache
from piglet.domain.http.cache_key import CacheKey, compute_cache_key
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.ports import ResponseCache

KEY = compute_cache_key(HTTPRequest(HTTPMethod.GET, "https://example.com/list.csv"))


def unwritable_directory(tmp_path: Path) -> Path:
    """A directory that exists and refuses everything written into it."""
    directory = tmp_path / "read-only"
    directory.mkdir(mode=0o500)
    return directory


def build_recording_logger() -> tuple[CapturingLogger, FilteringBoundLogger]:
    """A bound logger that keeps every call made to it instead of writing it anywhere."""
    recorded = CapturingLogger()
    logger: FilteringBoundLogger = structlog.wrap_logger(
        recorded, processors=[], wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG)
    )
    return recorded, logger


def test_it_satisfies_the_response_cache_port(tmp_path: Path) -> None:
    # Checked by mypy, not by the assertion: the annotation is the test.
    port: ResponseCache = FilesystemResponseCache(tmp_path, ttl_seconds=60)

    assert isinstance(port, FilesystemResponseCache)


async def test_reading_an_unknown_key_is_a_miss(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)

    assert await cache.get(CacheKey("nothing-was-ever-stored-here")) is None


async def test_what_was_stored_comes_back_unchanged(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    response = HTTPResponse(200, {"Content-Type": "text/csv"}, b"name,city\n")

    await cache.store(KEY, response)

    assert await cache.get(KEY) == response


async def test_a_binary_body_survives_the_round_trip(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe"

    await cache.store(KEY, HTTPResponse(200, {}, png_header))

    restored = await cache.get(KEY)
    assert restored is not None
    assert restored.body == png_header


async def test_an_entry_past_its_ttl_is_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    await cache.store(KEY, HTTPResponse(200, {}, b"stale"))
    later = time.time() + 61

    monkeypatch.setattr(time, "time", lambda: later)

    assert await cache.get(KEY) is None


async def test_a_response_that_cannot_be_written_is_not_lost_to_an_error(tmp_path: Path) -> None:
    directory = unwritable_directory(tmp_path)
    cache = FilesystemResponseCache(directory, ttl_seconds=60)

    await cache.store(KEY, HTTPResponse(200, {}, b"unstorable"))

    assert list(directory.iterdir()) == []


async def test_a_response_that_cannot_be_written_is_reported_as_a_warning(tmp_path: Path) -> None:
    recorded, logger = build_recording_logger()
    cache = FilesystemResponseCache(unwritable_directory(tmp_path), ttl_seconds=60, logger=logger)

    await cache.store(KEY, HTTPResponse(200, {}, b"unstorable"))

    assert len(recorded.calls) == 1
    assert recorded.calls[0].method_name == "warning"
    assert recorded.calls[0].kwargs["event"] == "cache_store_failed"


async def test_the_warning_names_what_went_wrong(tmp_path: Path) -> None:
    recorded, logger = build_recording_logger()
    cache = FilesystemResponseCache(unwritable_directory(tmp_path), ttl_seconds=60, logger=logger)

    await cache.store(KEY, HTTPResponse(200, {}, b"unstorable"))

    assert recorded.calls[0].kwargs["cache_error"] == "PermissionError"


async def test_a_response_that_could_not_be_written_is_a_miss_afterwards(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(unwritable_directory(tmp_path), ttl_seconds=60)

    await cache.store(KEY, HTTPResponse(200, {}, b"unstorable"))

    assert await cache.get(KEY) is None


async def test_a_directory_that_cannot_be_created_is_reported_the_same_way(tmp_path: Path) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("something else already holds this name", encoding="utf-8")
    recorded, logger = build_recording_logger()
    cache = FilesystemResponseCache(occupied, ttl_seconds=60, logger=logger)

    await cache.store(KEY, HTTPResponse(200, {}, b"unstorable"))

    assert recorded.calls[0].kwargs["event"] == "cache_store_failed"
    assert recorded.calls[0].kwargs["cache_error"] == "FileExistsError"


async def test_a_damaged_file_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    cache = FilesystemResponseCache(tmp_path, ttl_seconds=60)
    await cache.store(KEY, HTTPResponse(200, {}, b"intact"))
    (tmp_path / f"{KEY}.json").write_text('{"status_code": 200, "body_base', encoding="utf-8")

    assert await cache.get(KEY) is None
