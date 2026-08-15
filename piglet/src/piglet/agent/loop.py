"""Ask, run what was asked for, say what happened, ask again — until something stops it."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import structlog
from structlog.typing import FilteringBoundLogger

from piglet.domain.llm.chat import ChatMessage, ChatRequest, Role
from piglet.domain.ports import ChatModel
from piglet.errors import InvalidRequestError
from piglet.tools.registry import ToolRegistry

__all__ = ["AgentRun", "StopReason", "run_agent"]

DEFAULT_MAX_STEPS = 12


class StopReason(StrEnum):
    """Why the loop stopped turning."""

    ANSWERED = "answered"
    FINISHED_BY_TOOL = "finished_by_tool"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class AgentRun:
    """What one run of the loop produced.

    The conversation is kept rather than discarded, and it is the reason a run that hit its
    budget comes back as a value instead of an exception: a run that went in circles is the one
    most worth reading, and an exception would throw away the evidence of what it circled.

    Attributes:
        final_text: The last thing the model said in prose. Empty when a tool finished the
            work, or when the budget ran out mid-turn.
        conversation: Every turn, in order, the tool results included.
        steps_taken: How many times the model was asked.
        stop_reason: What ended it.
    """

    final_text: str
    conversation: Sequence[ChatMessage]
    steps_taken: int
    stop_reason: StopReason


async def run_agent(
    chat_model: ChatModel,
    registry: ToolRegistry,
    request: ChatRequest,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> AgentRun:
    """Let a model work until it is done, it is finished for it, or it runs out of steps.

    A step is one call to the model, whatever number of tools that turn asks for. That is what
    the budget is protecting: turns are what cost money and turns are what go round in circles,
    while the tools inside one are already bounded by it.

    Args:
        chat_model: Who to ask. Asked afresh every step, carrying the whole conversation,
            because the provider remembers nothing between calls.
        registry: What the model may reach for, and the only thing that runs it.
        request: The opening conversation, and the settings every turn reuses — the model, the
            temperature, the prompt's name for the log. Whatever tools it carries are replaced
            by the registry's.
        max_steps: How many times the model may be asked.

    Returns:
        What the run produced, including why it stopped. Running out of steps is one of the
        three ways to stop and not an error.

    Raises:
        InvalidRequestError: If `max_steps` leaves no room for a single call.
        PigletError: Whatever the model or a tool raised and did not turn into an answer.

    Example:
        >>> finished = await run_agent(chat_model, registry, ChatRequest(messages), max_steps=15)
        >>> finished.stop_reason
        <StopReason.FINISHED_BY_TOOL: 'finished_by_tool'>
    """
    if max_steps < 1:
        raise InvalidRequestError(f"an agent needs at least one step, got {max_steps}")

    logger = structlog.get_logger()
    definitions = registry.definitions
    conversation = list(request.messages)
    tools_run = 0

    for steps_taken in range(1, max_steps + 1):
        answer = await chat_model.complete(replace(request, messages=list(conversation), tools=definitions))
        if not answer.tool_calls:
            conversation.append(ChatMessage(Role.ASSISTANT, answer.content))
            return _stopped(logger, answer.content, conversation, steps_taken, StopReason.ANSWERED, tools_run)

        conversation.append(ChatMessage(Role.ASSISTANT, answer.content, tool_calls=answer.tool_calls))
        for call in answer.tool_calls:
            result = await registry.execute(call)
            tools_run += 1
            conversation.append(ChatMessage(Role.TOOL, result.content, tool_call_id=call.call_id))
            if result.ends_the_run:
                # Whatever the model queued behind this one it asked for before knowing the work
                # was over, so running the rest would spend requests on answers nobody reads.
                reason = StopReason.FINISHED_BY_TOOL
                return _stopped(logger, answer.content, conversation, steps_taken, reason, tools_run)

    return _stopped(logger, "", conversation, max_steps, StopReason.BUDGET_EXHAUSTED, tools_run)


def _stopped(
    logger: FilteringBoundLogger,
    final_text: str,
    conversation: Sequence[ChatMessage],
    steps_taken: int,
    stop_reason: StopReason,
    tools_run: int,
) -> AgentRun:
    """Record how the run ended and hand it back.

    Args:
        logger: Where the entry goes.
        final_text: The last prose the model produced.
        conversation: Every turn, in order.
        steps_taken: How many times the model was asked.
        stop_reason: What ended it.
        tools_run: How many tool executions happened altogether.

    Returns:
        The finished run.
    """
    logger.info("agent_run_finished", steps_taken=steps_taken, stop_reason=stop_reason, tool_calls=tools_run)
    return AgentRun(final_text, tuple(conversation), steps_taken, stop_reason)
