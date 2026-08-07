"""The command line: a shell over the composition root, holding no logic of its own.

Everything here reads arguments, calls one function and prints what came back. When an
HTTP interface arrives it will call the same functions, which is the point of keeping
this file thin.
"""

import asyncio
from importlib import metadata
from typing import Annotated

import typer

from piglet.app.config import Settings
from piglet.app.container import build_http_client, start_run
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.errors import PigletError

__all__ = ["app"]

_BODY_PREVIEW_CHARACTERS = 500

app = typer.Typer(help="Universal agent tooling.", no_args_is_help=True)
http_commands = typer.Typer(help="Send requests through the resilient HTTP client.", no_args_is_help=True)
app.add_typer(http_commands, name="http")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(metadata.version("piglet"))


@app.command()
def config() -> None:
    """Print the effective configuration, with secrets masked."""
    settings = Settings()
    for name, value in settings.model_dump().items():
        typer.echo(f"{name} = {value}")
    typer.echo(f"cache_dir = {settings.cache_dir}")
    typer.echo(f"log_dir = {settings.log_dir}")


@http_commands.command("get")
def http_get(
    url: str,
    should_cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Read and write this answer in the cache.")
    ] = False,
) -> None:
    """Fetch a URL, retrying while the failure looks transient."""
    settings = Settings()
    run_id = start_run(settings)
    try:
        response = asyncio.run(_fetch(settings, url, should_cache=should_cache))
    except PigletError as failure:
        typer.echo(f"error: {failure}", err=True)
        typer.echo(f"run_id: {run_id}", err=True)
        raise typer.Exit(code=1) from failure

    typer.echo(f"run_id: {run_id}")
    typer.echo(f"status: {response.status_code}")
    typer.echo(f"bytes: {len(response.body)}")
    typer.echo(response.text[:_BODY_PREVIEW_CHARACTERS])


async def _fetch(settings: Settings, url: str, should_cache: bool) -> HTTPResponse:
    """Fetch one URL with a client built for this run.

    Args:
        settings: Configuration for the client.
        url: The address to fetch.
        should_cache: Whether the answer may come from, and go to, the cache.

    Returns:
        The successful response.
    """
    async with build_http_client(settings) as client:
        return await client.send(HTTPRequest(HTTPMethod.GET, url), should_cache=should_cache)
