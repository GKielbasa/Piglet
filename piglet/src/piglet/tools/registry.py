"""What a model may reach for, and what it is told when reaching goes wrong."""

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import cast

import structlog
from pydantic import BaseModel, ValidationError
from structlog.typing import FilteringBoundLogger

from piglet.domain.llm.chat import ToolCall, ToolDefinition
from piglet.errors import InvalidRequestError, PigletError, ToolFailedError
from piglet.llm.json_schema import to_strict_json_schema

__all__ = ["Tool", "ToolRegistry", "ToolResult", "define_tool"]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What running a tool produced.

    Only `content` reaches the model — the provider's API carries a string and nothing else.
    The other two are for the caller: an agent loop needs to know whether to keep going, and a
    log that cannot tell a refusal from an answer cannot say afterwards how often the tools
    were the thing that failed.

    Attributes:
        content: What the model will read.
        is_error: Whether the tool refused rather than answered.
        ends_the_run: Whether this was the tool that finishes the work.
    """

    content: str
    is_error: bool = False
    ends_the_run: bool = False


@dataclass(frozen=True, slots=True)
class Tool:
    """One capability, with the code behind it.

    Built through `define_tool` rather than directly, which is what keeps `run` honest: the
    registry validates arguments against `arguments` before calling it, and the factory is
    where the two are tied together.

    Attributes:
        name: What the model asks for.
        description: When to reach for this, read by the model as part of its instruction.
        arguments: The shape of the arguments, as a pydantic model.
        run: What to do about it, given already-validated arguments.
        ends_the_run: Whether a successful call means there is nothing left to do.
    """

    name: str
    description: str
    arguments: type[BaseModel]
    run: Callable[[BaseModel], Awaitable[str]]
    ends_the_run: bool = False


def define_tool[A: BaseModel](
    name: str,
    description: str,
    arguments: type[A],
    run: Callable[[A], Awaitable[str]],
    ends_the_run: bool = False,
) -> Tool:
    """Declare one tool, keeping its argument type at the call site.

    A registry holds tools whose argument models all differ, and no type checker can express a
    list of those. So the type is erased exactly here, once, instead of every caller writing
    `BaseModel` and losing it — a tool's own body stays fully typed.

    Args:
        name: What the model asks for. Worth making unlikely to collide with anything else on
            offer, because it is the model that resolves a collision.
        description: When to reach for this.
        arguments: The shape of the arguments.
        run: What to do, given arguments already validated into `arguments`.
        ends_the_run: Whether a successful call means the work is finished.

    Returns:
        The tool, ready to be registered.

    Example:
        >>> define_tool("locate_town", "Where a town is.", TownName, locate)
    """
    # Sound because `ToolRegistry.execute` parses with the very `arguments` model above, so
    # whatever reaches `run` is an instance of what it declared.
    widened = cast("Callable[[BaseModel], Awaitable[str]]", run)
    return Tool(name, description, arguments, widened, ends_the_run)


class ToolRegistry:
    """Everything a model may reach for, and the only thing that runs it.

    Nothing here raises on the model's behalf. A model works from text alone, so a mistake it
    can correct has to reach it as text: naming a tool that does not exist, filling a field
    wrongly, asking for something the world refuses. Each comes back as a result it can act on.

    What does not come back that way is a failure the model cannot do anything about. The
    registry cannot tell those apart — a tool can, which is why the only failure it converts is
    the one a tool raised deliberately.

    Attributes:
        tools: What is on offer, in the order it was given. No two of them share a name.
        logger: Where each execution is recorded.

    Example:
        >>> registry = ToolRegistry([define_tool("locate_town", "Where a town is.", TownName, locate)])
        >>> answer = await model.complete(ChatRequest(messages, tools=registry.definitions))
    """

    def __init__(self, tools: Sequence[Tool], logger: FilteringBoundLogger | None = None) -> None:
        self.tools = tuple(tools)
        self.logger = logger or structlog.get_logger()
        self._by_name = _index_by_name(self.tools)

    @property
    def definitions(self) -> list[ToolDefinition]:
        """What the model is told it may reach for.

        In the order the tools were registered. That order is part of the instruction the model
        reads, so it may not come from whatever a dictionary happens to hold.

        Returns:
            One definition per tool, argument schemas in the dialect a provider enforces.
        """
        return [
            ToolDefinition(tool.name, tool.description, to_strict_json_schema(tool.arguments).json_schema)
            for tool in self.tools
        ]

    async def execute(self, call: ToolCall) -> ToolResult:
        """Run what the model asked for, and say what came of it.

        Args:
            call: What the model asked for, arguments still as it wrote them.

        Returns:
            The result, whether the tool answered or refused.

        Raises:
            PigletError: Whatever the tool raised that was not a `ToolFailedError`. Such a
                failure is not the model's to solve, and handing it over as text buys several
                turns of guessing at the caller's expense.
        """
        started = time.perf_counter()
        try:
            result = await self._run(call)
        except PigletError:
            # The call that ends the run is the one the log is read for, and the only one that
            # would otherwise leave no trace of having happened.
            self._record(call, started, is_error=True)
            raise
        self._record(call, started, is_error=result.is_error)
        return result

    def _record(self, call: ToolCall, started: float, is_error: bool) -> None:
        """Write down that one call happened, and how it went.

        The arguments are deliberately absent: they carry whatever the task is about, and the
        log's redactor knows none of it. Whole exchanges are recorded elsewhere, and that
        recording can be switched off.

        Args:
            call: What the model asked for.
            started: When the attempt began, from `time.perf_counter`.
            is_error: Whether the tool refused, or failed in a way that travels on.
        """
        self.logger.info(
            "tool_call_finished",
            tool=call.name,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            is_error=is_error,
        )

    async def _run(self, call: ToolCall) -> ToolResult:
        """Find the tool, read the arguments, and do it.

        Args:
            call: What the model asked for.

        Returns:
            The result, with every failure the model can act on already turned into one.
        """
        tool = self._by_name.get(call.name)
        if tool is None:
            on_offer = ", ".join(named.name for named in self.tools) or "none at all"
            return ToolResult(f"There is no tool called {call.name!r}. The tools you have are: {on_offer}.", True)
        try:
            arguments = tool.arguments.model_validate_json(call.arguments)
        except ValidationError as rejected:
            return ToolResult(_why_the_arguments_were_not_accepted(tool.name, rejected), True)
        try:
            answered = await tool.run(arguments)
        except ToolFailedError as refused:
            # A refusal ends nothing: the model is being told to try again, and a terminal tool
            # that stopped the run here would stop it with the work undone.
            return ToolResult(refused.advice, True)
        return ToolResult(answered, ends_the_run=tool.ends_the_run)


def _index_by_name(tools: Sequence[Tool]) -> dict[str, Tool]:
    """Key the tools by the name a model will ask for, refusing a name that is used twice.

    A dictionary built from a list keeps the last of two entries sharing a key, while both are
    still offered: the model reads two descriptions under one name and reaches whichever
    survived. Nothing downstream can see that, because by then there is only one tool left.

    Args:
        tools: What is on offer.

    Returns:
        The tools, by name.

    Raises:
        InvalidRequestError: If two tools are registered under one name.
    """
    by_name: dict[str, Tool] = {}
    for tool in tools:
        if tool.name in by_name:
            raise InvalidRequestError(
                f"two tools are registered as {tool.name!r}; a model has one name to reach each of them by"
            )
        by_name[tool.name] = tool
    return by_name


def _why_the_arguments_were_not_accepted(name: str, rejected: ValidationError) -> str:
    """Say what is wrong with the arguments, in terms the model can act on.

    A validation error reads as a stack of locations and codes. The model has no schema in
    front of it and no documentation, so what it needs is which field, what is wrong with it,
    and that trying again is the thing to do.

    Args:
        name: The tool whose arguments were refused.
        rejected: What pydantic made of them.

    Returns:
        One sentence per problem, then the next move.
    """
    problems = "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or 'the arguments as a whole'}: {problem['msg']}"
        for problem in rejected.errors()
    )
    return f"The arguments for {name!r} were not accepted — {problems}. Call it again with these corrected."
