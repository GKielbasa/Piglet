import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.adapters.llm.openrouter_chat import OpenRouterChatModel
from piglet.adapters.logging.setup import configure_logging
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.http.retry_policy import RetryPolicy
from piglet.domain.http.service_profile import ServiceProfile
from piglet.domain.llm.chat import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    ResponseSchema,
    Role,
    ToolCall,
    ToolDefinition,
)
from piglet.errors import HTTPError, ModelAnswerTruncatedError, ModelCallFailedError, RetryExhaustedError

API_KEY = SecretStr("a-key-nobody-owns")
MODEL = "openai/gpt-4.1-mini"
ANSWERING_MODEL = "openai/gpt-4.1-mini:floor"
BASE_URL = "https://models.example/api/v1"
ENDPOINT = "https://models.example/api/v1/chat/completions"

QUESTION = ChatRequest([ChatMessage(Role.USER, "How many moons does Mars have?")])
SCHEMA = ResponseSchema("moon_count", {"type": "object", "properties": {"count": {"type": "integer"}}})
QUICK_RETRIES = RetryPolicy(max_attempts=3, transient_base_delay_seconds=0.0, jitter_fraction=lambda: 0.0)


class ScriptedTransport:
    """Answers from a script, remembers what it was asked, never touches a network."""

    def __init__(self, *answers: HTTPResponse) -> None:
        self.scripted = list(answers)
        self.requests: list[HTTPRequest] = []

    async def send(self, request: HTTPRequest) -> HTTPResponse:
        self.requests.append(request)
        # The last scripted answer repeats, so "always 503" needs one entry.
        return self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]

    async def aclose(self) -> None:
        return None


async def no_waiting(seconds: float, /) -> None:
    return None


def build_model(*answers: HTTPResponse) -> tuple[ScriptedTransport, OpenRouterChatModel]:
    transport = ScriptedTransport(*answers)
    client = ResilientHTTPClient(transport, QUICK_RETRIES, ServiceProfile(), no_waiting)
    return transport, OpenRouterChatModel(client, API_KEY, MODEL, BASE_URL)


def answered(**overrides: object) -> HTTPResponse:
    """A successful completion, with whichever fields a test needs replaced."""
    payload: dict[str, Any] = {
        "model": ANSWERING_MODEL,
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Two."}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 2, "cost": 0.000042},
    }
    payload.update(overrides)
    return HTTPResponse(200, body=json.dumps(payload).encode())


def body_of(transport: ScriptedTransport) -> dict[str, Any]:
    """The JSON body of the first request the transport was handed."""
    return cast("dict[str, Any]", json.loads(transport.requests[0].body or b""))


def llm_entries(log_dir: Path) -> list[dict[str, Any]]:
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    return [entry for entry in entries if entry["event"] == "llm_call_finished"]


async def test_the_call_is_a_post_to_the_chat_completions_endpoint() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert transport.requests[0].method is HTTPMethod.POST
    assert transport.requests[0].url == ENDPOINT


async def test_the_key_travels_as_a_bearer_token() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert transport.requests[0].headers["Authorization"] == "Bearer a-key-nobody-owns"


async def test_the_configured_model_is_used_when_the_request_names_none() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert body_of(transport)["model"] == MODEL


async def test_a_request_naming_a_model_wins_over_configuration() -> None:
    transport, model = build_model(answered())

    await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], model="anthropic/claude-haiku-4.5"))

    assert body_of(transport)["model"] == "anthropic/claude-haiku-4.5"


async def test_messages_keep_their_order_and_roles() -> None:
    transport, model = build_model(answered())
    conversation = [ChatMessage(Role.SYSTEM, "Answer briefly."), ChatMessage(Role.USER, "How many moons?")]

    await model.complete(ChatRequest(conversation))

    assert body_of(transport)["messages"] == [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": "How many moons?"},
    ]


async def test_a_schema_is_sent_as_json_schema_in_strict_mode() -> None:
    transport, model = build_model(answered())

    await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], response_schema=SCHEMA))

    assert body_of(transport)["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "moon_count", "strict": True, "schema": dict(SCHEMA.json_schema)},
    }


async def test_a_schema_demands_a_provider_that_supports_it() -> None:
    transport, model = build_model(answered())

    await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], response_schema=SCHEMA))

    assert body_of(transport)["provider"] == {"require_parameters": True}


async def test_without_a_schema_neither_field_is_sent() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert "response_format" not in body_of(transport)
    assert "provider" not in body_of(transport)


async def test_generation_parameters_appear_only_when_set() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert "temperature" not in body_of(transport)
    assert "max_tokens" not in body_of(transport)


