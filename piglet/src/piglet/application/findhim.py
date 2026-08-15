"""One course task, run by an agent: the model chooses the order, the code does the measuring."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import inf
from pathlib import Path

import structlog
from pydantic import BaseModel, Field, SecretStr, TypeAdapter, ValidationError

from piglet.agent.loop import run_agent
from piglet.application.platform_client import PlatformClient
from piglet.domain.geo import Coordinates, distance_km
from piglet.domain.llm.chat import ChatMessage, ChatRequest, Role
from piglet.domain.llm.prompt import Prompt
from piglet.domain.ports import ChatModel
from piglet.errors import (
    AgentProducedNoAnswerError,
    HTTPError,
    InvalidRequestError,
    SchemaViolationError,
    ToolFailedError,
)
from piglet.llm.structured import complete_as
from piglet.tools.registry import ToolRegistry, define_tool

__all__ = ["TASK_NAME", "Answer", "solve"]

TASK_NAME = "findhim"
SITES_FILE = "findhim_locations.json"
PREVIOUS_ANSWER = "people.json"

# A turn per person, one for the level, one for the report, one spare for a report the guard
# sends back. Fixed, it would run out the day the previous task returns a longer list.
STEPS_BESIDES_THE_PEOPLE = 3

# The mark the log's redactor uses, by value rather than by import: that constant is an adapter's.
_REDACTION_MARK = "***"

# The list keys sites by town, and the coordinates of a town are nowhere in it, so a model
# supplies them. This sentence is what stops it choosing the wrong village of the same name.
WHERE_THESE_TOWNS_ARE = "These are Polish towns, each of them the site of a power station."


class Site(BaseModel):
    """One site, as the platform's file lists it.

    Attributes:
        is_active: Whether it is running. Carried through to the model rather than filtered on:
            nothing in the task says an idle site does not count.
        power: What it produces, as free text. Read but not used.
        code: The identifier the answer has to carry.
    """

    is_active: bool
    power: str
    code: str


class SiteList(BaseModel):
    """The platform's file, whole."""

    power_plants: dict[str, Site]


class Sighting(BaseModel):
    """One place somebody was seen.

    Bounded here rather than left to `Coordinates`, because this is the boundary: a number
    outside the earth arrives from the platform, and reading it is what has to fail. Rejected a
    line later instead, it would leave as an `InvalidRequestError` — which is not a failure a
    tool is allowed to raise, and would end the run instead of the lookup.
    """

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AccessLevel(BaseModel):
    """What the platform says about somebody's clearance.

    The level is passed on exactly as it arrives. Coercing it to be safe would hide the day the
    platform starts answering with something else.
    """

    access_level: int = Field(alias="accessLevel")


class Suspect(BaseModel):
    """One person from the previous task's answer.

    Its own model rather than the one that wrote the file: the file is a boundary, and three of
    its six fields are all this task needs. Anything else in there is ignored.

    Attributes:
        name: Given name.
        surname: Family name.
        born: Year of birth, which the clearance endpoint asks for and the model never sees.
    """

    name: str
    surname: str
    born: int


class TownLocation(BaseModel):
    """Where one town is, or that it is not known.

    Both coordinates may be null, because a schema that demands a number leaves inventing one
    as the only way to answer. A town this list names more than one of is exactly where that
    would happen, and an invented centre would then be measured against as though it were real.
    """

    town: str = Field(description="The town's name, exactly as it was given to you.")
    latitude: float | None = Field(description="Degrees north of the equator, -90 to 90. Null if you do not know.")
    longitude: float | None = Field(
        description="Degrees east of the prime meridian, -180 to 180. Null if you do not know."
    )


class TownLocations(BaseModel):
    """Where each of the towns is."""

    towns: list[TownLocation] = Field(description="One entry per town given, in the order they were given.")


class AskAboutSightings(BaseModel):
    """What the sightings endpoint is asked."""

    name: str
    surname: str


class AskAboutAccess(BaseModel):
    """What the clearance endpoint is asked.

    The year travels under the platform's own spelling of it, which is what keeps that spelling
    in one place instead of in a dictionary literal at the call site.
    """

    name: str
    surname: str
    birth_year: int = Field(serialization_alias="birthYear")


class SurvivorName(BaseModel):
    """Who to ask about."""

    name: str = Field(description="The person's given name, spelt exactly as the list spells it.")
    surname: str = Field(description="The person's family name, spelt exactly as the list spells it.")


