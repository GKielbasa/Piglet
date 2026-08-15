import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from piglet.adapters.llm.recording_chat import RecordingChatModel
from piglet.adapters.logging.setup import configure_logging
from piglet.domain.llm.chat import (
    ChatCompletion,
    ChatMessage,
    ChatRequest,
    FinishReason,
    ResponseSchema,
    Role,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from piglet.errors import ModelCallFailedError, PigletError

ANSWER = ChatCompletion("Two.", "test/model", FinishReason.STOP, TokenUsage(11, 2, 0.000042))
QUESTION = ChatRequest([ChatMessage(Role.USER, "How many moons does Mars have?")], prompt_name="moons")
SCHEMA = ResponseSchema("moon_count", {"type": "object", "properties": {"count": {"type": "integer"}}})


class ScriptedModel:
    """Answers with what it was handed, or raises it when it is a failure."""

    def __init__(self, *answers: ChatCompletion | PigletError) -> None:
        self.scripted = list(answers)
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        self.requests.append(request)
        answer = self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]
        if isinstance(answer, PigletError):
            raise answer
        return answer


def written(directory: Path) -> list[dict[str, Any]]:
    """Every exchange written to a directory, in the order the files are numbered."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.iterdir())]


def file_names(directory: Path) -> list[str]:
    """The names of the files written to a directory, sorted."""
    return sorted(path.name for path in directory.iterdir())


def unwritable_directory(tmp_path: Path) -> Path:
    """A path no directory can be created at, because a file sits where its parent would go."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    return blocked / "exchanges"


def read_entries(log_dir: Path) -> list[dict[str, Any]]:
    """Every entry written to the log, in order."""
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


async def test_a_finished_exchange_is_written_as_one_file(tmp_path: Path) -> None:
    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(QUESTION)

    assert file_names(tmp_path) == ["0001.json"]


async def test_files_are_numbered_in_the_order_the_calls_were_made(tmp_path: Path) -> None:
    model = RecordingChatModel(ScriptedModel(ANSWER), tmp_path)

    for _ in range(3):
        await model.complete(QUESTION)

    assert file_names(tmp_path) == ["0001.json", "0002.json", "0003.json"]


async def test_the_messages_are_written_with_their_roles(tmp_path: Path) -> None:
    conversation = ChatRequest([ChatMessage(Role.SYSTEM, "Answer briefly."), ChatMessage(Role.USER, "How many?")])

    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(conversation)

    assert written(tmp_path)[0]["messages"] == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "How many?"},
    ]


async def test_the_answer_is_written_with_what_it_cost(tmp_path: Path) -> None:
    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(QUESTION)

    exchange = written(tmp_path)[0]
    assert exchange["answer"]["content"] == "Two."
    assert exchange["answer"]["model"] == "test/model"
    assert exchange["answer"]["finish_reason"] == "stop"
    assert exchange["answer"]["usage"] == {"prompt_tokens": 11, "completion_tokens": 2, "cost_usd": 0.000042}
    assert exchange["prompt_name"] == "moons"


async def test_the_schema_is_written_when_one_was_asked_for(tmp_path: Path) -> None:
    asked = ChatRequest([ChatMessage(Role.USER, "How many?")], response_schema=SCHEMA)

    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(asked)

    assert written(tmp_path)[0]["response_schema"] == {"name": "moon_count", "schema": dict(SCHEMA.json_schema)}


async def test_a_call_without_a_schema_says_so(tmp_path: Path) -> None:
    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(QUESTION)

    assert written(tmp_path)[0]["response_schema"] is None


async def test_a_call_that_failed_is_written_too(tmp_path: Path) -> None:
    failure = ModelCallFailedError("test/model", "upstream provider died", 502)

    with pytest.raises(ModelCallFailedError):
        await RecordingChatModel(ScriptedModel(failure), tmp_path).complete(QUESTION)

    exchange = written(tmp_path)[0]
    assert exchange["answer"] is None
    assert exchange["failure"]["type"] == "ModelCallFailedError"
    assert "upstream provider died" in exchange["failure"]["message"]
    assert exchange["messages"][0]["content"] == "How many moons does Mars have?"


async def test_the_answer_comes_back_unchanged(tmp_path: Path) -> None:
    assert await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(QUESTION) == ANSWER


async def test_the_request_reaches_the_model_underneath_untouched(tmp_path: Path) -> None:
    inner = ScriptedModel(ANSWER)

    await RecordingChatModel(inner, tmp_path).complete(QUESTION)

    assert inner.requests == [QUESTION]


async def test_a_directory_that_cannot_be_written_does_not_replace_the_answer(tmp_path: Path) -> None:
    answer = await RecordingChatModel(ScriptedModel(ANSWER), unwritable_directory(tmp_path)).complete(QUESTION)

    assert answer == ANSWER


async def test_it_does_not_replace_the_failure_underneath_either(tmp_path: Path) -> None:
    failure = ModelCallFailedError("test/model", "upstream provider died", 502)

    with pytest.raises(ModelCallFailedError):
        await RecordingChatModel(ScriptedModel(failure), unwritable_directory(tmp_path)).complete(QUESTION)


async def test_an_exchange_that_could_not_be_written_says_so_in_the_log(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs")

    await RecordingChatModel(ScriptedModel(ANSWER), unwritable_directory(tmp_path)).complete(QUESTION)

    entries = read_entries(tmp_path / "logs")
    assert [entry["event"] for entry in entries] == ["llm_exchange_not_recorded"]
    assert entries[0]["level"] == "error"


LOCATE_TOWN = ToolDefinition("locate_town", "Where a town is.", {"type": "object", "properties": {}})
CALLED = ChatCompletion(
    "",
    "test/model",
    FinishReason.TOOL_CALLS,
    TokenUsage(11, 7),
    tool_calls=[ToolCall("call_1", "locate_town", '{"town": "Zabrze"}')],
)


async def test_the_tools_the_call_offered_are_written(tmp_path: Path) -> None:
    offered = ChatRequest([ChatMessage(Role.USER, "Where is Zabrze?")], tools=[LOCATE_TOWN])

    await RecordingChatModel(ScriptedModel(CALLED), tmp_path).complete(offered)

    assert written(tmp_path)[0]["tools"] == [
        {"name": "locate_town", "description": "Where a town is.", "parameters": {"type": "object", "properties": {}}}
    ]


async def test_a_call_offering_no_tools_writes_none(tmp_path: Path) -> None:
    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(QUESTION)

    assert written(tmp_path)[0]["tools"] is None


async def test_the_tool_calls_the_answer_made_are_written(tmp_path: Path) -> None:
    await RecordingChatModel(ScriptedModel(CALLED), tmp_path).complete(QUESTION)

    assert written(tmp_path)[0]["answer"]["tool_calls"] == [
        {"call_id": "call_1", "name": "locate_town", "arguments": '{"town": "Zabrze"}'}
    ]


async def test_a_recorded_conversation_keeps_the_calls_each_turn_made(tmp_path: Path) -> None:
    conversation = ChatRequest(
        [
            ChatMessage(Role.ASSISTANT, tool_calls=[ToolCall("call_1", "locate_town", "{}")]),
            ChatMessage(Role.TOOL, "50.3143, 18.7816", tool_call_id="call_1"),
        ]
    )

    await RecordingChatModel(ScriptedModel(ANSWER), tmp_path).complete(conversation)

    assert written(tmp_path)[0]["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"call_id": "call_1", "name": "locate_town", "arguments": "{}"}],
        },
        {"role": "tool", "content": "50.3143, 18.7816", "tool_call_id": "call_1"},
    ]
