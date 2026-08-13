"""A prompt as a file: a header describing it, and the instruction itself below."""

from dataclasses import dataclass

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from piglet.errors import MalformedPromptError

__all__ = ["Prompt", "PromptMetadata", "parse_prompt"]

_FENCE = "---"


@dataclass(frozen=True, slots=True)
class Prompt:
    """One instruction, as a file describes it.

    Attributes:
        name: Identity, taken from the file name rather than from the header. One name in one
            place: a header field repeating the file name is a second truth that can disagree
            with the first.
        description: What this prompt is for. Written for a reader, never sent to a model.
        text: The instruction itself, exactly as written below the header.
    """

    name: str
    description: str
    text: str


class PromptMetadata(BaseModel):
    """The header of a prompt file.

    Unknown keys are refused rather than ignored: a misspelt key that is quietly dropped looks
    from the outside exactly like a setting that had no effect.

    Attributes:
        description: What this prompt is for.
    """

    model_config = ConfigDict(extra="forbid")

    description: str


def parse_prompt(name: str, source: str) -> Prompt:
    """Read one prompt file.

    The format is a YAML header fenced by `---`, then the instruction. It is the convention
    every tool that treats prompts as files already uses, which is the reason for choosing it.

    Args:
        name: What to call this prompt. The library passes the file name.
        source: The whole file.

    Returns:
        The prompt.

    Raises:
        MalformedPromptError: If the header is missing, unreadable, carries a key this library
            does not know, or if nothing follows it.
    """
    header, text = _split(name, source)
    try:
        parsed = yaml.safe_load(header)
    except yaml.YAMLError as unreadable:
        raise MalformedPromptError(name, f"its header is not valid YAML: {unreadable}") from unreadable

    if not isinstance(parsed, dict):
        raise MalformedPromptError(name, "its header is not a mapping of keys to values")
    try:
        metadata = PromptMetadata.model_validate(parsed)
    except ValidationError as invalid:
        raise MalformedPromptError(name, f"its header is wrong: {invalid}") from invalid

    return Prompt(name=name, description=metadata.description, text=text)


def _split(name: str, source: str) -> tuple[str, str]:
    """Separate the header from the instruction.

    Args:
        name: The prompt being read, for the failure.
        source: The whole file.

    Returns:
        The header and the instruction, each stripped of the blank lines around it.

    Raises:
        MalformedPromptError: If there is no fenced header, or nothing after it.
    """
    if not source.startswith(f"{_FENCE}\n"):
        raise MalformedPromptError(name, f"it does not open with a {_FENCE} header")
    header, fence, text = source[len(_FENCE) + 1 :].partition(f"\n{_FENCE}\n")
    if not fence:
        raise MalformedPromptError(name, f"its {_FENCE} header is never closed")
    if not text.strip():
        raise MalformedPromptError(name, "it carries a header and no instruction")
    return header, text.strip()