class Finding(BaseModel):
    """The answer, and the case for it.

    `reasoning` is declared first on purpose: a model fills the fields in the order the schema
    gives them, so the case it makes here becomes the context the four values are chosen in.
    """

    reasoning: str = Field(description="How the measurements led to this person, in one or two sentences.")
    name: str = Field(description="The person's given name, as the list spells it.")
    surname: str = Field(description="The person's family name, as the list spells it.")
    access_level: int = Field(description="The level, exactly as get_survivor_access_level reported it.")
    site_code: str = Field(description="The code of the site, exactly as get_survivor_sightings reported it.")


class NoCandidate(BaseModel):
    """Nobody was close enough to be the answer."""

    reasoning: str = Field(description="What you measured, and why none of it supports naming anybody.")


class Answer(BaseModel):
    """What the platform is told, in the field names it uses.

    Attributes:
        name: Given name.
        surname: Family name.
        access_level: The level the platform itself reported.
        power_plant: The site's code.
    """

    name: str
    surname: str
    access_level: int = Field(serialization_alias="accessLevel")
    power_plant: str = Field(serialization_alias="powerPlant")


@dataclass(frozen=True, slots=True)
class PlacedSite:
    """One site, once somebody has said where its town is.

    Attributes:
        town: The town it stands at.
        code: Its identifier.
        is_active: Whether it is running.
        where: Where the town is.
    """

    town: str
    code: str
    is_active: bool
    where: Coordinates


