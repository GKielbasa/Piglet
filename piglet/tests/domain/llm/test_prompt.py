import pytest

from piglet.domain.llm.prompt import parse_prompt
from piglet.errors import MalformedPromptError

WELL_FORMED = """---
description: Assign each record every label that applies.
---

You classify records into a fixed taxonomy.

Answer with one verdict per record.
"""


def test_the_header_and_the_instruction_are_separated() -> None:
    prompt = parse_prompt("record-classification", WELL_FORMED)

    assert prompt.description == "Assign each record every label that applies."
    assert prompt.text.startswith("You classify records into a fixed taxonomy.")


def test_the_instruction_keeps_its_own_shape() -> None:
    assert "\n\nAnswer with one verdict per record." in parse_prompt("classification", WELL_FORMED).text


def test_the_name_comes_from_the_caller() -> None:
    assert parse_prompt("record-classification", WELL_FORMED).name == "record-classification"


def test_a_file_without_a_header_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="does not open"):
        parse_prompt("classification", "You classify records.\n")


def test_a_header_that_is_never_closed_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="never closed"):
        parse_prompt("classification", "---\ndescription: Something.\n")


def test_a_header_key_this_library_does_not_know_is_refused() -> None:
    source = "---\ndescription: Something.\nmodel: openai/gpt-4.1-mini\n---\n\nDo it.\n"

    with pytest.raises(MalformedPromptError, match="header is wrong"):
        parse_prompt("classification", source)


def test_a_header_without_a_description_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="header is wrong"):
        parse_prompt("classification", "---\nnote: Something.\n---\n\nDo it.\n")


def test_a_header_that_is_not_yaml_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="not valid YAML"):
        parse_prompt("classification", "---\ndescription: [unclosed\n---\n\nDo it.\n")


def test_a_header_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="not a mapping"):
        parse_prompt("classification", "---\n- one\n- two\n---\n\nDo it.\n")


def test_a_prompt_with_no_instruction_is_refused() -> None:
    with pytest.raises(MalformedPromptError, match="no instruction"):
        parse_prompt("classification", "---\ndescription: Something.\n---\n\n   \n")
