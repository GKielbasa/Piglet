# piglet

Universal agent tooling, written in Python alongside the AI_devs 4: Builders course.

The tools know nothing about the course. Each lesson contributes a generic problem — a
resilient HTTP client, enforced response schemas, a tool registry, retrieval — and what
gets built is that problem's solution, not the lesson's answer. The flag is a by-product.

Today the library is one primitive: **an asynchronous HTTP client that survives transient
failures, remembers answers and records every attempt.**

## Requirements

Python 3.12+ and [uv](https://docs.astral.sh/uv/). No `pip` in this project.

```bash
uv sync
cp .env.example .env   # then fill in what you have; every value has a default
```

## Use

```bash
uv run piglet version
uv run piglet config                                    # secrets masked, paths resolved
uv run piglet http get https://example.com --cache      # fetch, cache, log
uv run piglet http get https://example.com --cache      # again: served from disk, no traffic
uv run piglet http get https://httpbin.org/status/503   # retries with backoff, then exits 1
```

Every attempt lands in `data/logs/<date>.jsonl`, one JSON object per line:

```json
{"url": "https://example.com", "method": "GET", "status_code": 200, "attempt": 1,
 "duration_ms": 92.596, "cache_hit": false, "event": "http_attempt_finished",
 "run_id": "ea3fdb98...", "level": "info", "timestamp": "2026-08-06T16:20:11.913Z"}
```

From code:

```python
import asyncio

from piglet.app.config import Settings
from piglet.app.container import build_http_client, start_run
from piglet.domain.http.request import HTTPMethod, HTTPRequest


async def main() -> None:
    settings = Settings()
    start_run(settings)
    async with build_http_client(settings) as client:
        answer = await client.send(HTTPRequest(HTTPMethod.GET, "https://example.com"), should_cache=True)
    print(answer.status_code, len(answer.body))


asyncio.run(main())
```

## Layout

```
src/piglet/
├── errors.py              exception hierarchy
├── domain/                values, decisions, contracts — no I/O, no imports from above
│   ├── http/              request, response, retry policy, cache key
│   └── ports.py           HTTPTransport, ResponseCache, Sleeper
├── adapters/              httpx, filesystem cache, structlog
└── app/                   configuration, composition root, CLI
```

`docs/ARCHITECTURE.md` explains the layering and what is coming; `docs/adr/` records why
each hard-to-reverse decision was made.

## Quality gates

All four must be green before any step counts as done:

```bash
uv run ruff format .
uv run ruff check --fix .
uv run mypy
uv run pytest -q
```

They are also automated: a `PostToolUse` hook runs ruff and mypy after every `.py` write,
and a `Stop` hook runs all four before a coding turn is allowed to end.

Green gates only prove the code is coherent. A step is closed by running the thing that was
just built and reading what came back — the rule, and the reasoning, are in `CLAUDE.md`.
