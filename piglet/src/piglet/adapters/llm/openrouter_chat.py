"""OpenRouter's Chat Completions endpoint, spoken through the resilient HTTP client."""

import json
import time
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field, SecretStr, ValidationError
from structlog.typing import FilteringBoundLogger

from piglet.adapters.http.resilient_client import ResilientHTTPClient
from piglet.domain.http.request import HTTPMethod, HTTPRequest
from piglet.domain.http.response import HTTPResponse
from piglet.domain.llm.chat import ChatCompletion, ChatRequest, FinishReason, TokenUsage
from piglet.errors import ModelAnswerTruncatedError, ModelCallFailedError, RetryExhaustedError

__all__ = ["OpenRouterChatModel"]

_NO_PROVIDER_FOR_THE_PARAMETERS = 503


class _Outcome(StrEnum):
    """How one call ended, as the log records it."""

    OK = "ok"
    PROVIDER_ERROR = "provider_error"
    TRUNCATED = "truncated"
    HTTP_FAILURE = "http_failure"


class _WireMessage(BaseModel):
    """One message as the endpoint returns it."""

    content: str | None = None


class _WireChoice(BaseModel):
    """One candidate answer."""

    finish_reason: str | None = None
    message: _WireMessage


class _WireUsage(BaseModel):
    """What the call consumed, as the endpoint accounts for it."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None


class _WireError(BaseModel):
    """A failure the provider reports in its own words."""

    code: int | None = None
    message: str = ""


class _WireAnswer(BaseModel):
    """A whole response, in either of the two shapes it arrives in.

    Every field carries a default because the same 200 can hold an answer or an error, and
    which one it is cannot be known before parsing it.
    """

    model: str = ""
    choices: list[_WireChoice] = Field(default_factory=list[_WireChoice])
    usage: _WireUsage = Field(default_factory=_WireUsage)
    error: _WireError | None = None


class OpenRouterChatModel:
    """Asks OpenRouter, and turns what comes back into a `ChatCompletion`.

    Retrying, backoff and the per-attempt log entry belong to the client underneath; this class
    builds one request, reads one answer, and names what went wrong when the answer says so.

    Attributes:
        http_client: Where the request goes. Built without a cache — see `build_llm_http_client`.
        api_key: Credential for the provider. Never logged: the log's redactor is given this
            same value at startup.
        default_model: Which model answers when a request names none.
        base_url: Where the provider listens, without a trailing slash.
        logger: Where finished calls are recorded.

    Example:
        >>> async with build_llm_http_client(settings) as http_client:
        ...     model = OpenRouterChatModel(http_client, settings.openrouter_api_key, "openai/gpt-4.1-mini", url)
        ...     answer = await model.complete(ChatRequest([ChatMessage(Role.USER, "Say hello.")]))
    """

    def __init__(
        self,
        http_client: ResilientHTTPClient,
        api_key: SecretStr,
        default_model: str,
        base_url: str,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self.http_client = http_client
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = base_url
        self.logger = logger or structlog.get_logger()

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        """Ask the model, and wait for what it says.

        Args:
            request: What to ask.

        Returns:
            The answer, together with what it cost.

        Raises:
            ModelCallFailedError: If the answer reports a failure of the provider's own, holds
                no single choice, or cannot be read at all.
            ModelAnswerTruncatedError: If generation stopped at a token ceiling.
            HTTPError: If the status marks the request itself as wrong — a key that is not
                accepted, an account out of credit.
            RetryExhaustedError: If the endpoint kept failing until a budget ran out.
        """
        model = request.model or self.default_model
        started = time.perf_counter()
        outcome = _Outcome.HTTP_FAILURE
        completion: ChatCompletion | None = None
        try:
            response = await self._send(request, model)
            completion = _read_answer(response, model, request.max_output_tokens)
            outcome = _Outcome.OK
            return completion
        except ModelCallFailedError:
            outcome = _Outcome.PROVIDER_ERROR
            raise
        except ModelAnswerTruncatedError:
            outcome = _Outcome.TRUNCATED
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            self._record_call(request, model, outcome, duration_ms, completion)

    async def _send(self, request: ChatRequest, model: str) -> HTTPResponse:
        """Put one request on the wire.

        Args:
            request: What to ask.
            model: Which model to ask, already resolved against the default.

        Returns:
            Whatever answered, as long as its status was a success.

        Raises:
            ModelCallFailedError: If a schema was asked for and no provider offering it ever
                answered. Translated here because `RetryExhaustedError` would otherwise report
                a network that kept failing, which is not what happened.
        """
        http_request = HTTPRequest(
            HTTPMethod.POST,
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            },
            body=json.dumps(_build_body(request, model)).encode(),
        )
        try:
            # A completion has no side effect but its cost, so repeating one is safe — which
            # RFC 9110 cannot know about a POST, and the client therefore has to be told.
            return await self.http_client.send(http_request, is_safe_to_repeat=True)
        except RetryExhaustedError as exhausted:
            schema = request.response_schema
            if schema is not None and exhausted.last_status_code == _NO_PROVIDER_FOR_THE_PARAMETERS:
                raise ModelCallFailedError(
                    model,
                    f"no provider answered that can enforce the schema {schema.name!r}",
                    exhausted.last_status_code,
                ) from exhausted
            raise

    def _record_call(
        self,
        request: ChatRequest,
        model: str,
        outcome: _Outcome,
        duration_ms: float,
        completion: ChatCompletion | None,
    ) -> None:
        """Write the entry for one finished call, however it finished.

        The URL never varies, so the HTTP entry beneath this one cannot say which model was
        asked, what it cost, or which prompt produced it. A field that does not apply is absent
        rather than null.

        Args:
            request: What was asked.
            model: Which model was asked for.
            outcome: How the call ended.
            duration_ms: How long it took altogether, retries included.
            completion: The answer, or None when none was understood.
        """
        entry = self.logger.bind(model=model, outcome=outcome, duration_ms=duration_ms)
        if request.prompt_name is not None:
            entry = entry.bind(prompt_name=request.prompt_name)
        if completion is not None:
            entry = entry.bind(
                model_answered=completion.model,
                finish_reason=completion.finish_reason,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
            )
            if completion.usage.cost_usd is not None:
                entry = entry.bind(cost_usd=completion.usage.cost_usd)
        entry.info("llm_call_finished")


def _build_body(request: ChatRequest, model: str) -> dict[str, Any]:
    """Compose the JSON body for one call.

    A field the request leaves unset is left out entirely rather than sent as null, so the
    provider's own default applies — temperature in particular differs between models and is
    theirs to choose.

    Args:
        request: What to ask.
        model: Which model to ask, already resolved against the default.

    Returns:
        The body, ready to be serialised.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": message.role.value, "content": message.content} for message in request.messages],
    }
    if request.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_schema.name,
                "strict": True,
                "schema": request.response_schema.json_schema,
            },
        }
        # Support for enforced schemas differs between the models behind this one endpoint.
        # Without this, a call can be routed to one that ignores the schema and answers prose.
        body["provider"] = {"require_parameters": True}
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        body["max_tokens"] = request.max_output_tokens
    return body


