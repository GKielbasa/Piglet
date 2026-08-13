"""A pydantic model, described the way a provider will enforce it."""

import re
from typing import Any

from pydantic import BaseModel

from piglet.domain.llm.chat import ResponseSchema

__all__ = ["to_strict_json_schema"]


def to_strict_json_schema(model: type[BaseModel]) -> ResponseSchema:
    """Describe a pydantic model in the dialect strict mode accepts.

    Three differences from what pydantic writes, each demanded by strict mode: every object
    forbids properties it does not name, every property is listed as required — optionality is
    expressed as a union with null rather than by absence — and the keywords strict mode does
    not name as supported are dropped, which here means `title` and `default`.

    Dropping `default` is not only caution about an unsupported keyword. Once every property is
    required, a default describes a case that can no longer arise, so leaving it in would tell
    the model about a state it will never be asked to produce.

    Field names and descriptions are left exactly as declared. They are part of the prompt
    rather than documentation: the model reads them to decide what belongs in each field.

    Args:
        model: The shape the answer must take.

    Returns:
        The schema, named after the model, ready to travel unchanged.
    """
    schema: dict[str, Any] = model.model_json_schema()
    _make_strict(schema)
    return ResponseSchema(name=_acceptable_name(model.__name__), json_schema=schema)


def _acceptable_name(class_name: str) -> str:
    """Turn a class name into one a provider will accept.

    Schema names are restricted to letters, digits, underscores and dashes. A pydantic generic
    parametrised at runtime is called `Batch[Verdict]`, which is outside that set — and is
    exactly how a batched call names the envelope it asks for.

    Args:
        class_name: The model's own name.

    Returns:
        The same name with everything else replaced by underscores.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", class_name).strip("_")


def _make_strict(node: dict[str, Any]) -> None:
    """Rewrite one schema node, and everything nested in it, where it stands.

    Args:
        node: The node to rewrite.
    """
    node.pop("title", None)
    node.pop("default", None)

    properties = node.get("properties")
    if properties is not None:
        node["additionalProperties"] = False
        # Declaration order is kept because preceding tokens steer the ones that follow: a field
        # the model fills first is context for the field it fills next.
        node["required"] = list(properties)

    for group in ("properties", "$defs"):
        for child in node.get(group, {}).values():
            _make_strict(child)
    for alternative in node.get("anyOf", []):
        _make_strict(alternative)
    items = node.get("items")
    if items is not None:
        _make_strict(items)
