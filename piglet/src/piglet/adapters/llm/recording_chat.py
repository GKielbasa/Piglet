"""Every exchange with a model, written down where it can be read back."""

import json
from dataclasses import asdict
from itertools import count
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

from piglet.domain.llm.chat import ChatCompletion, ChatMessage, ChatRequest
from piglet.domain.ports import ChatModel
from piglet.errors import PigletError

__all__ = ["RecordingChatModel"]

_TOOL_FIELDS = frozenset({"tool_calls", "tool_call_id"})


class RecordingChatModel:
    """Asks another model, and writes the whole exchange to disk on the way back.

    A `ChatModel` wrapping a `ChatModel`: the caller cannot tell the difference and the
    provider underneath does not know it is being recorded. That is what the port is for — this
    works for any provider, including ones nobody has written yet.

    The JSONL log records what a call **cost**; this records what it **contained**. The
    difference decides what can be done later: token counts answer "how often did it fail and
    how much did it cost", and nothing else. Why a model chose one label over another, and
    whether a changed prompt improved anything, can only be answered against the exchange
    itself — which cannot be reconstructed after the fact, and is why the writing starts with
    the first run rather than with the season that needs it.

    Attributes:
        inner: Who actually answers.
        directory: Where the files go. One file per call, numbered in the order they were made.
        logger: Where the reference to each written file is recorded.

    Example:
        >>> model = RecordingChatModel(OpenRouterChatModel(...), settings.runs_dir / run_id)
    """

    def __init__(self, inner: ChatModel, directory: Path, logger: FilteringBoundLogger | None = None) -> None:
        self.inner = inner
        self.directory = directory
        self.logger = logger or structlog.get_logger()
        self._sequence = count(1)

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        """Ask the model underneath, and write down what was said either way.

        Args:
            request: What to ask.

        Returns:
            Exactly what the model underneath returned.

        Raises:
            PigletError: Whatever the model underneath raised, unchanged and after the failed
                exchange has been written. A call that failed is the one most worth reading
                back, so it is not the one to skip.
        """
        try:
            answer = await self.inner.complete(request)
        except PigletError as failure:
            self._write(request, failure=failure)
            raise
        self._write(request, answer=answer)
        return answer

    def _write(
        self, request: ChatRequest, answer: ChatCompletion | None = None, failure: PigletError | None = None
    ) -> None:
        """Write one exchange as a JSON document, or record that it could not be written.

        A recorder observes; it may not change what it observes. A read-only directory or a
        full disk would otherwise leave this method raising `OSError` — replacing an answer
        that has already been paid for, or replacing the model's own failure with one about
        the recording of it, which no caller of a `ChatModel` expects to catch. So the write
        fails alone, at error level: not swallowed, and not passed on.

        Note that the log's redactor does not run here: a secret placed in a prompt would be
        written as it stands. Prompts are ours to write, so the rule is the one from section 11
        — a secret never goes into a prompt in the first place.

        Args:
            request: What was asked.
            answer: What came back, or None when nothing did.
            failure: What went wrong, or None when nothing did.
        """
        path = self.directory / f"{next(self._sequence):04d}.json"
        document: dict[str, Any] = {
            "prompt_name": request.prompt_name,
            "model": request.model,
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "messages": [_describe_message(message) for message in request.messages],
            "tools": _describe_tools(request),
            "response_schema": _describe_schema(request),
            "answer": _describe_answer(answer),
            "failure": None if failure is None else {"type": type(failure).__name__, "message": str(failure)},
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as unwritable:
            self.logger.error("llm_exchange_not_recorded", path=str(path), reason=str(unwritable))
            return
        self.logger.info("llm_exchange_recorded", path=str(path), prompt_name=request.prompt_name)


def _describe_message(message: ChatMessage) -> dict[str, Any]:
    """Describe one turn of the conversation that was sent.

    Args:
        message: The turn to describe.

    Returns:
        The turn, its tool calls flattened with it.
    """
    return _without_the_empty_tool_fields(asdict(message))


def _describe_tools(request: ChatRequest) -> list[dict[str, Any]] | None:
    """Describe what the model was allowed to reach for.

    Recorded in full rather than by name. A description is read by the model as part of the
    instruction, so an answer cannot be judged later against a definition nobody wrote down.

    Args:
        request: What was asked.

    Returns:
        One entry per tool, or None when the call offered none.
    """
    if not request.tools:
        return None
    return [asdict(tool) for tool in request.tools]


def _without_the_empty_tool_fields(described: dict[str, Any]) -> dict[str, Any]:
    """Drop the tool fields of anything that used no tools.

    Args:
        described: One value as `asdict` rendered it.

    Returns:
        The same, minus the tool fields that carry nothing — so a conversation that used no
        tools is recorded exactly as it was before this library could offer any.
    """
    return {name: value for name, value in described.items() if name not in _TOOL_FIELDS or value}


def _describe_schema(request: ChatRequest) -> dict[str, Any] | None:
    """Describe the shape the answer was required to take.

    Args:
        request: What was asked.

    Returns:
        The schema's name and body, or None when the call asked for free text.
    """
    if request.response_schema is None:
        return None
    return {"name": request.response_schema.name, "schema": dict(request.response_schema.json_schema)}


def _describe_answer(answer: ChatCompletion | None) -> dict[str, Any] | None:
    """Describe what the model said.

    Args:
        answer: What came back, or None when nothing did.

    Returns:
        The answer with what it cost, or None when the call failed. `tool_calls` is absent
        unless the model made some, for the reason given on `_describe_message`.
    """
    if answer is None:
        return None
    return _without_the_empty_tool_fields(asdict(answer))
