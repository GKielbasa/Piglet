"""Exception hierarchy for the whole library.

Every failure raised by piglet inherits from `PigletError`, so a caller can catch
this library without catching unrelated failures from the runtime. Each handled
error has its own type; nothing is ever swallowed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

# Annotations are strings at runtime under the import above, so these three are needed
# for type checking only. Imported for real they would make this module depend on the
# ones it describes, and `request.py` could not raise from here without a cycle.
#
# This pairing is safe here and unsafe above a pydantic model: pydantic resolves
# annotations at runtime, so a name it can only see under TYPE_CHECKING fails the model
# at import with `PydanticUndefinedAnnotation`. Exception classes never read their own
# annotations, which is why this file can afford it and `app/config.py` cannot.
if TYPE_CHECKING:
    from piglet.domain.http.request import HTTPMethod
    from piglet.domain.http.retry_policy import GiveUpReason
    from piglet.domain.http.service_profile import FailureClass
    from piglet.domain.llm.chat import TokenUsage

__all__ = [
    "AgentProducedNoAnswerError",
    "HTTPError",
    "InvalidRequestError",
    "MalformedPromptError",
    "ModelAnswerTruncatedError",
    "ModelCallFailedError",
    "ModelError",
    "PigletError",
    "PromptNotFoundError",
    "RetryExhaustedError",
    "SchemaViolationError",
    "ToolFailedError",
    "TransportError",
    "UnsafeToRepeatError",
]


class PigletError(Exception):
    """Root of the library's exception hierarchy."""


class InvalidRequestError(PigletError, ValueError):
    """A request this library cannot send, refused before anything travelled.

    A `ValueError` as well, because a bad argument is what it is: an ordinary
    `except ValueError` keeps working, while `except PigletError` now sees it too —
    which is what makes this module's first sentence true of every failure we raise.
    """


class TransportError(PigletError):
    """No response arrived: the connection failed, timed out or was refused.

    Attributes:
        url: The address the request was sent to.
        cause: What the underlying library raised. Kept rather than only formatted into
            the message, so a caller and a log entry can name the kind of failure.
        failure_class: Whether the failure may pass by itself. Decided by the adapter
            that caught it, which is the only place that knows the library's taxonomy.
        may_have_been_processed: Whether the server may already have acted on the
            request. RFC 9110's own wording. False only when the adapter is certain
            nothing travelled; True whenever it cannot tell, so a request that must not
            be repeated is refused rather than sent twice.
    """

    def __init__(
        self, url: str, cause: Exception, failure_class: FailureClass, may_have_been_processed: bool = True
    ) -> None:
        super().__init__(f"request to {url} never completed: {cause}")
        self.url = url
        self.cause = cause
        self.failure_class = failure_class
        self.may_have_been_processed = may_have_been_processed


class HTTPError(PigletError):
    """A response arrived and its status marks the request as failed.

    Attributes:
        url: The address that answered.
        status_code: The status it answered with.
        attempts: How many attempts were made before this answer arrived. Required
            rather than defaulted: a permanent status can follow several transient
            ones, and a caller reading `1` where 3 happened is misled about the cost.
        body_preview: The beginning of what the service said, or None where nothing
            was kept. A status names a category; the body names the cause, and a
            caller that has to explain the failure to somebody else — a person, or a
            model deciding what to try next — has only this to explain it with.
    """

    def __init__(self, url: str, status_code: int, attempts: int, body_preview: str | None = None) -> None:
        super().__init__(f"{url} answered with status {status_code} after {attempts} attempt(s)")
        self.url = url
        self.status_code = status_code
        self.attempts = attempts
        self.body_preview = body_preview


class RetryExhaustedError(PigletError):
    """The retry policy gave up before the request succeeded.

    Attributes:
        url: The address that kept failing.
        attempts: How many attempts were made in total.
        failure_class: What kind of failure it kept answering with.
        give_up_reason: Which limit ran out — the attempts, the waiting budget or the
            deadline for the request as a whole.
        last_status_code: The status of the final attempt, if one arrived.
    """

    def __init__(
        self,
        url: str,
        attempts: int,
        failure_class: FailureClass,
        give_up_reason: GiveUpReason,
        last_status_code: int | None = None,
    ) -> None:
        ending = f"last status {last_status_code}" if last_status_code is not None else "no response ever arrived"
        super().__init__(f"{url} still failing after {attempts} attempt(s): {ending}")
        self.url = url
        self.attempts = attempts
        self.failure_class = failure_class
        self.give_up_reason = give_up_reason
        self.last_status_code = last_status_code


class UnsafeToRepeatError(PigletError):
    """A failure that might have passed, on a request that must not be sent twice.

    Nothing ran out here: we refused to send it again, because the server may already
    have acted on it. The remedy is a change at the call site rather than a longer
    budget, which is why this is not a `RetryExhaustedError`.

    `attempts` is not always 1. A failure the guard exempts — throttling, or one raised
    before the request travelled — is retried, so a later attempt can be the one that
    reaches the guard. The caller needs the count to know how many times the operation
    may already have been carried out.

    Attributes:
        url: The address that failed.
        method: The verb that may not be repeated.
        attempts: How many times the request was sent before we refused to send it again.
        status_code: The status that failed, or None when no response arrived at all.
    """

    def __init__(self, url: str, method: HTTPMethod, attempts: int, status_code: int | None = None) -> None:
        ending = f"answered with status {status_code}" if status_code is not None else "never completed"
        super().__init__(
            f"{method.value} {url} {ending} after {attempts} attempt(s) and may not be repeated automatically"
        )
        self.url = url
        self.method = method
        self.attempts = attempts
        self.status_code = status_code


