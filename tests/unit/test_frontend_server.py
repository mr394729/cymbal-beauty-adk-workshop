"""The frontend's CLI: where it binds, and why.

A Cloud Run container is reached from outside itself, so a server bound to loopback answers nothing and the
service fails its health check with no error of its own. PORT being set is the signal that a host is in front."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _parser(monkeypatch: pytest.MonkeyPatch, port: str | None):
    monkeypatch.delenv("PORT", raising=False)
    if port is not None:
        monkeypatch.setenv("PORT", port)
    server = importlib.reload(importlib.import_module("frontend.server"))
    return server.build_parser()


def test_a_local_run_stays_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _parser(monkeypatch, None).parse_args([])
    assert (a.host, a.port) == ("127.0.0.1", 8080)


def test_a_host_that_sets_port_gets_every_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _parser(monkeypatch, "9090").parse_args([])
    assert (a.host, a.port) == ("0.0.0.0", 9090)  # noqa: S104


def test_the_flags_still_win(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _parser(monkeypatch, "9090").parse_args(["--host", "127.0.0.1", "--port", "1234"])
    assert (a.host, a.port) == ("127.0.0.1", 1234)


def event(author, text=None, **fields):
    return {"author": author, "content": {"parts": [{"text": text}] if text else []}, **fields}


def tool_event(name, call_id, response=None):
    part = {"function_call": {"name": name, "id": call_id, "args": {}}} if response is None else {
        "function_response": {"name": name, "id": call_id, "response": response}}
    return event("store_manager_agent", content={"parts": [part]})


async def collect(events):
    from frontend.server import sse

    async def source():
        for item in events:
            if isinstance(item, Exception):
                raise item
            yield item

    return [json.loads(frame.decode().removeprefix("data: ")) async for frame in sse(source())]


@pytest.mark.parametrize("specialist", ["inventory_excellence", "associate_development", "store_tasks"])
async def test_only_final_coordinator_answer_reaches_chat(specialist):
    output = await collect([
        event("store_manager_agent", "Checking that now."),
        tool_event(specialist, "agent-1"),
        event(specialist, "Specialist working result"),
        tool_event(specialist, "agent-1", {"result": "Working result"}),
        event("store_manager_agent", "Use bay B2 for the four reserved units."),
    ])
    assert [i["text"] for i in output if i["type"] == "text"] == ["Use bay B2 for the four reserved units."]
    assert [i["type"] for i in output].count("tool_call") == 1
    assert any(i.get("text") == "Specialist working result" and i["type"] == "agent_note" for i in output)


@pytest.mark.parametrize("first,last", [("store_manager_agent", "associate_development"), ("associate_development", "store_manager_agent")])
async def test_handoff_preserves_one_answer_from_receiving_chat_agent(first, last):
    output = await collect([
        event(first, "Handing over."), event(first, actions={"transfer_to_agent": last}),
        event(last, content={"parts": [{"text": "One useful answer."}, {"text": "With its evidence."}]}),
    ])
    assert [i["text"] for i in output if i["type"] == "text"] == ["One useful answer.\nWith its evidence."]
    assert any(i["type"] == "transfer" for i in output)


async def test_partial_thought_and_replayed_events_do_not_duplicate_messages():
    complete = event("store_manager_agent", id="answer-1", content={"parts": [
        {"text": "Private reasoning", "thought": True}, {"text": "Ready at 9:30 a.m."}]})
    output = await collect([
        event("store_manager_agent", "Ready", id="answer-1", partial=True), complete, complete,
    ])
    assert [i["text"] for i in output if i["type"] == "text"] == ["Ready at 9:30 a.m."]
    assert "Private reasoning" not in json.dumps(output)


async def test_confirmation_streams_before_generator_finishes_and_suppresses_task_preamble():
    from frontend.server import sse
    confirmation = event("store_tasks", long_running_tool_ids=["approve-1"], invocation_id="inv-1", content={"parts": [{
        "function_call": {"id": "approve-1", "name": "adk_request_confirmation", "args": {
            "originalFunctionCall": {"name": "create_store_task", "args": {"note": "Pick four units"}}}}}]})
    progressed = False

    async def source():
        nonlocal progressed
        yield confirmation
        progressed = True
        yield event("store_tasks", "Waiting for your approval.")

    stream = sse(source())
    first = json.loads((await anext(stream)).decode().removeprefix("data: "))
    assert first["type"] == "confirmation" and first["fc_id"] == "approve-1"
    assert not progressed
    rest = [json.loads(frame.decode().removeprefix("data: ")) async for frame in stream]
    assert not any(i["type"] == "text" for i in rest)


async def test_task_completion_without_root_reply_survives_handback():
    output = await collect([
        tool_event("create_store_task", "write-1", {"status": "SUCCESS"}),
        event("store_tasks", "Created the pickup task for Priya."),
        event("store_tasks", actions={"transfer_to_agent": "store_manager_agent"}),
    ])
    assert [i["text"] for i in output if i["type"] == "text"] == ["Created the pickup task for Priya."]


@pytest.mark.parametrize("failure", [RuntimeError("engine unavailable"), event("store_manager_agent", error_message="engine unavailable")])
async def test_failed_stream_does_not_publish_an_unfinished_answer(failure):
    output = await collect([event("store_manager_agent", "I will check."), failure])
    assert not any(i["type"] == "text" for i in output)
    assert output[-2]["type"] == "error"
    assert output[-1]["type"] == "done"


async def test_same_tool_concurrent_calls_keep_ids_and_results():
    output = await collect([
        tool_event("check_store_stock", "stock-1"), tool_event("check_store_stock", "stock-2"),
        tool_event("check_store_stock", "stock-2", {"units": 3}),
        tool_event("check_store_stock", "stock-1", {"units": 7}),
    ])
    assert [(i["call_id"], i["data"]["units"]) for i in output if i["type"] == "tool_result"] == [("stock-2", 3), ("stock-1", 7)]


def test_trace_shaping_separates_execution_from_session_state_and_hides_thoughts():
    from frontend.server import shape
    spans = [{"id": "tool-1", "parent_id": "agent-1", "invocation_id": "nested-1", "agent": "briefing_inventory",
              "name": "get_osa_exceptions", "kind": "tool", "start_ms": 1000, "duration_ms": 20, "status": "ok",
              "input": {"limit": 2}, "output": {"parts": [{"text": "Private reasoning", "thought": True}, {"text": "Stock result"}], "thought_signature": "secret"},
              "unexpected": "not part of trace contract"}]
    result = shape(event("daily_briefing", actions={"state_delta": {
        "ui:trace:briefing_inventory": {"invocation_id": "nested-1", "root_invocation_id": "root-1", "spans": spans},
        "ui:next_actions": [], "_private": "hidden"}}))
    trace = next(i for i in result if i["type"] == "trace")
    assert trace["invocation_id"] == "nested-1"
    assert trace["root_invocation_id"] == "root-1"
    assert trace["spans"][0]["parent_id"] == "agent-1"
    assert trace["spans"][0]["output"] == {"parts": [{"text": "Stock result"}]}
    assert "Private reasoning" not in json.dumps(result)
    assert "secret" not in json.dumps(result)
    assert next(i for i in result if i["type"] == "state")["delta"] == {"ui:next_actions": []}


def test_trace_shaping_rejects_malformed_spans_and_bounds_payloads():
    from frontend.server import shape_trace
    assert shape_trace("ui:trace:test", {"spans": "bad"}) is None
    trace = shape_trace("ui:trace:test", [{"id": "valid", "kind": "tool", "output": "x" * 15000},
                                        {"kind": "tool"}, {"id": "thought", "kind": "reasoning"}, None])
    assert len(trace["spans"]) == 1
    assert trace["spans"][0]["output"].endswith("[truncated]")
    assert len(trace["spans"][0]["output"]) < 12100


async def test_trace_is_delivered_immediately_including_failed_execution():
    from frontend.server import sse
    progressed = False
    running = event("daily_briefing", actions={"state_delta": {"ui:trace:briefing_inventory": {
        "invocation_id": "nested-1", "spans": [{"id": "read-1", "kind": "tool", "status": "running", "duration_ms": None}]}}})

    async def source():
        nonlocal progressed
        yield running
        progressed = True
        yield event("daily_briefing", error_message="Lookup failed", actions={"state_delta": {
            "ui:trace:briefing_inventory": {"spans": [{"id": "read-1", "kind": "tool", "status": "error", "duration_ms": 45}]}}})

    stream = sse(source())
    first = json.loads((await anext(stream)).decode().removeprefix("data: "))
    assert first["type"] == "trace" and not progressed
    rest = [json.loads(frame.decode().removeprefix("data: ")) async for frame in stream]
    assert [item["type"] for item in rest] == ["trace", "error", "done"]
    assert rest[0]["spans"][0]["status"] == "error"
