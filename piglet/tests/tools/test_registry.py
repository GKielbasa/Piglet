import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, Field

from piglet.adapters.logging.setup import configure_logging
from piglet.domain.http.service_profile import FailureClass
from piglet.domain.llm.chat import ToolCall
from piglet.errors import InvalidRequestError, ToolFailedError, TransportError
from piglet.tools.registry import ToolRegistry, ToolResult, define_tool


class TownName(BaseModel):
    """Which town to look up."""

    town: str = Field(description="The town's name, as written.")


async def locate(arguments: TownName) -> str:
    return f"{arguments.town} is at 50.3143, 18.7816."


async def refuse(arguments: TownName) -> str:
    raise ToolFailedError(f"No town called {arguments.town!r} is on the map. The ones that are: Zabrze, Tczew.")


async def lose_the_network(arguments: TownName) -> str:
    raise TransportError("https://nowhere.example", OSError("no route to host"), FailureClass.TRANSIENT)


LOCATE = define_tool("locate_town", "Where a town is, in degrees.", TownName, locate)
REPORT = define_tool("report_finding", "Report the answer and finish.", TownName, locate, ends_the_run=True)
REFUSING = define_tool("refusing_town", "Refuses whatever it is given.", TownName, refuse)
REFUSING_TERMINAL = define_tool("report_or_refuse", "Reports, or refuses.", TownName, refuse, ends_the_run=True)
BROKEN = define_tool("broken_town", "Loses the network.", TownName, lose_the_network)

ASKING_FOR_ZABRZE = ToolCall("call_1", "locate_town", '{"town": "Zabrze"}')


def log_file(log_dir: Path) -> Path:
    return log_dir / f"{date.today().isoformat()}.jsonl"


def tool_entries(log_dir: Path) -> list[dict[str, Any]]:
    entries = [json.loads(line) for line in log_file(log_dir).read_text(encoding="utf-8").splitlines()]
    return [entry for entry in entries if entry["event"] == "tool_call_finished"]


def test_a_result_carries_the_text_the_model_will_read_and_whether_it_is_a_failure() -> None:
    result = ToolResult("No such town.", is_error=True)

    assert (result.content, result.is_error) == ("No such town.", True)


def test_a_tool_is_declared_with_a_name_a_description_and_a_model_for_its_arguments() -> None:
    assert (LOCATE.name, LOCATE.description, LOCATE.arguments) == (
        "locate_town",
        "Where a town is, in degrees.",
        TownName,
    )


def test_a_tool_does_not_end_the_run_unless_it_says_so() -> None:
    assert LOCATE.ends_the_run is False
    assert REPORT.ends_the_run is True


def test_every_registered_tool_appears_as_a_definition_the_model_can_read() -> None:
    definitions = ToolRegistry([LOCATE, REPORT]).definitions

    assert [(one.name, one.description) for one in definitions] == [
        ("locate_town", "Where a town is, in degrees."),
        ("report_finding", "Report the answer and finish."),
    ]


def test_the_argument_schema_is_the_strict_dialect_a_provider_enforces() -> None:
    schema = cast("dict[str, Any]", ToolRegistry([LOCATE]).definitions[0].parameters)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["town"]
    assert schema["properties"]["town"]["description"] == "The town's name, as written."


def test_the_definitions_keep_the_order_the_tools_were_given() -> None:
    assert [one.name for one in ToolRegistry([REPORT, LOCATE]).definitions] == ["report_finding", "locate_town"]


async def test_a_call_reaches_its_tool_with_the_arguments_parsed_into_its_own_model() -> None:
    seen: list[TownName] = []

    async def remember(arguments: TownName) -> str:
        seen.append(arguments)
        return "noted"

    registry = ToolRegistry([define_tool("remember_town", "Remember it.", TownName, remember)])

    await registry.execute(ToolCall("call_1", "remember_town", '{"town": "Zabrze"}'))

    assert seen == [TownName(town="Zabrze")]


