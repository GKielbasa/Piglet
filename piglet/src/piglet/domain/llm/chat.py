"""One exchange with a language model, as immutable values."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from piglet.errors import InvalidRequestError

__all__ = [
    "ChatCompletion",
    "ChatMessage",
    "ChatRequest",
    "FinishReason",
    "ResponseSchema",
    "Role",
    "TokenUsage",
]


class Role(StrEnum):
    """Who is speaking in one message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(StrEnum):
    """Why the model stopped generating.

    `OTHER` absorbs anything a provider names that this library does not know, so a new value
    on their side cannot break parsing on ours — the same rule the lesson gives for schemas we
    ask a model to fill, applied to the schema a model fills for us.
    """

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn in a conversation.

    Attributes:
        role: Who is speaking.
        content: What they said.

    Example:
        >>> ChatMessage(Role.USER, "How many moons does Mars have?").role
        <Role.USER: 'user'>
    """

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ResponseSchema:
    """The shape an answer must take, as JSON Schema.

    Built from a pydantic model by `piglet.llm.json_schema` and passed to the provider
    unchanged. The schema stays a mapping because JSON Schema is one; wrapping it in a value is
    what keeps a bare `dict[str, Any]` from crossing a module boundary.

    Attributes:
        name: What the provider should call this schema. Appears in its error messages, so it
            is worth naming after the thing being extracted rather than after the caller.
        json_schema: The schema itself, already in the dialect the provider expects.
    """

    name: str
    json_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """Everything one call to a model consists of.

    The API is stateless: every call carries the whole conversation, and a client holds no
    history of its own. Two identical requests are therefore the same question, whatever
    happened between them.

    Attributes:
        messages: The conversation, in order. Must not be empty.
        model: Which model to ask, or None to take the configured default.
        response_schema: The shape the answer must take, or None for free text.
        temperature: How much the model may wander. None leaves the provider's own default,
            which differs between models and is theirs to choose.
        max_output_tokens: Ceiling on the answer. None leaves the provider's own default.
        prompt_name: Which prompt this call came from. Metadata for the log only — it is never
            sent, and without it a log entry cannot say which instruction produced an answer.
    """

    messages: Sequence[ChatMessage]
    model: str | None = None
    response_schema: ResponseSchema | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    prompt_name: str | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise InvalidRequestError("a chat request must carry at least one message")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What one call consumed.

    Attributes:
        prompt_tokens: Tokens the request cost.
        completion_tokens: Tokens the answer cost.
        cost_usd: What the provider charged for it, or None when it did not say.
    """

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    """What the model answered.

    A value rather than a bare string, because an answer is a set of events: text today, tool
    calls and images later. Growing it then means adding an attribute rather than changing the
    signature of everything that returns one.

    Attributes:
        content: The text the model produced.
        model: The model that actually answered. It can differ from the one asked for, because
            a provider is free to route the call elsewhere.
        finish_reason: Why generation stopped.
        usage: What the call cost.
    """

    content: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