async def test_the_body_carries_nothing_else() -> None:
    transport, model = build_model(answered())
    request = ChatRequest(
        [ChatMessage(Role.USER, "Hi.")], response_schema=SCHEMA, temperature=0.0, max_output_tokens=64
    )

    await model.complete(request)

    assert set(body_of(transport)) == {"model", "messages", "response_format", "provider", "temperature", "max_tokens"}


async def test_nothing_identifies_us_to_the_leaderboard() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert set(transport.requests[0].headers) == {"Content-Type", "Authorization"}


async def test_the_prompt_name_never_reaches_the_wire() -> None:
    transport, model = build_model(answered())

    await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], prompt_name="record-classification"))

    assert set(body_of(transport)) == {"model", "messages"}


async def test_the_answer_carries_the_model_that_actually_produced_it() -> None:
    _, model = build_model(answered())

    completion = await model.complete(QUESTION)

    assert completion.content == "Two."
    assert completion.model == ANSWERING_MODEL
    assert completion.finish_reason is FinishReason.STOP


async def test_token_counts_and_cost_are_carried_over() -> None:
    _, model = build_model(answered())

    usage = (await model.complete(QUESTION)).usage

    assert (usage.prompt_tokens, usage.completion_tokens, usage.cost_usd) == (11, 2, 0.000042)


async def test_a_missing_cost_stays_unknown() -> None:
    _, model = build_model(answered(usage={"prompt_tokens": 11, "completion_tokens": 2}))

    assert (await model.complete(QUESTION)).usage.cost_usd is None


async def test_an_unknown_finish_reason_becomes_other() -> None:
    _, model = build_model(answered(choices=[{"finish_reason": "cable_chewed_through", "message": {"content": "…"}}]))

    assert (await model.complete(QUESTION)).finish_reason is FinishReason.OTHER


async def test_an_answer_cut_off_at_the_ceiling_raises() -> None:
    _, model = build_model(answered(choices=[{"finish_reason": "length", "message": {"content": "Tw"}}]))

    with pytest.raises(ModelAnswerTruncatedError) as raised:
        await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], max_output_tokens=64))

    assert raised.value.max_output_tokens == 64
    assert raised.value.usage.completion_tokens == 2


async def test_an_error_inside_a_successful_response_raises() -> None:
    failure = json.dumps({"error": {"code": 502, "message": "upstream provider died"}}).encode()
    _, model = build_model(HTTPResponse(200, body=failure))

    with pytest.raises(ModelCallFailedError) as raised:
        await model.complete(QUESTION)

    assert raised.value.code == 502
    assert raised.value.provider_message == "upstream provider died"


async def test_an_answer_without_exactly_one_choice_raises() -> None:
    _, model = build_model(answered(choices=[]))

    with pytest.raises(ModelCallFailedError, match="exactly one choice"):
        await model.complete(QUESTION)


async def test_a_transient_failure_is_retried_although_the_verb_is_post() -> None:
    transport, model = build_model(HTTPResponse(502), answered())

    completion = await model.complete(QUESTION)

    assert completion.content == "Two."
    assert len(transport.requests) == 2


async def test_a_permanent_status_stays_an_http_error() -> None:
    _, model = build_model(HTTPResponse(401))

    with pytest.raises(HTTPError):
        await model.complete(QUESTION)


async def test_a_schema_no_provider_supports_is_reported_as_a_model_failure() -> None:
    _, model = build_model(HTTPResponse(503))

    with pytest.raises(ModelCallFailedError, match="moon_count"):
        await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], response_schema=SCHEMA))


async def test_without_a_schema_the_same_failure_stays_what_it_was() -> None:
    _, model = build_model(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError):
        await model.complete(QUESTION)