class Investigation:
    """The four tools of this task, and the state they share.

    A class because the tools are not independent: what one of them learned is what makes the
    next one checkable. The clearance the platform reported is remembered so that the level the
    model finally reports can be compared against it, and the site each person was measured
    against is remembered for the same reason. Without that the model's word would be the only
    thing standing behind a submission.

    Attributes:
        platform: Where the answers about people come from.
        sites: Every site, with its town's coordinates.
        survivors: The people who may be asked about, and nobody else.
        finding: What the model reported, or None until it does.
        gave_up: The model's account of finding nobody, or None.
    """

    def __init__(self, platform: PlatformClient, sites: Sequence[PlacedSite], survivors: Sequence[Suspect]) -> None:
        self.platform = platform
        self.sites = tuple(sites)
        self.survivors = tuple(survivors)
        self.finding: Finding | None = None
        self.gave_up: NoCandidate | None = None
        self._levels: dict[tuple[str, str], int] = {}
        self._measured_against: dict[tuple[str, str], str] = {}
        self._distances: dict[tuple[str, str], float] = {}
        self._logger = structlog.get_logger()

    def as_registry(self) -> ToolRegistry:
        """Offer these four as tools.

        Returns:
            The registry, in the order the model should read them.
        """
        return ToolRegistry(
            [
                define_tool(
                    "get_survivor_sightings",
                    "Where somebody was seen, reported as the site nearest to any of those places and how far away "
                    "it was in kilometres. Use it once per person on your list.",
                    SurvivorName,
                    self.sightings,
                ),
                define_tool(
                    "get_survivor_access_level",
                    "The access level of one person, as a number. Ask only about the person you have settled on.",
                    SurvivorName,
                    self.access_level,
                ),
                define_tool(
                    "report_finding",
                    "Report who it is, their access level and the site's code. Ends your work; call it once.",
                    Finding,
                    self.record,
                    ends_the_run=True,
                ),
                define_tool(
                    "report_no_candidate",
                    "Report that nobody was near a site. Ends your work; call it only after measuring everybody.",
                    NoCandidate,
                    self.record_nothing,
                    ends_the_run=True,
                ),
            ]
        )

    async def sightings(self, asked: SurvivorName) -> str:
        """Answer where one person was seen, already measured against every site.

        Only the closest of them is reported. The model decides one thing about each person —
        whether they are the candidate — and every other sighting is context spent on nothing.

        Args:
            asked: Who to look up.

        Returns:
            How many sightings there were, and the nearest site to any of them.

        Raises:
            ToolFailedError: If nobody by that name is on the list, or the platform declines.
        """
        person = self._on_the_list(asked)
        seen = await self._where_seen(person)
        if not seen:
            # Written down as unreachable rather than left out, so that the guard below can tell
            # somebody measured and found nowhere near a site from somebody not yet measured.
            self._distances[_who(person.name, person.surname)] = inf
            return f"{person.name} {person.surname} was never seen anywhere. Move on to the next person."

        site, how_far = min(
            ((site, distance_km(site.where, point)) for site in self.sites for point in seen),
            key=lambda measured: measured[1],
        )
        self._measured_against[_who(person.name, person.surname)] = site.code
        self._distances[_who(person.name, person.surname)] = how_far
        self._logger.info("nearest_site_measured", site=site.town, code=site.code, distance_km=round(how_far, 1))
        standing = "in service" if site.is_active else "out of service"
        return (
            f"{len(seen)} sighting(s). The closest was {how_far:.1f} km from the site at {site.town} "
            f"(code {site.code}, {standing}). No other site was nearer to any of them."
        )

    async def access_level(self, asked: SurvivorName) -> str:
        """Answer what one person's access level is.

        The year of birth the platform demands is not an argument. It is on the list beside the
        name, so asking the model for it would only create something for it to get wrong.

        Args:
            asked: Who to look up.

        Returns:
            The level, as the platform reported it.

        Raises:
            ToolFailedError: If nobody by that name is on the list, or the platform declines.
        """
        person = self._on_the_list(asked)
        answered = await self._ask(
            "accesslevel", AskAboutAccess(name=person.name, surname=person.surname, birth_year=person.born)
        )
        try:
            level = AccessLevel.model_validate_json(answered).access_level
        except ValidationError as unreadable:
            raise ToolFailedError(f"The access level for {person.name} {person.surname} came back unreadable.") from (
                unreadable
            )
        self._levels[_who(person.name, person.surname)] = level
        return f"{person.name} {person.surname} has access level {level}."

    async def record(self, reported: Finding) -> str:
        """Take down the answer, once it survives being checked against what the tools said.

        Every value here has already passed through a tool, so none of it has to be taken on
        trust. A model that misremembers a level or a code is the ordinary failure of a long
        conversation, and this is the last place it can be caught before a submission.

        Args:
            reported: What the model concluded.

        Returns:
            Confirmation, and that there is nothing further to do.

        Raises:
            ToolFailedError: If any of it disagrees with what a tool actually reported.
        """
        person = self._on_the_list(SurvivorName(name=reported.name, surname=reported.surname))
        who = _who(person.name, person.surname)

        known_level = self._levels.get(who)
        if known_level is None:
            raise ToolFailedError(
                f"No access level has been fetched for {person.name} {person.surname}. "
                "Call get_survivor_access_level for them first, then report again."
            )
        if known_level != reported.access_level:
            raise ToolFailedError(
                f"Access level {reported.access_level} is not what was reported for {person.name} "
                f"{person.surname}, which was {known_level}. Report the number the tool gave you."
            )

        measured = self._measured_against.get(who)
        if measured is None:
            raise ToolFailedError(
                f"No site has been measured for {person.name} {person.surname}. "
                "Call get_survivor_sightings for them first, then report again."
            )
        if measured != reported.site_code:
            raise ToolFailedError(
                f"Site code {reported.site_code!r} is not the one measured for {person.name} "
                f"{person.surname}, which was {measured!r}. Report the code the tool gave you."
            )

        # The checks above are made for whoever was named; which person to name was still the
        # model's word alone. Here it is measured.
        self._refuse_until_everybody_is_measured()
        nearest = min(self._distances, key=lambda measured_person: self._distances[measured_person])
        if nearest != who:
            raise ToolFailedError(
                f"{person.name} {person.surname} was {self._distances[who]:.1f} km from the nearest site, "
                f"and somebody else on your list was closer, at {self._distances[nearest]:.1f} km. "
                "Compare the distances again and report whoever is nearest."
            )

        # The level and the code above are compared against what a tool reported; a name is only
        # matched, and `_who` matches across capitalisation. Without this, `cezary żurek` reaches
        # the platform in that spelling.
        self.finding = reported.model_copy(update={"name": person.name, "surname": person.surname})
        return "Recorded. Nothing further is needed."

    async def record_nothing(self, reported: NoCandidate) -> str:
        """Take down that there is no answer to give, once nobody is left to measure.

        This tool ends the run, which is what makes an unchecked call to it expensive: the run
        is over, and nothing that comes afterwards can establish what it skipped. So it carries
        the same guard as `record` — the one they share is that everybody has been measured.

        Args:
            reported: The model's account of why.

        Returns:
            Confirmation, and that there is nothing further to do.

        Raises:
            ToolFailedError: If anybody on the list has not been measured yet.
        """
        self._refuse_until_everybody_is_measured()
        self.gave_up = reported
        return "Recorded that there is no candidate. Nothing further is needed."

    def _refuse_until_everybody_is_measured(self) -> None:
        """Stop a run from ending on a list that was never worked through.

        Both terminal tools are conclusions about the whole list, and neither is worth anything
        drawn from part of it. The model is told who is missing rather than that something is
        missing, because that is the difference between a refusal it can act on and one it can
        only guess at.

        Raises:
            ToolFailedError: If anybody on the list has no distance recorded.
        """
        waiting = [person for person in self.survivors if _who(person.name, person.surname) not in self._distances]
        if not waiting:
            return
        named = ", ".join(f"{person.name} {person.surname}" for person in waiting)
        raise ToolFailedError(
            f"Nothing has been measured for {named} yet. Call get_survivor_sightings for them, "
            "then report — the answer is whoever turns out to be nearest, which cannot be known "
            "while somebody is unmeasured."
        )

    def _on_the_list(self, asked: SurvivorName) -> Suspect:
        """Find who was asked about, refusing anybody who is not on the list.

        Args:
            asked: The name the model used.

        Returns:
            That person's record.

        Raises:
            ToolFailedError: If the name is not one of the listed people.
        """
        for person in self.survivors:
            if _who(person.name, person.surname) == _who(asked.name, asked.surname):
                return person
        listed = ", ".join(f"{person.name} {person.surname}" for person in self.survivors)
        raise ToolFailedError(
            f"Nobody called {asked.name} {asked.surname} is on your list. The people on it are: {listed}. "
            "Spell the name exactly as it appears there."
        )

    async def _where_seen(self, person: Suspect) -> list[Coordinates]:
        """Fetch every place one person was seen.

        Args:
            person: Who to ask about.

        Returns:
            The coordinates, in the order the platform gave them.

        Raises:
            ToolFailedError: If the platform declines, or answers with something unreadable.
        """
        answered = await self._ask("location", AskAboutSightings(name=person.name, surname=person.surname))
        try:
            sightings = TypeAdapter(list[Sighting]).validate_json(answered)
        except ValidationError as unreadable:
            raise ToolFailedError(f"The sightings for {person.name} {person.surname} came back unreadable.") from (
                unreadable
            )
        return [Coordinates(seen.latitude, seen.longitude) for seen in sightings]

    async def _ask(self, endpoint: str, question: BaseModel) -> str:
        """Put one question to the platform, turning a refusal into something the model can use.

        A refusal from the platform explains itself in the body, and that sentence is better
        than anything invented here — it is the platform saying what it knows. Anything that is
        not a refusal, a lost connection above all, is not the model's to solve and travels on.

        What the platform said is somebody else's text, and our key travelled in the question it
        is answering, so a service that quotes the request back quotes the key with it. From
        here that sentence goes into the conversation, which means to the provider and into the
        recorded exchange on disk, where no redactor runs. Hence the key comes out first.

        Args:
            endpoint: Which endpoint to ask.
            question: What to ask, without the key.

        Returns:
            The answer as text.

        Raises:
            ToolFailedError: If the platform refused and said why.
        """
        try:
            return await self.platform.ask(endpoint, question)
        except HTTPError as refused:
            said = refused.body_preview or f"it answered with status {refused.status_code} and no explanation"
            raise ToolFailedError(
                f"The platform refused that question: {_without_our_key(said, self.platform.api_key)} "
                "Check the spelling against your list, or move on to the next person."
            ) from refused


