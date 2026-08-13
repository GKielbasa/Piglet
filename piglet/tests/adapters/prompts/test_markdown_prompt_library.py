from pathlib import Path

import pytest

from piglet.adapters.prompts.markdown_prompt_library import MarkdownPromptLibrary
from piglet.errors import PromptNotFoundError

SOURCE = "---\ndescription: Assign labels.\n---\n\nYou classify records.\n"
SHIPPED_PROMPTS = Path(__file__).parents[3] / "prompts"


def write_prompt(directory: Path, name: str, source: str = SOURCE) -> None:
    (directory / f"{name}.md").write_text(source, encoding="utf-8")


def test_a_prompt_on_disk_is_loaded_with_its_name_and_instruction(tmp_path: Path) -> None:
    write_prompt(tmp_path, "record-classification")

    prompt = MarkdownPromptLibrary(tmp_path).load("record-classification")

    assert prompt.name == "record-classification"
    assert prompt.text == "You classify records."


def test_a_name_with_no_file_says_where_it_looked(tmp_path: Path) -> None:
    with pytest.raises(PromptNotFoundError) as raised:
        MarkdownPromptLibrary(tmp_path).load("absent")

    assert raised.value.directory == tmp_path


def test_an_edit_between_two_loads_is_seen_by_the_second(tmp_path: Path) -> None:
    library = MarkdownPromptLibrary(tmp_path)
    write_prompt(tmp_path, "instruction")
    before = library.load("instruction").text

    write_prompt(tmp_path, "instruction", "---\ndescription: Assign labels.\n---\n\nYou classify differently now.\n")

    assert library.load("instruction").text != before


def test_the_extension_is_not_part_of_the_name(tmp_path: Path) -> None:
    write_prompt(tmp_path, "instruction")

    with pytest.raises(PromptNotFoundError):
        MarkdownPromptLibrary(tmp_path).load("instruction.md")


def test_the_prompt_that_ships_with_the_project_can_be_read() -> None:
    prompt = MarkdownPromptLibrary(SHIPPED_PROMPTS).load("record-classification")

    assert prompt.description
    assert prompt.text.startswith("You classify records into a fixed taxonomy.")
