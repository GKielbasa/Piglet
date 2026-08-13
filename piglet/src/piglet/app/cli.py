"""The command line: a shell over the composition root, holding no logic of its own.

Everything here reads arguments, calls one function and prints what came back. When an
HTTP interface arrives it will call the same functions, which is the point of keeping
this file thin.
"""

import asyncio
from importlib import metadata
from typing import Annotated

import typer

from piglet.adapters.prompts.markdown_prompt_library import MarkdownPromptLibrary
from piglet.app.config import Settings
from piglet.app.container import build_chat_model, build_http_client, build_llm_http_client, start_run
from piglet.application.tasks import run_task
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.llm.chat import ChatCompletion, ChatMessage, ChatRequest, Role
from piglet.errors import PigletError

__all__ = ["app"]

_BODY_PREVIEW_CHARACTERS = 500

app = typer.Typer(help="Universal agent tooling.", no_args_is_help=True)
http_commands = typer.Typer(help="Send requests through the resilient HTTP client.", no_args_is_help=True)
app.add_typer(http_commands, name="http")
llm_commands = typer.Typer(help="Ask a language model.", no_args_is_help=True)
app.add_typer(llm_commands, name="llm")
task_commands = typer.Typer(help="Run one task end to end.", no_args_is_help=True)
app.add_typer(task_commands, name="task")


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


@llm_commands.command("ask")
def llm_ask(
    question: str,
    model: Annotated[str | None, typer.Option(help="Which model to ask. Defaults to the configured one.")] = None,
    prompt: Annotated[str | None, typer.Option(help="Name of a prompt file to put in front of the question.")] = None,
) -> None:
    """Ask a model one question and print what it answers."""
    settings = Settings()
    run_id = start_run(settings)
    try:
        answer = asyncio.run(_ask(settings, question, model, prompt, run_id))
    except PigletError as failure:
        typer.echo(f"error: {failure}", err=True)
        typer.echo(f"run_id: {run_id}", err=True)
        raise typer.Exit(code=1) from failure

    cost = f"${answer.usage.cost_usd:.6f}" if answer.usage.cost_usd is not None else "unknown"
    typer.echo(f"run_id: {run_id}")
    typer.echo(f"model: {answer.model}")
    typer.echo(f"finish_reason: {answer.finish_reason}")
    typer.echo(f"tokens: {answer.usage.prompt_tokens} in, {answer.usage.completion_tokens} out")
    typer.echo(f"cost: {cost}")
    typer.echo(answer.content)


@task_commands.command("run")
def task_run(name: str) -> None:
    """Run one task by name and print what the platform answered."""
    try:
        outcome = asyncio.run(run_task(name, Settings()))
    except (PigletError, ValueError) as failure:
        typer.echo(f"error: {failure}", err=True)
        raise typer.Exit(code=1) from failure

    typer.echo(f"run_id: {outcome.run_id}")
    typer.echo(f"submitted: {outcome.submitted}")
    typer.echo(outcome.reply)


async def _ask(settings: Settings, question: str, model: str | None, prompt: str | None, run_id: str) -> ChatCompletion:
    """Ask one question of a model built for this run.

    Args:
        settings: Credentials, the provider's address, the timeouts and where prompts live.
        question: What to ask.
        model: Which model to ask, or None to take the configured one.
        prompt: Name of a prompt to send as the system message, or None to send none.
        run_id: Identity of this run, under which the exchange is written down.

    Returns:
        The answer, with what it cost.
    """
    messages = [ChatMessage(Role.USER, question)]
    instruction = MarkdownPromptLibrary(settings.prompts_dir).load(prompt) if prompt is not None else None
    if instruction is not None:
        messages.insert(0, ChatMessage(Role.SYSTEM, instruction.text))

    async with build_llm_http_client(settings) as http_client:
        chat_model = build_chat_model(settings, http_client, run_id)
        request = ChatRequest(messages, model=model, prompt_name=instruction.name if instruction else None)
        return await chat_model.complete(request)


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
