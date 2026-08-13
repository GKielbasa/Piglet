"""An answer whose shape the caller can rely on."""

from dataclasses import replace

from pydantic import BaseModel, ValidationError

from piglet.domain.llm.chat import ChatRequest
from piglet.domain.ports import ChatModel
from piglet.errors import SchemaViolationError
from piglet.llm.json_schema import to_strict_json_schema

__all__ = ["complete_as"]

_PREVIEW_CHARACTERS = 200


async def complete_as[T: BaseModel](chat_model: ChatModel, request: ChatRequest, schema: type[T]) -> T:
    """Ask for an answer of a given shape, and hand that shape back.

    A schema is not only a promise about the answer. Field names and their descriptions are
    read by the model as part of the instruction, so what the caller declares here is part of
    what it asks for.

    Args:
        chat_model: Who to ask.
        request: What to ask. Whatever response schema it carries is replaced by this one.
        schema: The shape the answer must take.

    Returns:
        The answer, parsed into `schema`.

    Raises:
        SchemaViolationError: If the answer cannot be read as `schema` — which means the
            provider did not enforce what it was given, so the fix is a model or a provider
            rather than another attempt.
    """
    response_schema = to_strict_json_schema(schema)
    answer = await chat_model.complete(replace(request, response_schema=response_schema))
    try:
        return schema.model_validate_json(answer.content)
    except ValidationError as violated:
        raise SchemaViolationError(
            response_schema.name, str(violated), answer.content[:_PREVIEW_CHARACTERS]
        ) from violated
