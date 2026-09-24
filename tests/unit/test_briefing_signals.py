"""Exercise code briefing branches through ADK's real runner without any model calls."""
import json
import threading
from functools import wraps

import pytest
from google.adk.agents import BaseAgent, ParallelAgent, SequentialAgent
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.cymbal_store_ops.sub_agents.briefing_signals import BriefingSignals

MANAGER = {"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"}


def branch(area):
    return BriefingSignals(name=f"briefing_{area}", area=area, output_key=f"temp:briefing_{area}")


class StateProbe(BaseAgent):
    """Read the exact state a downstream plan writer would receive in the same invocation."""

    async def _run_async_impl(self, ctx):
        values = {key: value for key, value in ctx.session.state.items() if key.startswith("temp:briefing_")}
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    content=types.Content(role="model", parts=[types.Part(text=json.dumps(values))]))


async def run(agent, state=None):
    sequence = SequentialAgent(name="briefing_test", sub_agents=[agent, StateProbe(name="state_probe")])
    runner = InMemoryRunner(agent=sequence, app_name="briefing_test")
    try:
        session = await runner.session_service.create_session(app_name="briefing_test", user_id="test", state=state or {})
        return [event async for event in runner.run_async(user_id="test", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Opening priorities")]))]
    finally:
        await runner.close()


def tool_events(events):
    calls, responses = [], []
    for event in events:
        for part in (event.content.parts if event.content else []) or []:
            if part.function_call:
                calls.append(part.function_call)
            if part.function_response:
                responses.append(part.function_response)
    return calls, responses


def outputs(events):
    # ADK removes temp deltas from emitted/persisted events, but preserves them for the next
    # agent in a sequence. Probe that actual consumer boundary rather than asserting persistence.
    probe = next(event for event in events if event.author == "state_probe")
    state = json.loads(probe.content.parts[0].text)
    return {key: json.loads(value) for key, value in state.items() if key.startswith("temp:briefing_")}


@pytest.mark.asyncio
async def test_inventory_branch_emits_correlated_actual_reads_and_exact_allocation_state(fake_backend):
    events = await run(branch("inventory"), MANAGER)
    calls, responses = tool_events(events)
    assert [call.name for call in calls] == ["get_osa_exceptions", "get_bopis_demand", "get_task_status",
                                           "get_merchandising_work", "get_inventory_context"]
    assert len({call.id for call in calls}) == len(calls) == len(responses)
    assert {call.id: call.name for call in calls} == {response.id: response.name for response in responses}
    assert calls[-1].args == {"product_name": "P-0101"}
    assert {event.author for event in events} == {"briefing_inventory", "state_probe"}
    state = outputs(events)["temp:briefing_inventory"]
    demand = next(p for p in state["get_bopis_demand"]["by_product"] if p["product_id"] == "P-0101")
    assert demand["orders"] == 3 and demand["units"] == 4
    assert "09:30" in demand["earliest_promise"] and "10:00" in demand["latest_promise"]
    decision = state["get_inventory_context"]["rows"][0]["decision"]
    assert decision["reserved_units"] == 4 and decision["available_to_promise_units"] == 3
    assert decision["action"] == "pick_reserved_then_replenish"
    # The async composite completed and produced data, rather than a serialized coroutine object.
    assert "coroutine" not in json.dumps(state)


@pytest.mark.asyncio
async def test_unsigned_branches_emit_errors_without_backend_access(fake_backend):
    agent = ParallelAgent(name="signals", sub_agents=[branch(area) for area in ("inventory", "coverage", "shrink")])
    events = await run(agent)
    calls, responses = tool_events(events)
    assert calls and len(calls) == len(responses)
    assert all(response.response["status"] == "ERROR" for response in responses)
    assert fake_backend.calls == []
    assert set(outputs(events)) == {"temp:briefing_inventory", "temp:briefing_coverage", "temp:briefing_shrink"}
    assert all(result["status"] == "ERROR" for area in outputs(events).values() for result in area.values())


@pytest.mark.asyncio
async def test_role_guard_blocks_loss_case_read_for_associate(fake_backend):
    events = await run(branch("shrink"), {**MANAGER, "user:user_id": "A-1004", "user:role": "associate"})
    state = outputs(events)["temp:briefing_shrink"]
    assert state["get_shrink_signals"]["status"] == "ERROR"
    assert "manager role" in state["get_shrink_signals"]["error_details"]
    assert "get_loss_controls" not in state and "get_task_history" not in state
    assert fake_backend.calls == []


@pytest.mark.asyncio
async def test_code_branch_backend_reads_are_concurrent(fake_backend, monkeypatch):
    barrier = threading.Barrier(4)

    def synchronized(read):
        first = True
        lock = threading.Lock()

        @wraps(read)
        def wrapped(*args, **kwargs):
            nonlocal first
            with lock:
                wait = first
                first = False
            if wait:
                barrier.wait(timeout=5)
            return read(*args, **kwargs)
        return wrapped

    for name in ("get_traffic_and_backlog", "get_shift_roster", "get_guest_feedback", "get_operations_context"):
        monkeypatch.setattr(fake_backend, name, synchronized(getattr(fake_backend, name)))
    events = await run(branch("coverage"), MANAGER)
    output = outputs(events)["temp:briefing_coverage"]
    assert all(result["status"] == "SUCCESS" for result in output.values())
    workload = output["get_pickup_workload"]["rows"][0]
    assert workload["pending_order_count"] == 9 and workload["estimated_minutes"] == 54
    assert workload["orders_due_at_first_promise"] == 1 and not workload["whole_queue_can_finish_by_first_promise"]


@pytest.mark.asyncio
async def test_failed_read_is_preserved_and_dependent_read_is_not_invented(fake_backend, monkeypatch):
    failure = {"status": "ERROR", "error_details": "Inventory feed unavailable", "code": "source_unavailable"}
    monkeypatch.setattr(fake_backend, "get_osa_exceptions", lambda **kwargs: dict(failure))
    events = await run(branch("inventory"), MANAGER)
    state = outputs(events)["temp:briefing_inventory"]
    assert state["get_osa_exceptions"] == failure
    assert "get_inventory_context" not in state
    assert state["get_bopis_demand"]["pending_count"] == 9
    calls, _ = tool_events(events)
    assert "get_inventory_context" not in [call.name for call in calls]


@pytest.mark.asyncio
async def test_parallel_branches_keep_separate_state_and_unique_call_ids(fake_backend, monkeypatch):
    barrier = threading.Barrier(3)

    def synchronized(read):
        @wraps(read)
        def wrapped(*args, **kwargs):
            barrier.wait(timeout=5)
            return read(*args, **kwargs)
        return wrapped

    # One read from each branch must enter before any of these reads can complete.
    for name in ("get_osa_exceptions", "get_traffic_and_backlog", "get_shrink_signals"):
        monkeypatch.setattr(fake_backend, name, synchronized(getattr(fake_backend, name)))
    agent = ParallelAgent(name="signals", sub_agents=[branch(area) for area in ("inventory", "coverage", "shrink")])
    events = await run(agent, MANAGER)
    calls, responses = tool_events(events)
    assert len({call.id for call in calls}) == len(calls)
    assert {call.id for call in calls} == {response.id for response in responses}
    state = outputs(events)
    assert set(state) == {"temp:briefing_inventory", "temp:briefing_coverage", "temp:briefing_shrink"}
    assert state["temp:briefing_inventory"]["get_inventory_context"]["rows"][0]["decision"]["reserved_units"] == 4
    assert "get_shift_roster" in state["temp:briefing_coverage"]
    shrink = state["temp:briefing_shrink"]["get_shrink_signals"]
    assert shrink["products"] == next(response.response["products"] for response in responses
                                      if response.name == "get_shrink_signals")
    assert all(r["product_id"] in {p["product_id"] for p in shrink["products"]} for r in shrink["rows"])


@pytest.mark.asyncio
async def test_failed_demand_read_never_becomes_zero_demand_or_a_pick_recommendation(fake_backend, monkeypatch):
    failure = {"status": "ERROR", "error_details": "Orders feed unavailable", "code": "source_unavailable"}
    monkeypatch.setattr(fake_backend, "get_bopis_demand", lambda **kwargs: dict(failure))
    state = outputs(await run(branch("inventory"), MANAGER))["temp:briefing_inventory"]
    assert state["get_bopis_demand"] == failure
    assert "pending_count" not in state["get_bopis_demand"]
    assert state["get_inventory_context"]["status"] == "ERROR"
    assert state["get_inventory_context"]["failed_source"] == "demand"
    assert "rows" not in state["get_inventory_context"]
