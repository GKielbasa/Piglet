import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from piglet.adapters.logging.setup import configure_logging
from piglet.agent.loop import StopReason, run_agent
from piglet.domain.llm.chat import (
    ChatCompletion,
    ChatMessage,
    ChatRequest,
    FinishReason,
    Role,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from piglet.errors import InvalidRequestError, ToolFailedError
from piglet.tools.registry import ToolRegistry, define_tool


class TownName(BaseModel):
    """Which town to look up."""

    town: str = Field(description="The town's name, as written.")


class ScriptedModel:
    """Answers from a script, and remembers everything it was asked."""

    def __init__(self, *answers: ChatCompletion) -> None:
        self.scripted = list(answers)
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        self.requests.append(request)
        return self.scripted.pop(0) if len(self.scripted) > 1 else self.scripted[0]


def said(text: str) -> ChatCompletion:
    return ChatCompletion(text, "test/model", FinishReason.STOP, TokenUsage(11, 2))


def asked_for(*calls: ToolCall) -> ChatCompletion:
    return ChatCompletion("", "test/model", FinishReason.TOOL_CALLS, TokenUsage(11, 2), tool_calls=calls)


def call(name: str, town: str = "Zabrze", call_id: str = "call_1") -> ToolCall:
    return ToolCall(call_id, name, json.dumps({"town": town}))


ASKED = ChatRequest([ChatMessage(Role.USER, "Where is Zabrze?")])


def build_registry(order: list[str] | None = None) -> ToolRegistry:
    async def locate(arguments: TownName) -> str:
        if order is not None:
            order.append(arguments.town)
        return f"{arguments.town} is at 50.3143, 18.7816."

    async def finish(arguments: TownName) -> str:
        if order is not None:
            order.append(f"finish:{arguments.town}")
        return "Recorded. Nothing further is needed."

    async def refuse(arguments: TownName) -> str:
        raise ToolFailedError("That is not something I can record. Look the town up first.")

    return ToolRegistry(
        [
            define_tool("locate_town", "Where a town is.", TownName, locate),
            define_tool("report_finding", "Report and finish.", TownName, finish, ends_the_run=True),
            define_tool("report_or_refuse", "Reports, or refuses.", TownName, refuse, ends_the_run=True),
        ]
    )


def run_entries(log_dir: Path) -> list[dict[str, Any]]:
    log_file = log_dir / f"{date.today().isoformat()}.jsonl"
    entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    return [entry for entry in entries if entry["event"] == "agent_run_finished"]


async def test_a_model_that_answers_without_tool_calls_ends_the_run() -> None:
    finished = await run_agent(ScriptedModel(said("It is in Silesia.")), build_registry(), ASKED)

    assert finished.stop_reason is StopReason.ANSWERED
    assert finished.final_text == "It is in Silesia."


async def test_a_tool_call_is_executed_and_its_result_handed_back_naming_the_call() -> None:
    model = ScriptedModel(asked_for(call("locate_town")), said("Silesia, then."))

    finished = await run_agent(model, build_registry(), ASKED)

    result = finished.conversation[2]
    assert result.role is Role.TOOL
    assert result.tool_call_id == "call_1"
    assert result.content == "Zabrze is at 50.3143, 18.7816."


async def test_the_conversation_keeps_every_turn_in_order() -> None:
    model = ScriptedModel(asked_for(call("locate_town")), said("Silesia, then."))

    finished = await run_agent(model, build_registry(), ASKED)

    assert [turn.role for turn in finished.conversation] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]


async def test_whatever_tools_the_request_carried_are_replaced_by_the_registrys() -> None:
    model = ScriptedModel(said("Nothing to do."))
    stale = ToolDefinition("a_tool_that_went_away", "Gone.", {"type": "object"})

    await run_agent(model, build_registry(), ChatRequest(ASKED.messages, tools=[stale]))

    assert [one.name for one in model.requests[0].tools] == ["locate_town", "report_finding", "report_or_refuse"]