def _without_our_key(said: str, api_key: SecretStr) -> str:
    """Take our key out of a sentence somebody else wrote.

    Args:
        said: What the platform answered.
        api_key: The key that travelled in the question it answers.

    Returns:
        The same sentence, redacted. An empty key is left alone: an empty needle matches
        between every pair of characters.
    """
    secret = api_key.get_secret_value()
    return said.replace(secret, _REDACTION_MARK) if secret else said


def _who(name: str, surname: str) -> tuple[str, str]:
    """Identify one person for lookup, ignoring how the name was capitalised.

    Args:
        name: Given name.
        surname: Family name.

    Returns:
        A key two spellings of the same person share.
    """
    return name.strip().casefold(), surname.strip().casefold()


def read_suspects(document: str) -> list[Suspect]:
    """Read the people a previous task submitted.

    Args:
        document: The stored answer, as JSON text.

    Returns:
        One entry per person, extra fields ignored.

    Raises:
        ValidationError: If the document is not a list of people with these three fields.
    """
    return TypeAdapter(list[Suspect]).validate_json(document)


async def place_the_sites(chat_model: ChatModel, sites: SiteList, instruction: Prompt) -> list[PlacedSite]:
    """Give every site the coordinates of the town it stands at.

    The platform's file names towns and never says where they are, so somebody has to. A model
    knows where a town is; this is knowledge rather than arithmetic, which is why it is the one
    thing here the model is asked for. Every distance it leads to is printed by the run, so a
    town put in the wrong place shows up as a margin that stops making sense.

    Args:
        chat_model: Who to ask.
        sites: The file as the platform wrote it.
        instruction: What the answer should look like, as a prompt.

    Returns:
        Every site, with its town's coordinates.

    Raises:
        SchemaViolationError: If the answer leaves a town unplaced — either by not naming it at
            all, or by saying it does not know where it is. Refusing to run beats measuring
            against a coordinate nobody stands behind: the failure would otherwise reappear as a
            distance, which looks like an answer.
    """
    towns = list(sites.power_plants)
    asked = f"{WHERE_THESE_TOWNS_ARE}\n\n" + "\n".join(towns)
    request = ChatRequest(
        [ChatMessage(Role.SYSTEM, instruction.text), ChatMessage(Role.USER, asked)],
        temperature=0.0,
        prompt_name=instruction.name,
    )
    located = await complete_as(chat_model, request, TownLocations)
    answered = {found.town: found for found in located.towns}

    logger = structlog.get_logger()
    placed: list[PlacedSite] = []
    for town, site in sites.power_plants.items():
        found = answered.get(town)
        if found is None:
            raise SchemaViolationError(TownLocations.__name__, f"the answer never mentions {town!r}")
        if found.latitude is None or found.longitude is None:
            raise SchemaViolationError(TownLocations.__name__, f"the model does not know where {town!r} is")
        try:
            at = Coordinates(found.latitude, found.longitude)
        except InvalidRequestError as off_the_earth:
            # The schema makes both fields nullable and cannot bound them: strict mode does not
            # read `minimum` and `maximum`, so a number outside the earth is caught only here.
            raise SchemaViolationError(TownLocations.__name__, f"{town!r} was placed nowhere: {off_the_earth}") from (
                off_the_earth
            )
        logger.info("site_located", site=town, code=site.code, latitude=at.latitude, longitude=at.longitude)
        placed.append(PlacedSite(town, site.code, site.is_active, at))
    return placed


