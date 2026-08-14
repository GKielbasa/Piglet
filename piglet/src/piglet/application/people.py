"""One course task, in two passes: what a comparison can settle, then what only prose can."""

import csv
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from io import StringIO

from pydantic import BaseModel, ConfigDict, Field

from piglet.application.platform_client import PlatformClient
from piglet.domain.age import birth_years_for_age_range
from piglet.domain.llm.prompt import Prompt
from piglet.domain.ports import ChatModel
from piglet.llm.classification import classify_in_batches

__all__ = ["TASK_NAME", "Person", "solve"]

TASK_NAME = "people"
DATA_FILE = "people.csv"
BIRTH_PLACE = "Grudziądz"
GENDER = "M"
YOUNGEST, OLDEST = 20, 40
AS_OF_YEAR = 2026


class Tag(StrEnum):
    """What a description of somebody's work can be about.

    The set is closed, and one description may carry several of these at once or none at all.
    These sentences are the definitions the model classifies by — they are read as the
    instruction, so they are written for it rather than for a maintainer.

    IT — building, running or maintaining software and computer systems.
    transport — moving goods or passengers from one place to another.
    edukacja — teaching, training, or otherwise passing knowledge on.
    medycyna — treating patients, or other work inside healthcare.
    praca z ludźmi — work whose substance is dealing with other persons.
    praca z pojazdami — work with vehicles: driving them, loading them, servicing them.
    praca fizyczna — work whose substance is physical effort, with hands or with tools.
    """

    IT = "IT"
    TRANSPORT = "transport"
    EDUCATION = "edukacja"
    MEDICINE = "medycyna"
    WITH_OTHERS = "praca z ludźmi"
    WITH_VEHICLES = "praca z pojazdami"
    PHYSICAL = "praca fizyczna"


class PersonRecord(BaseModel):
    """One row of the platform's file, as it is written there.

    Attributes:
        name: Given name.
        surname: Family name.
        gender: `M` or `F`, as the file spells it.
        birth_date: Full date, from which only the year is ever used.
        birth_place: Town of birth.
        birth_country: Country of birth. Read but not used; leaving it out would make an
            unexpected column silently acceptable.
        job: A paragraph describing what the person does, in prose rather than as a title.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    surname: str
    gender: str
    birth_date: date = Field(alias="birthDate")
    birth_place: str = Field(alias="birthPlace")
    birth_country: str = Field(alias="birthCountry")
    job: str


class JobVerdict(BaseModel):
    """What one description of somebody's work is about.

    The reasoning is declared first on purpose. A model fills the fields in the order the
    schema gives them, so what it writes here becomes the context it then chooses labels in.

    Attributes:
        reasoning: Why these labels, in one sentence.
        tags: Every label that fits.
    """

    reasoning: str = Field(description="One sentence on what this description says the person actually does.")
    tags: list[Tag] = Field(description="Every label that fits this description. Empty when none of them does.")


class Person(BaseModel):
    """One person in the shape the platform expects an answer to carry.

    Attributes:
        name: Given name.
        surname: Family name.
        gender: As the file spelt it.
        born: Year of birth, as a number rather than a date.
        city: Town of birth.
        tags: Every label the model gave this person's work.
    """

    name: str
    surname: str
    gender: str
    born: int
    city: str
    tags: list[Tag]


def read_records(file_contents: str) -> list[PersonRecord]:
    """Parse the platform's file.

    Args:
        file_contents: The file as text.

    Returns:
        One record per row.

    Raises:
        ValidationError: If a row is missing a column or holds an unreadable date.
    """
    return [PersonRecord.model_validate(row) for row in csv.DictReader(StringIO(file_contents))]


def select_candidates(records: Iterable[PersonRecord]) -> list[PersonRecord]:
    """Keep the records that meet the criteria a comparison can settle.

    Three of the task's four criteria are comparisons, and only the fourth has to read prose.
    Deciding those three here is what keeps the model's share of the work small enough to be
    reliable, and cheap: it is the difference between judging a whole file and judging a few
    dozen records.

    Args:
        records: Every record read from the file.

    Returns:
        The records still in the running, in the order they were read.
    """
    years = birth_years_for_age_range(YOUNGEST, OLDEST, AS_OF_YEAR)
    return [
        record
        for record in records
        if record.gender == GENDER and record.birth_place == BIRTH_PLACE and record.birth_date.year in years
    ]


async def solve(chat_model: ChatModel, platform: PlatformClient, instruction: Prompt) -> tuple[list[Person], str]:
    """Find the people this task asks for, and submit them.

    Args:
        chat_model: Who judges the job descriptions.
        platform: Where the file comes from and where the answer goes.
        instruction: What classifying means, as a prompt.

    Returns:
        What was submitted, and what the platform answered.
    """
    candidates = select_candidates(read_records(await platform.download(DATA_FILE)))
    verdicts = await classify_in_batches(chat_model, [record.job for record in candidates], JobVerdict, instruction)
    answer = [
        Person(
            name=record.name,
            surname=record.surname,
            gender=record.gender,
            born=record.birth_date.year,
            city=record.birth_place,
            tags=verdict.tags,
        )
        for record, verdict in zip(candidates, verdicts, strict=True)
        if Tag.TRANSPORT in verdict.tags
    ]
    return answer, await platform.submit(TASK_NAME, answer)
