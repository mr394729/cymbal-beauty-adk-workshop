"""Concise writer inputs retain changed facts and full source events."""
import json
from copy import deepcopy
from functools import wraps

import pytest

from agents.cymbal_store_ops.sub_agents.briefing_facts import (
    project_briefing_facts,
    project_tool_result,
)
from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.inventory_context import get_inventory_context
from agents.cymbal_store_ops.tools.pickup_workload import get_pickup_workload
from tests.conftest import FakeToolContext
from tests.unit.test_briefing_signals import MANAGER, branch, outputs, run, tool_events


def context():
    return FakeToolContext(dict(MANAGER))


@pytest.mark.asyncio
async def test_projection_preserves_full_trace_but_reduces_writer_payload(fake_backend):
    events = await run(branch("inventory"), MANAGER)
    _, responses = tool_events(events)
    full = {response.name: response.response for response in responses}
    facts = outputs(events)["temp:briefing_inventory"]
    assert facts == project_briefing_facts("inventory", full)
    assert "store_name" in full["get_inventory_context"]["rows"][0]["stock"]
    assert "store_name" not in facts["get_inventory_context"]["rows"][0]["stock"]
    assert len(json.dumps(facts)) < len(json.dumps(full)) * .8
    demand = facts["get_bopis_demand"]
    assert "rows" not in demand and len(full["get_bopis_demand"]["rows"]) == 9
    hero = next(product for product in demand["by_product"] if product["product_id"] == "P-0101")
    assert (hero["orders"], hero["units"]) == (3, 4)
    assert "09:30" in hero["earliest_promise"] and "10:00" in hero["latest_promise"]


def test_changed_and_incomplete_demand_is_never_hidden(fake_backend):
    source = domain.get_bopis_demand(tool_context=context())
    before = deepcopy(source)
    changed = deepcopy(source)
    changed["by_product"][0]["orders"] += 1
    assert project_tool_result("get_bopis_demand", changed)["rows"] == changed["rows"]
    changed = deepcopy(source)
    changed["rows"][0]["stock_blocker"] = "Selected bin empty"
    assert project_tool_result("get_bopis_demand", changed)["rows"][0]["stock_blocker"] == "Selected bin empty"
    for key in ("by_product_complete",):
        changed = deepcopy(source)
        changed[key] = False
        assert project_tool_result("get_bopis_demand", changed)["rows"] == source["rows"]
    changed = deepcopy(source)
    changed["by_product"][0]["promise_times_complete"] = False
    assert "rows" in project_tool_result("get_bopis_demand", changed)
    assert source == before


@pytest.mark.asyncio
async def test_allocation_discrepancy_and_source_errors_survive(fake_backend):
    value = await get_inventory_context("P-0101", context())
    row = value["rows"][0]
    row["allocation"]["last_failed_pick"] = {"order_id": "BO-000651", "reason": "Bin empty"}
    row["decision"].update(action="resolve_stock_discrepancy", physical_check_needed=True,
                           reasons=["failed_pick_requires_reconciliation"], available_to_promise_units=None)
    row["open_tasks"] = [{"task_id": "T-CHANGED", "assignee_id": "A-1000", "assignee_name": "Jordan",
        "due_at": "2026-10-03T13:00:00-05:00", "note": "Report discrepancy before 9:30", "status": "open"}]
    result = project_tool_result("get_inventory_context", value)["rows"][0]
    assert result["allocation"] == row["allocation"]
    assert result["location"] == row["location"]
    assert result["decision"] == row["decision"]
    assert result["open_tasks"] == row["open_tasks"]
    assert result["inbound"][0]["status"] == "delayed"
    error = {"status": "ERROR", "code": "source_unavailable", "failed_source": "allocation", "details": {"freshness": "unknown"}}
    assert project_tool_result("get_inventory_context", error) == error


def test_roster_keeps_candidate_conflicts_and_all_tasks(fake_backend):
    source = domain.get_shift_roster(tool_context=context())
    source["candidates"][0]["shift_end"] = "2026-10-03T10:00:00-05:00"
    source["candidates"].append({"associate_id": "A-UNLISTED", "first_name": "New person", "skills": ["bopis"]})
    result = project_tool_result("get_shift_roster", source)
    assert len(result["rows"]) == len(source["rows"])
    assert result["candidates"][0]["shift_end"] == "2026-10-03T10:00:00-05:00"
    assert result["candidates"][-1] == source["candidates"][-1]
    assert result["recommended_assignee_id"] == source["recommended_assignee_id"]
    tasks = [task for row in result["rows"] for task in row["assigned_tasks"]]
    assert tasks and all(task.get("task_id") and task.get("due_at") and task.get("note") for task in tasks)


@pytest.mark.asyncio
async def test_changed_queue_feasibility_and_coverage_constraints_are_exact(fake_backend):
    source = await get_pickup_workload(tool_context=context())
    source["rows"][0]["orders"][0].update(estimated_finish="2026-10-03T09:40:00-05:00", within_promise=False)
    source["rows"][0]["orders_late_in_estimate"] = 1
    assert project_tool_result("get_pickup_workload", source) == source
    constraints = {"status": "SUCCESS", "rows": [{"payload": {"breaks": [{"associate_id": "A-1004", "start": "09:20"}],
        "protected_assignments": [{"associate_id": "A-1002", "until": "12:00"}], "budget": None,
        "estimate_basis": "Exceptions add time", "requirements": [{"zone": "guest_support", "minimum": 2}]}}]}
    assert project_tool_result("get_coverage_requirements", constraints) == constraints


