import pytest

from piglet.domain.llm.chat import ChatMessage, ChatRequest, Role
from piglet.errors import InvalidRequestError


def test_a_request_without_messages_is_refused() -> None:
    with pytest.raises(InvalidRequestError, match="at least one message"):
        ChatRequest([])


def test_a_request_with_one_message_is_allowed() -> None:
    assert ChatRequest([ChatMessage(Role.USER, "How many moons does Mars have?")]).messages
