import json

import pytest
from pydantic import BaseModel

from piglet.domain.llm.chat import ChatCompletion, ChatMessage, ChatRequest, FinishReason, Role, TokenUsage
from piglet.errors import SchemaViolationError
from piglet.llm.structured import complete_as


class Verdict(BaseModel):
    """One judgement about a record."""

    reasoning: str
    tag: str


class ScriptedModel:
    """Answers with whatever it was handed, and remembers what it was asked."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        self.requests.append(request)
        return ChatCompletion(self.answer, "test/model", FinishReason.STOP, TokenUsage(0, 0))


QUESTION = ChatRequest([ChatMessage(Role.USER, "a bus driver")])
WELL_SHAPED = json.dumps({"reasoning": "drives a bus for a living", "tag": "transport"})


async def test_the_answer_comes_back_in_the_shape_that_was_asked_for() -> None:
    model = ScriptedModel(WELL_SHAPED)

    verdict = await complete_as(model, QUESTION, Verdict)

    assert verdict.tag == "transport"
    assert verdict.reasoning == "drives a bus for a living"


async def test_the_schema_travels_with_the_request() -> None:
    model = ScriptedModel(WELL_SHAPED)

    await complete_as(model, QUESTION, Verdict)

    schema = model.requests[0].response_schema
    assert schema is not None
    assert schema.name == "Verdict"
    assert schema.json_schema["additionalProperties"] is False


async def test_the_rest_of_the_request_survives() -> None:
    model = ScriptedModel(WELL_SHAPED)
    request = ChatRequest([ChatMessage(Role.USER, "a bus driver")], model="x/y", temperature=0.0, prompt_name="p")

    await complete_as(model, request, Verdict)

    asked = model.requests[0]
    assert (asked.model, asked.temperature, asked.prompt_name) == ("x/y", 0.0, "p")


async def test_an_answer_of_another_shape_is_refused() -> None:
    model = ScriptedModel(json.dumps({"tag": "transport"}))

    with pytest.raises(SchemaViolationError) as raised:
        await complete_as(model, QUESTION, Verdict)

    assert raised.value.schema_name == "Verdict"
    assert raised.value.answer_preview == '{"tag": "transport"}'


async def test_an_answer_that_is_not_json_at_all_is_refused() -> None:
    model = ScriptedModel("I think this person drives a bus.")

    with pytest.raises(SchemaViolationError):
        await complete_as(model, QUESTION, Verdict)