class ModelError(PigletError):
    """A call reached the model provider, and what came back cannot be used.

    Separate from the failures above it because the exchange itself succeeded. A caller that
    needs to tell "the network is bad" from "the model is not cooperating" catches this.
    """


class ModelCallFailedError(ModelError):
    """The provider's own answer says the call failed.

    A failure that happens while the model is generating arrives inside a successful response,
    so nothing below this layer can see it: the HTTP client reads a 200 as success, never
    retries it, and would remember it if it were allowed to cache.

    Attributes:
        model: The model that was asked.
        provider_message: What the provider said went wrong, in its own words.
        code: The code it named, or None when it named none.
    """

    def __init__(self, model: str, provider_message: str, code: int | None = None) -> None:
        named = f" (code {code})" if code is not None else ""
        super().__init__(f"{model} reported a failure{named}: {provider_message}")
        self.model = model
        self.provider_message = provider_message
        self.code = code


class ModelAnswerTruncatedError(ModelError):
    """Generation stopped at a token ceiling, so the answer is a fragment.

    Its own class rather than one more `ModelCallFailedError`, because this is the failure that
    names its own remedy: the ceiling was too low, and repeating the call unchanged reaches it
    again in the same place.

    Attributes:
        model: The model that answered.
        usage: What the fragment cost. It was generated in full and is billed in full, so this
            is the bill rather than an estimate — and the reason the failure carries it at all,
            since a caller keeping account of what a run spends must count this call too.
        max_output_tokens: The ceiling we asked for, or None when the provider's own stopped it.
    """

    def __init__(self, model: str, usage: TokenUsage, max_output_tokens: int | None = None) -> None:
        ceiling = (
            f"the ceiling of {max_output_tokens}" if max_output_tokens is not None else "the provider's own ceiling"
        )
        super().__init__(f"{model} hit {ceiling} after {usage.completion_tokens} token(s); the answer is incomplete")
        self.model = model
        self.usage = usage
        self.max_output_tokens = max_output_tokens


class SchemaViolationError(ModelError):
    """The answer arrived whole and does not honour the schema it was asked for.

    An enforced schema guarantees a shape, not a count: a batch can come back short, or with one
    index repeated, while every field in it is well formed.

    Attributes:
        schema_name: The schema the answer was measured against.
        reason: What does not fit, in one line.
        answer_preview: The beginning of what came back, or None when none was kept.
    """

    def __init__(self, schema_name: str, reason: str, answer_preview: str | None = None) -> None:
        super().__init__(f"the answer does not match schema {schema_name!r}: {reason}")
        self.schema_name = schema_name
        self.reason = reason
        self.answer_preview = answer_preview


class ToolFailedError(PigletError):
    """A tool could not do what it was asked, in a way the model can act on.

    Raised by the tool itself rather than by the machinery around it, because only the tool
    knows what a failure means. A person who is not on a list, an argument outside a permitted
    range, a resource that does not exist — the model can try something else. A dead network
    cannot be reasoned around, so a tool does not catch that, and it travels past the registry
    and stops the run.

    The message is the one the model will read, so it is written for the model: what went
    wrong, and what to do about it.

    Attributes:
        advice: What the model is told. Not a diagnosis for a maintainer.
    """

    def __init__(self, advice: str) -> None:
        super().__init__(advice)
        self.advice = advice


class AgentProducedNoAnswerError(PigletError):
    """A loop finished without ever recording the answer it was asked for.

    The alternative — reading an answer out of whatever prose the model stopped on — is a second
    route to a submission nobody checked, so this is a failure rather than a fallback.

    Attributes:
        stop_reason: What ended the loop, in its own words.
        steps_taken: How many times the model was asked before it stopped.
        run_id: Which run to read back. The exchanges are on disk under it, and they are the
            only place that says what the model was actually doing instead.
        account: What the model said about finding nothing, where it said anything. Concluding
            that there is no answer is a real conclusion and a different event from wandering
            off or running out of steps, so a caller is not told the same sentence for both.
    """

    def __init__(self, stop_reason: str, steps_taken: int, run_id: str, account: str | None = None) -> None:
        what_happened = (
            f"concluded there is no answer: {account}"
            if account is not None
            else f"stopped ({stop_reason}) without recording an answer"
        )
        super().__init__(f"after {steps_taken} step(s) the agent {what_happened}; what it said is under run {run_id}")
        self.stop_reason = stop_reason
        self.steps_taken = steps_taken
        self.run_id = run_id
        self.account = account


class PromptNotFoundError(PigletError):
    """Nothing on disk answers to that prompt name.

    Attributes:
        name: The prompt that was asked for.
        directory: Where it was looked for, so a wrong working directory says so itself.
    """

    def __init__(self, name: str, directory: Path) -> None:
        super().__init__(f"no prompt named {name!r} in {directory.resolve()}")
        self.name = name
        self.directory = directory


class MalformedPromptError(PigletError):
    """A prompt file exists and cannot be read as a prompt.

    Raised rather than tolerated, because the alternative is a run that quietly instructs a
    model with an empty string or with a key nobody reads.

    Attributes:
        name: The prompt that was being read.
        reason: What is wrong with it.
    """

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"prompt {name!r} cannot be read: {reason}")
        self.name = name
        self.reason = reason