async def solve(
    chat_model: ChatModel,
    platform: PlatformClient,
    answers_dir: Path,
    gazetteer: Prompt,
    investigator: Prompt,
    run_id: str,
) -> tuple[Answer, str]:
    """Find the person this task asks for, and submit them.

    Args:
        chat_model: Who to ask, both for the towns and for the investigating.
        platform: Where the data comes from and where the answer goes.
        answers_dir: Where the previous task left its answer.
        gazetteer: How to turn town names into coordinates.
        investigator: How to conduct the search.
        run_id: Which run this is, for a failure to point at the exchanges it left behind.

    Returns:
        What was submitted, and what the platform answered.

    Raises:
        AgentProducedNoAnswerError: If the loop ended without recording an answer.
        FileNotFoundError: If the previous task's answer is not on disk.
        InvalidRequestError: If the platform's file lists no sites, which leaves every distance
            in this task undefined.
    """
    stored = answers_dir / PREVIOUS_ANSWER
    if not stored.is_file():
        raise FileNotFoundError(f"{stored} is missing; run `piglet task run people` first, which writes it")

    survivors = read_suspects(stored.read_text(encoding="utf-8"))
    sites = SiteList.model_validate_json(await platform.download(SITES_FILE))
    if not sites.power_plants:
        raise InvalidRequestError(f"{SITES_FILE} lists no sites, so there is nothing to measure anybody against")
    investigation = Investigation(platform, await place_the_sites(chat_model, sites, gazetteer), survivors)

    listed = "\n".join(f"- {person.name} {person.surname}" for person in survivors)
    request = ChatRequest(
        [
            ChatMessage(Role.SYSTEM, investigator.text),
            ChatMessage(Role.USER, f"The people to investigate:\n{listed}"),
        ],
        prompt_name=investigator.name,
    )
    steps = len(survivors) + STEPS_BESIDES_THE_PEOPLE
    finished = await run_agent(chat_model, investigation.as_registry(), request, steps)

    if investigation.finding is None:
        gave_up = investigation.gave_up
        raise AgentProducedNoAnswerError(
            finished.stop_reason,
            finished.steps_taken,
            run_id,
            account=gave_up.reasoning if gave_up is not None else None,
        )

    found = investigation.finding
    answer = Answer(
        name=found.name, surname=found.surname, access_level=found.access_level, power_plant=found.site_code
    )
    return answer, await platform.submit(TASK_NAME, answer)