def test_loss_keeps_all_products_components_thresholds_and_uncertainty(fake_backend):
    source = domain.get_shrink_signals(tool_context=context())
    source["products"][4]["recommendation"] = "investigate"
    source["thresholds"] = {"events": 3, "value_usd": 100}
    result = project_tool_result("get_shrink_signals", source)
    assert result["products"] == source["products"]
    assert len(result["rows"]) == len(source["rows"])
    assert result["thresholds"] == source["thresholds"] and result["rule"] == source["rule"]
    for actual, expected in zip(result["rows"], source["rows"], strict=True):
        for key in ("product_id", "event_type", "events", "qty", "value_usd", "first_event_ts", "last_event_ts"):
            assert actual[key] == expected[key]


def test_feedback_keeps_distinct_context_and_actual_times_across_offsets():
    source = {"status": "SUCCESS", "summary": {"count": 3}, "rows": [
        {"feedback_id": "1", "topic": "stock", "rating": 1, "comment": "No moisturizer", "submitted_at": "2026-10-03T09:00:00-05:00"},
        {"feedback_id": "2", "topic": "stock", "rating": 1, "comment": "No moisturizer", "submitted_at": "2026-10-03T13:30:00Z"},
        {"feedback_id": "3", "topic": "stock", "rating": 5, "comment": "Helpful staff", "product_id": "P-OTHER", "submitted_at": "2026-10-03T09:00:00-05:00"}]}
    result = project_tool_result("get_guest_feedback", source)
    assert result["summary"] == source["summary"]
    assert result["observations"][0]["count"] == 2
    assert result["observations"][0]["first_submitted_at"] == "2026-10-03T13:30:00Z"
    assert result["observations"][1]["product_id"] == "P-OTHER"
    assert result["observations"][1]["rating"] == 5


def test_unknown_tools_and_failed_sources_are_unchanged_independent_objects():
    unknown = {"status": "SUCCESS", "rows": [{"new_connector_data": [1, 2]}]}
    result = project_tool_result("new_tool", unknown)
    assert result == unknown and result is not unknown
    result["rows"][0]["new_connector_data"].append(3)
    assert unknown["rows"][0]["new_connector_data"] == [1, 2]
    failure = {"status": "ERROR", "code": "forbidden", "error_details": "Manager only"}
    assert project_briefing_facts("shrink", {"get_shrink_signals": failure})["get_shrink_signals"] == failure


@pytest.mark.asyncio
async def test_briefing_keeps_changed_fourth_investigation_and_task_age_context(fake_backend, monkeypatch):
    original = domain.get_shrink_signals

    @wraps(original)
    def changed_signals(*args, **kwargs):
        source = original(*args, **kwargs)
        source["products"][3]["recommendation"] = "investigate"
        return source

    monkeypatch.setattr(domain, "get_shrink_signals", changed_signals)
    events = await run(branch("shrink"), MANAGER)
    _, responses = tool_events(events)
    full = next(response.response for response in responses if response.name == "get_shrink_signals")
    facts = outputs(events)["temp:briefing_shrink"]
    assert facts["get_shrink_signals"]["products"] == full["products"]
    assert facts["get_shrink_signals"]["products"][3]["recommendation"] == "investigate"
    assert len(facts["get_shrink_signals"]["rows"]) == len(full["rows"])
    history = facts["get_task_history"]["rows"][0]
    assert history["created_at"] and history["source"] and history["completed_at"] == "not recorded"


def test_writer_loss_join_is_reversible_and_keeps_unmatched_future_fields():
    from agents.cymbal_store_ops.sub_agents.briefing_facts import writer_facts

    source = {"status": "SUCCESS", "complete": False, "limit": 3,
              "products": [{"product_id": "P-OTHER", "events": 6, "qty": 7, "custom_label": "Keep this"}],
              "rows": [
                  {"product_id": "P-OTHER", "event_type": "unknown_loss", "events": 3, "qty": 4, "value_usd": 12, "last_event_ts": "recorded", "future_signal": {"status": "uncertain"}},
                  {"product_id": "P-OTHER", "event_type": "damage", "events": 1, "qty": 1, "value_usd": 3},
                  {"product_id": "P-UNLISTED", "event_type": "adjustment", "events": 2, "qty": 5, "value_usd": 15}],
              "new_source_metadata": {"sourceCode": "exact"}}
    before = deepcopy(source)
    joined = writer_facts("shrink", {"get_shrink_signals": source})["get_shrink_signals"]
    assert source == before and joined["complete"] is False
    assert joined["new_source_metadata"] == source["new_source_metadata"]
    product = joined["products"][0]
    assert all(product[key] == value for key, value in source["products"][0].items())
    component = product["recorded_event_type_breakdown"][0]
    assert (component["events"], component["units"]) == (3, 4)
    assert component["future_signal"] == {"status": "uncertain"}
    restored = []
    for product in joined["products"]:
        for component in product["recorded_event_type_breakdown"]:
            row = deepcopy(component)
            row["product_id"] = product["product_id"]
            row["qty"] = row.pop("units")
            restored.append(row)
    restored.extend(joined["ungrouped_rows"])
    assert sorted(map(lambda r: json.dumps(r, sort_keys=True), restored)) == sorted(map(lambda r: json.dumps(r, sort_keys=True), source["rows"]))


def test_writer_does_not_reinterpret_failed_loss_source():
    from agents.cymbal_store_ops.sub_agents.briefing_facts import writer_facts

    facts = {"get_shrink_signals": {"status": "ERROR", "error_details": "Unavailable"}}
    assert writer_facts("shrink", facts) == facts