def _read_answer(response: HTTPResponse, model: str, max_output_tokens: int | None) -> ChatCompletion:
    """Turn one successful response into an answer, or into the failure it describes.

    A status of 200 is not agreement: a failure that happens while the model is generating is
    reported inside a successful response, so this is the first place able to see it.

    Args:
        response: What came back.
        model: Which model was asked, for the failures that name one.
        max_output_tokens: The ceiling that was asked for, if any.

    Returns:
        The answer.

    Raises:
        ModelCallFailedError: If the body reports a failure, cannot be read, or does not hold
            exactly one choice.
        ModelAnswerTruncatedError: If generation stopped at the token ceiling.
    """
    try:
        answer = _WireAnswer.model_validate_json(response.body)
    except ValidationError as unreadable:
        raise ModelCallFailedError(model, f"the response could not be read: {unreadable}") from unreadable

    if answer.error is not None:
        raise ModelCallFailedError(model, answer.error.message, answer.error.code)
    if len(answer.choices) != 1:
        raise ModelCallFailedError(model, f"expected exactly one choice, got {len(answer.choices)}")

    choice = answer.choices[0]
    answered_by = answer.model or model
    usage = TokenUsage(answer.usage.prompt_tokens, answer.usage.completion_tokens, answer.usage.cost)
    finish_reason = _finish_reason(choice.finish_reason)
    if finish_reason is FinishReason.LENGTH:
        raise ModelAnswerTruncatedError(answered_by, usage.completion_tokens, max_output_tokens)
    return ChatCompletion(choice.message.content or "", answered_by, finish_reason, usage)


def _finish_reason(named: str | None) -> FinishReason:
    """Read the provider's word for why generation stopped.

    Args:
        named: What the provider called it, or None when it said nothing.

    Returns:
        The matching reason, or `OTHER` for a word this library does not know, or for no word
        at all — a provider is free to invent one, and an unknown value must not stop us
        reading the answer itself.
    """
    if named is None:
        return FinishReason.OTHER
    try:
        return FinishReason(named)
    except ValueError:
        return FinishReason.OTHER
