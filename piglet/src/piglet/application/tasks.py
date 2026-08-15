"""Running one course task end to end, with the wiring each one needs."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from piglet.adapters.prompts.markdown_prompt_library import MarkdownPromptLibrary
from piglet.app.config import Settings
from piglet.app.container import build_chat_model, build_http_client, build_llm_http_client, start_run
from piglet.application import findhim, people
from piglet.application.platform_client import PlatformClient
from piglet.application.platform_settings import PlatformSettings

__all__ = ["TASKS", "Task", "TaskOutcome", "run_task"]

CLASSIFICATION_PROMPT = "record-classification"
GAZETTEER_PROMPT = "town-coordinates"
INVESTIGATOR_PROMPT = "findhim-agent"


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


@dataclass(frozen=True, slots=True)
class Task:
    """One task that can be run, and enough about it to pick it out of a list.

    Attributes:
        name: What the caller types to ask for this one.
        summary: One line saying what running it does.
        run: What to call to run it.
    """

    name: str
    summary: str
    run: Callable[[Settings], Awaitable[TaskOutcome]]


async def run_task(name: str, settings: Settings) -> TaskOutcome:
    """Run one task by name.

    The course-specific objects are assembled here rather than in `app/container.py`: the
    composition root there is part of the tooling layer and may not know this platform exists.

    Args:
        name: Which task to run. `TASKS` holds the ones that answer.
        settings: The tooling layer's configuration.

    Returns:
        What was submitted, and what came back.

    Raises:
        ValueError: If no task answers to that name. The message names the ones that do,
            because a caller who guessed wrong has no other way to find out.
    """
    for task in TASKS:
        if task.name == name:
            return await task.run(settings)
    raise ValueError(f"no task named {name!r}; known: {', '.join(task.name for task in TASKS)}")


async def _run_people(settings: Settings) -> TaskOutcome:
    """Find the people this course asks for, submit them, and keep the answer.

    The answer is written down because the next task takes it as its input. Without that, the
    only way to get at it again is to run this one again, which submits a second time to say
    something already said.

    Args:
        settings: The tooling layer's configuration.

    Returns:
        What was submitted, and what came back.
    """
    platform_settings = PlatformSettings()
    # The key travels in the URL path of every download, and every attempt writes its URL to
    # the log. Handing it to the redactor here is what keeps it out of the file.
    run_id = start_run(settings, secrets=[platform_settings.api_hub])
    instruction = MarkdownPromptLibrary(settings.prompts_dir).load(CLASSIFICATION_PROMPT)

    async with build_http_client(settings) as http_client, build_llm_http_client(settings) as llm_http_client:
        platform = PlatformClient(http_client, platform_settings.api_hub, platform_settings.base_url)
        chat_model = build_chat_model(settings, llm_http_client, run_id)
        answer, reply = await people.solve(chat_model, platform, instruction)

    _keep(settings.answers_dir / f"{people.TASK_NAME}.json", answer)
    return TaskOutcome(run_id, len(answer), reply)


async def _run_findhim(settings: Settings) -> TaskOutcome:
    """Let an agent find the one person this task is about, and submit them.

    Args:
        settings: The tooling layer's configuration.

    Returns:
        What was submitted, and what came back.
    """
    platform_settings = PlatformSettings()
    run_id = start_run(settings, secrets=[platform_settings.api_hub])
    prompts = MarkdownPromptLibrary(settings.prompts_dir)

    async with build_http_client(settings) as http_client, build_llm_http_client(settings) as llm_http_client:
        platform = PlatformClient(http_client, platform_settings.api_hub, platform_settings.base_url)
        chat_model = build_chat_model(settings, llm_http_client, run_id)
        answer, reply = await findhim.solve(
            chat_model,
            platform,
            settings.answers_dir,
            prompts.load(GAZETTEER_PROMPT),
            prompts.load(INVESTIGATOR_PROMPT),
            run_id,
        )

    _keep(settings.answers_dir / f"{findhim.TASK_NAME}.json", answer)
    return TaskOutcome(run_id, 1, reply)


def _keep(path: Path, answer: BaseModel | list[people.Person]) -> None:
    """Write down what a task answered, where the next one can read it.

    Field names are ours rather than the platform's here — this is a file for us, and the
    aliases exist to satisfy a wire format we are not writing to.

    Args:
        path: Where to write it.
        answer: What was submitted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    written = (
        answer.model_dump(mode="json")
        if isinstance(answer, BaseModel)
        else [one.model_dump(mode="json") for one in answer]
    )
    path.write_text(json.dumps(written, ensure_ascii=False, indent=2), encoding="utf-8")


# Last in the file, not up with the other constants: it names the runners, so they have to be
# defined already. Registering a task means adding a line here and nowhere else.
TASKS: tuple[Task, ...] = (
    Task(people.TASK_NAME, "Sort a downloaded set of records with a model and submit the matches.", _run_people),
    Task(findhim.TASK_NAME, "Let an agent chase one person through the platform's endpoints.", _run_findhim),
)