async def test_a_finished_call_leaves_one_entry(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    _, model = build_model(answered())

    await model.complete(ChatRequest([ChatMessage(Role.USER, "Hi.")], prompt_name="record-classification"))

    entry = llm_entries(tmp_path)[0]
    assert entry["outcome"] == "ok"
    assert entry["model"] == MODEL
    assert entry["model_answered"] == ANSWERING_MODEL
    assert entry["finish_reason"] == "stop"
    assert entry["prompt_tokens"] == 11
    assert entry["completion_tokens"] == 2
    assert entry["cost_usd"] == 0.000042
    assert entry["prompt_name"] == "record-classification"


async def test_a_call_the_provider_refused_leaves_one_too(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    failure = json.dumps({"error": {"code": 502, "message": "upstream provider died"}}).encode()
    _, model = build_model(HTTPResponse(200, body=failure))

    with pytest.raises(ModelCallFailedError):
        await model.complete(QUESTION)

    entry = llm_entries(tmp_path)[0]
    assert entry["outcome"] == "provider_error"
    assert "prompt_tokens" not in entry


async def test_a_call_the_http_layer_gave_up_on_leaves_one_too(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    _, model = build_model(HTTPResponse(503))

    with pytest.raises(RetryExhaustedError):
        await model.complete(QUESTION)

    assert llm_entries(tmp_path)[0]["outcome"] == "http_failure"


LOCATE_TOWN = ToolDefinition(
    "locate_town",
    "Where a town is, in degrees.",
    {"type": "object", "properties": {"town": {"type": "string"}}, "required": ["town"]},
)
ASKED_WITH_TOOLS = ChatRequest([ChatMessage(Role.USER, "Where is Zabrze?")], tools=[LOCATE_TOWN])
USED_A_TOOL = ChatRequest(
    [
        ChatMessage(Role.USER, "Where is Zabrze?"),
        ChatMessage(Role.ASSISTANT, tool_calls=[ToolCall("call_1", "locate_town", '{"town": "Zabrze"}')]),
        ChatMessage(Role.TOOL, "50.3143, 18.7816", tool_call_id="call_1"),
    ]
)


def called(arguments: str = '{"town": "Zabrze"}') -> HTTPResponse:
    """A completion in which the model reached for a tool instead of answering."""
    return answered(
        choices=[
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "locate_town", "arguments": arguments},
                        }
                    ],
                },
            }
        ]
    )


async def test_a_request_with_no_tools_sends_no_tools_field() -> None:
    transport, model = build_model(answered())

    await model.complete(QUESTION)

    assert "tools" not in body_of(transport)


async def test_a_tool_definition_is_sent_in_the_shape_the_endpoint_documents() -> None:
    transport, model = build_model(called())

    await model.complete(ASKED_WITH_TOOLS)

    assert body_of(transport)["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "locate_town",
                "description": "Where a town is, in degrees.",
                "strict": True,
                "parameters": {"type": "object", "properties": {"town": {"type": "string"}}, "required": ["town"]},
            },
        }
    ]


async def test_a_request_carrying_tools_asks_for_a_provider_that_supports_them() -> None:
    transport, model = build_model(called())

    await model.complete(ASKED_WITH_TOOLS)

    assert body_of(transport)["provider"] == {"require_parameters": True}


async def test_an_assistant_turn_that_called_tools_is_sent_back_with_those_calls() -> None:
    transport, model = build_model(answered())

    await model.complete(USED_A_TOOL)

    assert body_of(transport)["messages"][1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "locate_town", "arguments": '{"town": "Zabrze"}'},
            }
        ],
    }


async def test_a_tool_result_is_sent_as_its_own_message_naming_the_call() -> None:
    transport, model = build_model(answered())

    await model.complete(USED_A_TOOL)

    assert body_of(transport)["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "50.3143, 18.7816",
    }


async def test_an_answer_that_calls_a_tool_is_read_as_a_tool_call_not_as_a_failure() -> None:
    _, model = build_model(called())

    answer = await model.complete(ASKED_WITH_TOOLS)

    assert answer.content == ""
    assert [(call.call_id, call.name) for call in answer.tool_calls] == [("call_1", "locate_town")]


async def test_the_finish_reason_tool_calls_is_understood() -> None:
    _, model = build_model(called())

    assert (await model.complete(ASKED_WITH_TOOLS)).finish_reason is FinishReason.TOOL_CALLS


async def test_an_answer_with_neither_text_nor_tool_calls_is_still_a_failure() -> None:
    _, model = build_model(answered(choices=[{"finish_reason": "stop", "message": {"content": None}}]))

    with pytest.raises(ModelCallFailedError, match="no text at all"):
        await model.complete(QUESTION)


async def test_a_refusal_is_still_a_refusal() -> None:
    refused = {"finish_reason": "stop", "message": {"content": None, "refusal": "I will not."}}
    _, model = build_model(answered(choices=[refused]))

    with pytest.raises(ModelCallFailedError, match=r"declined to answer: I will not\."):
        await model.complete(QUESTION)


async def test_the_argument_text_is_handed_on_exactly_as_it_arrived() -> None:
    ragged = '{"town":   "Żarnowiec"  ,\n  "hint": "the one with the reactor"}'
    _, model = build_model(called(arguments=ragged))

    assert (await model.complete(ASKED_WITH_TOOLS)).tool_calls[0].arguments == ragged