async def test_what_the_tool_returned_is_what_the_model_will_read() -> None:
    result = await ToolRegistry([LOCATE]).execute(ASKING_FOR_ZABRZE)

    assert result.content == "Zabrze is at 50.3143, 18.7816."
    assert result.is_error is False


async def test_a_successful_call_to_a_terminal_tool_ends_the_run() -> None:
    result = await ToolRegistry([REPORT]).execute(ToolCall("call_1", "report_finding", '{"town": "Zabrze"}'))

    assert result.ends_the_run is True


async def test_a_call_naming_a_tool_nobody_registered_lists_the_tools_that_exist() -> None:
    result = await ToolRegistry([LOCATE, REPORT]).execute(ToolCall("call_1", "locate_plant", "{}"))

    assert result.is_error is True
    assert "locate_plant" in result.content
    assert "locate_town, report_finding" in result.content


async def test_arguments_that_do_not_fit_the_schema_say_which_field_and_why() -> None:
    result = await ToolRegistry([LOCATE]).execute(ToolCall("call_1", "locate_town", '{"village": "Zabrze"}'))

    assert result.is_error is True
    assert "town: Field required" in result.content
    assert "Call it again" in result.content


async def test_arguments_that_are_not_json_at_all_come_back_as_an_error() -> None:
    result = await ToolRegistry([LOCATE]).execute(ToolCall("call_1", "locate_town", "Zabrze"))

    assert result.is_error is True
    assert "the arguments as a whole" in result.content


async def test_a_tool_that_refuses_comes_back_carrying_the_message_it_refused_with() -> None:
    result = await ToolRegistry([REFUSING]).execute(ToolCall("call_1", "refusing_town", '{"town": "Atlantis"}'))

    assert result.is_error is True
    assert result.content == "No town called 'Atlantis' is on the map. The ones that are: Zabrze, Tczew."


async def test_a_terminal_tool_that_failed_does_not_end_the_run() -> None:
    result = await ToolRegistry([REFUSING_TERMINAL]).execute(ToolCall("call_1", "report_or_refuse", '{"town": "X"}'))

    assert result.is_error is True
    assert result.ends_the_run is False


async def test_any_other_failure_travels_through_untouched() -> None:
    with pytest.raises(TransportError):
        await ToolRegistry([BROKEN]).execute(ToolCall("call_1", "broken_town", '{"town": "Zabrze"}'))


async def test_every_execution_leaves_one_entry_naming_the_tool_and_how_it_went(tmp_path: Path) -> None:
    configure_logging(tmp_path)

    await ToolRegistry([REFUSING]).execute(ToolCall("call_1", "refusing_town", '{"town": "Atlantis"}'))

    entries = tool_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["tool"] == "refusing_town"
    assert entries[0]["is_error"] is True
    assert entries[0]["duration_ms"] >= 0


async def test_a_tool_that_crashed_still_leaves_an_entry_naming_it(tmp_path: Path) -> None:
    configure_logging(tmp_path)

    with pytest.raises(TransportError):
        await ToolRegistry([BROKEN]).execute(ToolCall("call_1", "broken_town", '{"town": "Zabrze"}'))

    entries = tool_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["tool"] == "broken_town"
    assert entries[0]["is_error"] is True
    assert entries[0]["duration_ms"] >= 0


def test_two_tools_under_one_name_are_refused_when_the_registry_is_built() -> None:
    with pytest.raises(InvalidRequestError, match="locate_town"):
        ToolRegistry([LOCATE, define_tool("locate_town", "Something else entirely.", TownName, locate)])


async def test_the_arguments_never_reach_the_log(tmp_path: Path) -> None:
    configure_logging(tmp_path)

    await ToolRegistry([LOCATE]).execute(ASKING_FOR_ZABRZE)

    assert "Zabrze" not in log_file(tmp_path).read_text(encoding="utf-8")
