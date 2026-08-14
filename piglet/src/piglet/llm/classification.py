"""Many records judged against one taxonomy, a batch at a time."""

import asyncio
from collections.abc import Sequence

from pydantic import BaseModel, Field

from piglet.domain.llm.chat import ChatMessage, ChatRequest, Role
from piglet.domain.llm.prompt import Prompt
from piglet.domain.ports import ChatModel
from piglet.errors import ModelCallFailedError, SchemaViolationError
from piglet.llm.structured import complete_as

__all__ = ["Batch", "Numbered", "classify_in_batches"]


class Numbered[T: BaseModel](BaseModel):
    """One verdict, tied to the record it judges.

    Attributes:
        number: Which record this answers.
        verdict: The judgement itself, in whatever shape the caller asked for.
    """

    number: int = Field(description="The number of the record this verdict is for.")
    verdict: T


class Batch[T: BaseModel](BaseModel):
    """Every verdict for one batch of records.

    Attributes:
        verdicts: One per record, in the order the records were given.
    """

    verdicts: list[Numbered[T]] = Field(description="One verdict per record, in the order they were given.")


async def classify_in_batches[T: BaseModel](
    chat_model: ChatModel,
    records: Sequence[str],
    schema: type[T],
    instruction: Prompt,
    batch_size: int = 20,
    max_concurrent_batches: int = 4,
) -> list[T]:
    """Judge every record against one taxonomy, several records at a time.

    Three things happen here that one call could not. Records are asked about in batches,
    because a narrower question is answered better — not because the whole list would not fit.
    Batches travel concurrently under a limit, so a long list is neither a long wait nor a rate
    limit. And identical records are asked about once: a verdict follows from the record's
    text, so asking twice buys the same answer at twice the price.

    This function never learns the taxonomy. The caller declares it inside `schema`, as a
    closed set with a description on every label, and those descriptions are what the model
    reads to decide.

    Args:
        chat_model: Who to ask.
        records: The records to judge, worded as the model will read them.
        schema: The verdict for one record.
        instruction: What classifying means here. Its text becomes the system message and its
            name goes to the log.
        batch_size: How many records travel in one call.
        max_concurrent_batches: How many calls may be in flight at once.

    Returns:
        One verdict per record, in the order the records were given.

    Raises:
        SchemaViolationError: If a batch answers about a record twice, about one nobody asked
            about, or leaves one unanswered.
        ModelCallFailedError: If a batch failed twice with a failure of the provider's own.
        ModelAnswerTruncatedError: If an answer hit the token ceiling. Not retried — the same
            call stops in the same place.
    """
    if not records:
        return []
    # A dictionary rather than a set: it keeps first-seen order, so batches stay stable
    # between runs over the same input.
    unique = list(dict.fromkeys(records))
    batches = [unique[start : start + batch_size] for start in range(0, len(unique), batch_size)]
    at_once = asyncio.Semaphore(max_concurrent_batches)

    async def judge(batch: Sequence[str]) -> list[T]:
        async with at_once:
            try:
                return await _judge_one_batch(chat_model, batch, schema, instruction)
            except ModelCallFailedError:
                # One second chance, and only for this failure: it is the provider's own and
                # often passes. A truncated or schema-violating answer would repeat exactly.
                return await _judge_one_batch(chat_model, batch, schema, instruction)

    judged = await asyncio.gather(*(judge(batch) for batch in batches))
    verdicts = {
        record: verdict
        for batch, answers in zip(batches, judged, strict=True)
        for record, verdict in zip(batch, answers, strict=True)
    }
    return [verdicts[record] for record in records]


async def _judge_one_batch[T: BaseModel](
    chat_model: ChatModel, batch: Sequence[str], schema: type[T], instruction: Prompt
) -> list[T]:
    """Ask about one batch and put its verdicts back in order.

    Args:
        chat_model: Who to ask.
        batch: The records in this batch.
        schema: The verdict for one record.
        instruction: What classifying means here.

    Returns:
        One verdict per record of the batch, in the order the batch was given.
    """
    # `Batch[schema]` is an ordinary model at runtime. No type checker can follow a class
    # object used as a type argument, and that is the price of building the envelope from the
    # caller's schema instead of from a fixed one.
    envelope: type[Batch[T]] = Batch[schema]  # type: ignore[valid-type]
    numbered = "\n".join(f"{number}. {record}" for number, record in enumerate(batch, start=1))
    request = ChatRequest(
        [ChatMessage(Role.SYSTEM, instruction.text), ChatMessage(Role.USER, numbered)],
        temperature=0.0,
        prompt_name=instruction.name,
    )
    answered = await complete_as(chat_model, request, envelope)
    return _in_the_order_asked(answered.verdicts, len(batch))


def _in_the_order_asked[T: BaseModel](verdicts: Sequence[Numbered[T]], expected: int) -> list[T]:
    """Match one batch's verdicts back to its records.

    An enforced schema guarantees the shape of each verdict and promises nothing about how
    many arrive or which record each one is for, so that is checked here rather than trusted.

    Args:
        verdicts: What came back.
        expected: How many records were asked about.

    Returns:
        The verdicts alone, in the order the records were given.

    Raises:
        SchemaViolationError: If a number repeats, is outside the batch, or is missing.
    """
    by_number: dict[int, T] = {}
    for numbered in verdicts:
        if numbered.number in by_number:
            raise SchemaViolationError(Batch.__name__, f"record {numbered.number} was judged twice")
        by_number[numbered.number] = numbered.verdict

    asked_about = range(1, expected + 1)
    unasked = sorted(number for number in by_number if number not in asked_about)
    if unasked:
        raise SchemaViolationError(Batch.__name__, f"verdicts for records nobody asked about: {unasked}")
    unanswered = [number for number in asked_about if number not in by_number]
    if unanswered:
        raise SchemaViolationError(Batch.__name__, f"no verdict for record(s) {unanswered}")
    return [by_number[number] for number in asked_about]
