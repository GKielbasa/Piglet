import json
from enum import StrEnum
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field

from piglet.errors import InvalidRequestError
from piglet.llm.json_schema import to_strict_json_schema


class Tag(StrEnum):
    """A closed set of labels, the kind a taxonomy is made of."""

    TRANSPORT = "transport"
    TEACHING = "teaching"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """How sure the model claims to be."""

    HIGH = "high"
    LOW = "low"


class Verdict(BaseModel):
    """One record judged: reasoning first, then the verdict it leads to."""

    reasoning: str = Field(description="Why these tags fit, in one sentence.")
    tags: list[Tag]
    confidence: Confidence = Confidence.LOW
    note: str | None


class Batch(BaseModel):
    """Several verdicts at once, so a nested model has to be reached through a list."""

    items: list[Verdict]


class Wrapper[T: BaseModel](BaseModel):
    """A generic, whose name once parametrised carries brackets a provider will not accept."""

    item: T


def strict_schema_of(model: type[BaseModel]) -> dict[str, Any]:
    """The strict schema for a model, typed loosely enough for a test to walk into it."""
    return cast("dict[str, Any]", to_strict_json_schema(model).json_schema)


def test_the_schema_carries_the_model_name() -> None:
    assert to_strict_json_schema(Verdict).name == "Verdict"


def test_the_root_object_forbids_unnamed_properties() -> None:
    assert strict_schema_of(Verdict)["additionalProperties"] is False


def test_a_nested_object_forbids_them_too() -> None:
    assert strict_schema_of(Batch)["$defs"]["Verdict"]["additionalProperties"] is False


def test_a_field_with_a_default_is_still_required() -> None:
    assert "confidence" not in Verdict.model_json_schema()["required"]
    assert "confidence" in strict_schema_of(Verdict)["required"]


def test_the_default_itself_is_dropped() -> None:
    assert "default" in Verdict.model_json_schema()["properties"]["confidence"]
    assert "default" not in strict_schema_of(Verdict)["properties"]["confidence"]


def test_a_parametrised_generic_gets_a_name_a_provider_accepts() -> None:
    assert to_strict_json_schema(Wrapper[Verdict]).name == "Wrapper_Verdict"


def test_required_lists_every_property() -> None:
    schema = strict_schema_of(Verdict)

    assert set(schema["required"]) == set(schema["properties"])


def test_properties_keep_their_declaration_order() -> None:
    assert list(strict_schema_of(Verdict)["properties"]) == ["reasoning", "tags", "confidence", "note"]


def test_field_descriptions_survive() -> None:
    reasoning = strict_schema_of(Verdict)["properties"]["reasoning"]

    assert reasoning["description"] == "Why these tags fit, in one sentence."


def test_an_enum_keeps_its_closed_set() -> None:
    assert strict_schema_of(Verdict)["$defs"]["Tag"]["enum"] == ["transport", "teaching", "unknown"]


def test_an_optional_field_stays_a_union_with_null_and_is_still_required() -> None:
    schema = strict_schema_of(Verdict)

    assert {"type": "null"} in schema["properties"]["note"]["anyOf"]
    assert "note" in schema["required"]


def test_titles_are_removed_everywhere() -> None:
    schema = strict_schema_of(Batch)

    assert "title" not in schema
    assert "title" not in schema["$defs"]["Verdict"]
    assert "title" not in schema["$defs"]["Verdict"]["properties"]["reasoning"]
    assert "title" not in schema["$defs"]["Tag"]


def test_a_model_reached_through_a_list_is_made_strict() -> None:
    verdict = strict_schema_of(Batch)["$defs"]["Verdict"]

    assert verdict["additionalProperties"] is False
    assert "confidence" in verdict["required"]


def test_the_result_is_serialisable() -> None:
    assert json.loads(json.dumps(strict_schema_of(Batch)))["type"] == "object"


def test_a_mapping_is_refused_and_the_field_is_named() -> None:
    class WithMapping(BaseModel):
        counts: dict[str, int]

    with pytest.raises(InvalidRequestError, match=r"WithMapping\.counts"):
        to_strict_json_schema(WithMapping)


def test_a_mapping_of_anything_is_refused_too() -> None:
    class WithLooseMapping(BaseModel):
        payload: dict[str, Any]

    with pytest.raises(InvalidRequestError, match=r"WithLooseMapping\.payload"):
        to_strict_json_schema(WithLooseMapping)


def test_a_fixed_length_tuple_is_refused() -> None:
    class WithTuple(BaseModel):
        pair: tuple[int, str]

    with pytest.raises(InvalidRequestError, match=r"WithTuple\.pair"):
        to_strict_json_schema(WithTuple)


def test_a_refusal_names_the_nested_model_it_was_declared_in() -> None:
    class Nested(BaseModel):
        counts: dict[str, int]

    class Outer(BaseModel):
        items: list[Nested]

    with pytest.raises(InvalidRequestError, match=r"Nested\.counts"):
        to_strict_json_schema(Outer)
