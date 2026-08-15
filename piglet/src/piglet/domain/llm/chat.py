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
    "ToolCall",
    "ToolDefinition",
]


class Role(StrEnum):
    """Who is speaking in one message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    """Why the model stopped generating.

    `OTHER` absorbs anything a provider names that this library does not know, so a new value
    on their side cannot break parsing on ours — the same rule the lesson gives for schemas we
    ask a model to fill, applied to the schema a model fills for us.
    """

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One capability offered to a model, as the model reads it.

    A model has no way to act on the world; it can only produce text. What turns that into an
    action is an agreement about the text, and this is our half of it: the name it may ask for,
    the sentence it decides by, and the arguments it may fill in. All three are read as part of
    the instruction, so the description carries as much weight here as any prompt.

    Attributes:
        name: What the model asks for. Worth making unlikely to collide — `send_email` rather
            than `send` — because collisions are resolved by the model, not by us.
        description: When to reach for this, in as few words as carry the decision.
        parameters: The arguments, as JSON Schema, already in the dialect the provider expects.
    """

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One request from the model to run a tool.

    The arguments stay as the text the model produced, unparsed. Reading them is the job of
    whoever owns the schema they were written against, and a model is free to answer with text
    that no schema accepts — which is a failure to be told about rather than one to hide inside
    a value.

    Attributes:
        call_id: The provider's identifier for this call. Its result has to quote it back, so
            it is what pairs a question with its answer when several travel at once.
        name: Which tool the model asked for.
        arguments: The arguments as raw JSON text, exactly as the model wrote them.
    """

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn in a conversation.

    Four kinds of turn share this shape. A system, user or assistant turn is text. An assistant
    turn that reaches for a tool carries calls instead of text, because the model produced no
    prose that time. A tool result carries the text a tool produced, and must say which call it
    answers.

    Attributes:
        role: Who is speaking.
        content: What they said. Empty on an assistant turn that only called tools.
        tool_calls: The tools this turn asked for, empty when it asked for none.
        tool_call_id: Which call this result answers. Only a tool result has one.

    Example:
        >>> ChatMessage(Role.USER, "How many moons does Mars have?").role
        <Role.USER: 'user'>
    """

    role: Role
    content: str = ""
    tool_calls: Sequence[ToolCall] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role is Role.TOOL and self.tool_call_id is None:
            raise InvalidRequestError("a tool result must name the call it answers")
        if self.role is not Role.TOOL and self.tool_call_id is not None:
            raise InvalidRequestError(f"a {self.role.value} message answers no call, so it may not name one")


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
        tools: What the model may reach for. Every definition travels on every call, used or
            not, so this list costs context on each step of a conversation rather than once.
    """

    messages: Sequence[ChatMessage]
    model: str | None = None
    response_schema: ResponseSchema | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    prompt_name: str | None = None
    tools: Sequence[ToolDefinition] = ()

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
        content: The text the model produced. Empty when it reached for tools instead, which is
            an answer and not a failure.
        model: The model that actually answered. It can differ from the one asked for, because
            a provider is free to route the call elsewhere.
        finish_reason: Why generation stopped.
        usage: What the call cost.
        tool_calls: The tools it asked for, empty when it asked for none.
    """

    content: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
    tool_calls: Sequence[ToolCall] = ()
