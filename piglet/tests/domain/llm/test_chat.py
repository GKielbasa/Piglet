import pytest

from piglet.domain.llm.chat import (
    ChatCompletion,
    ChatMessage,
    ChatRequest,
    FinishReason,
    Role,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from piglet.errors import InvalidRequestError

TOWN_SCHEMA = {"type": "object", "properties": {"town": {"type": "string"}}, "required": ["town"]}


def test_a_request_without_messages_is_refused() -> None:
    with pytest.raises(InvalidRequestError, match="at least one message"):
        ChatRequest([])


def test_a_request_with_one_message_is_allowed() -> None:
    assert ChatRequest([ChatMessage(Role.USER, "How many moons does Mars have?")]).messages


def test_a_tool_definition_keeps_its_name_description_and_schema() -> None:
    tool = ToolDefinition("locate_town", "Where a town is, in degrees.", TOWN_SCHEMA)

    assert (tool.name, tool.description, tool.parameters) == (
        "locate_town",
        "Where a town is, in degrees.",
        TOWN_SCHEMA,
    )


def test_a_tool_call_keeps_its_id_the_name_it_names_and_its_raw_arguments() -> None:
    call = ToolCall("call_1", "locate_town", '{"town": "Zabrze"}')

    assert (call.call_id, call.name, call.arguments) == ("call_1", "locate_town", '{"town": "Zabrze"}')


def test_a_message_carrying_tool_calls_needs_no_content() -> None:
    turn = ChatMessage(Role.ASSISTANT, tool_calls=[ToolCall("call_1", "locate_town", "{}")])

    assert turn.content == ""
    assert [call.name for call in turn.tool_calls] == ["locate_town"]


def test_a_tool_result_must_name_the_call_it_answers() -> None:
    with pytest.raises(InvalidRequestError, match="must name the call"):
        ChatMessage(Role.TOOL, "50.3143, 18.7816")


def test_a_message_that_is_not_a_tool_result_may_not_name_a_call() -> None:
    with pytest.raises(InvalidRequestError, match="answers no call"):
        ChatMessage(Role.USER, "Where is Zabrze?", tool_call_id="call_1")


def test_a_request_carries_no_tools_unless_it_is_given_some() -> None:
    assert ChatRequest([ChatMessage(Role.USER, "How many moons does Mars have?")]).tools == ()


def test_an_answer_carries_no_tool_calls_unless_the_model_made_some() -> None:
    assert ChatCompletion("Two.", "test/model", FinishReason.STOP, TokenUsage(11, 2)).tool_calls == ()
