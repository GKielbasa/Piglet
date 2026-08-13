"""Running one course task end to end, with the wiring each one needs."""

from dataclasses import dataclass

from piglet.adapters.prompts.markdown_prompt_library import MarkdownPromptLibrary
from piglet.app.config import Settings
from piglet.app.container import build_chat_model, build_http_client, build_llm_http_client, start_run
from piglet.application import people
from piglet.application.platform_client import PlatformClient
from piglet.application.platform_settings import PlatformSettings

__all__ = ["TaskOutcome", "run_task"]

CLASSIFICATION_PROMPT = "record-classification"


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """What one run of a task produced.

    Attributes:
        run_id: Correlates every log entry this run wrote.
        submitted: How many records were sent as the answer.
        reply: What the platform said, verbatim.
    """

    run_id: str
    submitted: int
    reply: str


async def run_task(name: str, settings: Settings) -> TaskOutcome:
    """Run one task by name.

    The course-specific objects are assembled here rather than in `app/container.py`: the
    composition root there is part of the tooling layer and may not know this platform exists.

    Args:
        name: Which task to run.
        settings: The tooling layer's configuration.

    Returns:
        What was submitted, and what came back.

    Raises:
        ValueError: If no task answers to that name.
    """
    if name != people.TASK_NAME:
        raise ValueError(f"no task named {name!r}")

    platform_settings = PlatformSettings()
    # The key travels in the URL path of every download, and every attempt writes its URL to
    # the log. Handing it to the redactor here is what keeps it out of the file.
    run_id = start_run(settings, secrets=[platform_settings.api_hub])
    instruction = MarkdownPromptLibrary(settings.prompts_dir).load(CLASSIFICATION_PROMPT)

    async with build_http_client(settings) as http_client, build_llm_http_client(settings) as llm_http_client:
        platform = PlatformClient(http_client, platform_settings.api_hub, platform_settings.base_url)
        chat_model = build_chat_model(settings, llm_http_client, run_id)
        answer, reply = await people.solve(chat_model, platform, instruction)
    return TaskOutcome(run_id, len(answer), reply)
