import asyncio
import json
from enum import StrEnum

import pytest
from pydantic import BaseModel, Field

from piglet.domain.llm.chat import ChatCompletion, ChatRequest, FinishReason, Role, TokenUsage
from piglet.domain.llm.prompt import Prompt
from piglet.errors import ModelCallFailedError, SchemaViolationError
from piglet.llm.classification import classify_in_batches


class Tag(StrEnum):
    """The closed set every record is judged against."""

    TRANSPORT = "transport"
    TEACHING = "teaching"
    UNKNOWN = "unknown"


class Verdict(BaseModel):
    """One record judged: the reasoning first, then the labels it leads to."""

    reasoning: str = Field(description="Why these labels fit this record.")
    tags: list[Tag]


INSTRUCTION = Prompt("record-classification", "Assign labels.", "You classify records.")


def answer_for(verdicts: dict[int, str]) -> str:
    """One batch's answer: a tag per record number."""
    return json.dumps(
        {
            "verdicts": [
                {"number": number, "verdict": {"reasoning": "because", "tags": [tag]}}
                for number, tag in verdicts.items()
            ]
        }
    )


class ScriptedModel:
    """Answers each call from a script, and counts how many calls run at once."""

    def __init__(self, *answers: str | Exception) -> None:
        self.scripted = list(answers)
        self.requests: list[ChatRequest] = []
        self.in_flight = 0
        self.most_at_once = 0

    @property
    def asked(self) -> list[str]:
        """The last message of every call, which is the numbered batch."""
        return [request.messages[-1].content for request in self.requests]

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        self.requests.append(request)
        self.in_flight += 1
        self.most_at_once = max(self.most_at_once, self.in_flight)
        # Yields, so a batch that started later can be in flight beside this one.
        await asyncio.sleep(0)
        self.in_flight -= 1
        answer = self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]
        if isinstance(answer, Exception):
            raise answer
        return ChatCompletion(answer, "test/model", FinishReason.STOP, TokenUsage(0, 0))


async def test_every_record_gets_a_verdict_in_the_order_given() -> None:
    model = ScriptedModel(answer_for({1: "transport", 2: "teaching", 3: "unknown"}))

    verdicts = await classify_in_batches(model, ["driver", "teacher", "???"], Verdict, INSTRUCTION)

    assert [verdict.tags[0] for verdict in verdicts] == [Tag.TRANSPORT, Tag.TEACHING, Tag.UNKNOWN]


async def test_records_are_asked_about_in_batches_of_the_given_size() -> None:
    model = ScriptedModel(answer_for({1: "transport", 2: "transport"}))

    await classify_in_batches(model, ["a", "b", "c", "d"], Verdict, INSTRUCTION, batch_size=2)

    assert model.asked == ["1. a\n2. b", "1. c\n2. d"]


async def test_an_identical_record_is_asked_about_once() -> None:
    model = ScriptedModel(answer_for({1: "transport", 2: "teaching"}))

    verdicts = await classify_in_batches(model, ["driver", "teacher", "driver"], Verdict, INSTRUCTION)

    assert model.asked == ["1. driver\n2. teacher"]
    assert [verdict.tags[0] for verdict in verdicts] == [Tag.TRANSPORT, Tag.TEACHING, Tag.TRANSPORT]


async def test_no_more_batches_run_at_once_than_allowed() -> None:
    model = ScriptedModel(answer_for({1: "transport"}))
    records = [f"record {number}" for number in range(8)]

    await classify_in_batches(model, records, Verdict, INSTRUCTION, batch_size=1, max_concurrent_batches=2)

    assert len(model.asked) == 8
    assert model.most_at_once <= 2


async def test_no_records_means_no_call() -> None:
    model = ScriptedModel(answer_for({1: "transport"}))

    assert await classify_in_batches(model, [], Verdict, INSTRUCTION) == []
    assert model.requests == []


async def test_the_instruction_becomes_the_system_message() -> None:
    model = ScriptedModel(answer_for({1: "transport"}))

    await classify_in_batches(model, ["driver"], Verdict, INSTRUCTION)

    system = model.requests[0].messages[0]
    assert system.role is Role.SYSTEM
    assert system.content == "You classify records."
    assert model.requests[0].prompt_name == "record-classification"


async def test_a_missing_verdict_is_refused() -> None:
    model = ScriptedModel(answer_for({1: "transport"}))

    with pytest.raises(SchemaViolationError, match="no verdict for record"):
        await classify_in_batches(model, ["driver", "teacher"], Verdict, INSTRUCTION)


async def test_a_record_judged_twice_is_refused() -> None:
    twice = json.dumps(
        {
            "verdicts": [
                {"number": 1, "verdict": {"reasoning": "one", "tags": ["transport"]}},
                {"number": 1, "verdict": {"reasoning": "two", "tags": ["teaching"]}},
            ]
        }
    )
    model = ScriptedModel(twice)

    with pytest.raises(SchemaViolationError, match="judged twice"):
        await classify_in_batches(model, ["driver", "teacher"], Verdict, INSTRUCTION)


async def test_a_verdict_about_a_record_nobody_asked_about_is_refused() -> None:
    model = ScriptedModel(answer_for({1: "transport", 7: "teaching"}))

    with pytest.raises(SchemaViolationError, match="nobody asked about"):
        await classify_in_batches(model, ["driver", "teacher"], Verdict, INSTRUCTION)


async def test_a_failure_of_the_providers_own_gets_one_second_chance() -> None:
    model = ScriptedModel(ModelCallFailedError("test/model", "upstream died"), answer_for({1: "transport"}))

    verdicts = await classify_in_batches(model, ["driver"], Verdict, INSTRUCTION)

    assert verdicts[0].tags == [Tag.TRANSPORT]
    assert len(model.requests) == 2


async def test_a_second_failure_of_the_same_kind_gives_up() -> None:
    model = ScriptedModel(ModelCallFailedError("test/model", "upstream died"))

    with pytest.raises(ModelCallFailedError):
        await classify_in_batches(model, ["driver"], Verdict, INSTRUCTION)

    assert len(model.requests) == 2
