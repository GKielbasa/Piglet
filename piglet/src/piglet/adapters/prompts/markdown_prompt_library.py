"""Prompts read from markdown files, one file per prompt."""

from pathlib import Path

from piglet.domain.llm.prompt import Prompt, parse_prompt
from piglet.errors import PromptNotFoundError

__all__ = ["MarkdownPromptLibrary"]


class MarkdownPromptLibrary:
    """Loads a prompt from disk, at the moment it is used.

    The file is read on every call rather than remembered. That is the whole reason for keeping
    instructions in files instead of string literals: one can be corrected while a program is
    running, and later an agent can be handed the same directory as a tool of its own.

    Attributes:
        directory: Where the files live. Each prompt is `<name>.md` inside it.

    Example:
        >>> MarkdownPromptLibrary(Path("prompts")).load("record-classification").name
        'record-classification'
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self, name: str) -> Prompt:
        """Read one prompt.

        Args:
            name: The prompt's name, which is its file name without the extension.

        Returns:
            The prompt as the file describes it.

        Raises:
            PromptNotFoundError: If no file answers to that name.
            MalformedPromptError: If the file cannot be read as a prompt.
        """
        try:
            source = (self.directory / f"{name}.md").read_text(encoding="utf-8")
        except FileNotFoundError as missing:
            raise PromptNotFoundError(name, self.directory) from missing
        return parse_prompt(name, source)