async def test_the_tools_travel_with_every_request_not_only_the_first() -> None:
    model = ScriptedModel(asked_for(call("locate_town")), said("Silesia, then."))

    await run_agent(model, build_registry(), ASKED)

    assert len(model.requests) == 2
    assert all(len(request.tools) == 3 for request in model.requests)


async def test_several_calls_in_one_turn_are_executed_in_the_order_the_model_emitted_them() -> None:
    order: list[str] = []
    turn = asked_for(
        call("locate_town", "Tczew", "call_1"),
        call("locate_town", "Radom", "call_2"),
        call("locate_town", "Zabrze", "call_3"),
    )

    await run_agent(ScriptedModel(turn, said("Done.")), build_registry(order), ASKED)

    assert order == ["Tczew", "Radom", "Zabrze"]


async def test_a_successful_terminal_tool_ends_the_run() -> None:
    model = ScriptedModel(asked_for(call("report_finding")), said("never reached"))

    finished = await run_agent(model, build_registry(), ASKED)

    assert finished.stop_reason is StopReason.FINISHED_BY_TOOL
    assert len(model.requests) == 1


async def test_calls_queued_behind_a_terminal_one_are_not_executed() -> None:
    order: list[str] = []
    turn = asked_for(
        call("locate_town", "Tczew", "call_1"),
        call("report_finding", "Tczew", "call_2"),
        call("locate_town", "Radom", "call_3"),
    )

    await run_agent(ScriptedModel(turn, said("never reached")), build_registry(order), ASKED)

    assert order == ["Tczew", "finish:Tczew"]


async def test_a_terminal_tool_that_failed_leaves_the_run_going() -> None:
    model = ScriptedModel(asked_for(call("report_or_refuse")), said("I will look it up first."))

    finished = await run_agent(model, build_registry(), ASKED)

    assert finished.stop_reason is StopReason.ANSWERED
    assert finished.steps_taken == 2


async def test_a_step_is_one_model_call_not_one_tool_execution() -> None:
    turn = asked_for(
        call("locate_town", "Tczew", "call_1"),
        call("locate_town", "Radom", "call_2"),
        call("locate_town", "Zabrze", "call_3"),
    )

    finished = await run_agent(ScriptedModel(turn, said("Done.")), build_registry(), ASKED)

    assert finished.steps_taken == 2


async def test_a_run_that_never_stops_is_cut_off_at_the_budget() -> None:
    forever = ScriptedModel(asked_for(call("locate_town")))

    finished = await run_agent(forever, build_registry(), ASKED, max_steps=4)

    assert finished.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert finished.steps_taken == 4
    assert len(forever.requests) == 4


async def test_a_cut_off_run_hands_back_everything_it_collected() -> None:
    finished = await run_agent(ScriptedModel(asked_for(call("locate_town"))), build_registry(), ASKED, max_steps=3)

    assert [turn.role for turn in finished.conversation].count(Role.TOOL) == 3


async def test_nothing_is_raised_when_the_budget_runs_out() -> None:
    finished = await run_agent(ScriptedModel(asked_for(call("locate_town"))), build_registry(), ASKED, max_steps=1)

    assert finished.stop_reason is StopReason.BUDGET_EXHAUSTED


async def test_a_budget_of_nothing_is_refused() -> None:
    with pytest.raises(InvalidRequestError, match="at least one step"):
        await run_agent(ScriptedModel(said("Hi.")), build_registry(), ASKED, max_steps=0)


async def test_the_run_reports_how_many_model_calls_it_took() -> None:
    model = ScriptedModel(asked_for(call("locate_town")), asked_for(call("locate_town", "Tczew")), said("Done."))

    finished = await run_agent(model, build_registry(), ASKED)

    assert finished.steps_taken == 3


async def test_a_finished_run_leaves_one_entry_naming_how_it_went(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    model = ScriptedModel(asked_for(call("locate_town")), said("Done."))

    await run_agent(model, build_registry(), ASKED)

    entries = run_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["steps_taken"] == 2
    assert entries[0]["stop_reason"] == "answered"
    assert entries[0]["tool_calls"] == 1
