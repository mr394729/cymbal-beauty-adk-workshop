"""Coverage choices come from raw source facts, never one preferred fixture name."""

from copy import deepcopy

import pytest
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.genai import types

from eval.metrics import coverage_invariant


def make(answer="Jordan can cover the 9 pending BOPIS orders (13 units) until 11."):
    calls = [
        types.FunctionCall(name=name, id=name, args={})
        for name in ("get_shift_roster", "get_coverage_requirements", "get_pickup_workload")
    ]
    rows = [
        {
            "associate_id": aid,
            "first_name": name,
            "skills": ["bopis"],
            "shift_start": "2026-10-03T09:00:00-05:00",
            "shift_end": "2026-10-03T17:00:00-05:00",
            "current_task": None,
            "assigned_tasks": [],
        }
        for aid, name in (("A-1000", "Jordan"), ("A-1004", "Priya"))
    ]
    payloads = [
        {"status": "SUCCESS", "rows": rows, "recommended_assignee_id": "A-1004"},
        {
            "status": "SUCCESS",
            "rows": [
                {
                    "store_id": "S-014",
                    "system": "coverage",
                    "payload": {
                        "breaks": [{"associate_id": "A-1004", "start": "10:30", "end": "10:45"}],
                        "protected_assignments": [],
                    },
                }
            ],
        },
        {
            "status": "SUCCESS",
            "rows": [{"pending_order_count": 9, "orders": [{"units": 5}] + [{"units": 1}] * 8}],
        },
    ]
    return Invocation(
        user_content=types.Content(
            parts=[types.Part(text="Who should cover BOPIS picking until 11?")]
        ),
        final_response=types.Content(parts=[types.Part(text=answer)]),
        intermediate_data=IntermediateData(
            tool_uses=calls,
            tool_responses=[
                types.FunctionResponse(name=c.name, id=c.id, response=d)
                for c, d in zip(calls, payloads, strict=True)
            ],
        ),
    )


def score(inv):
    return coverage_invariant(None, [inv], [make()]).overall_score


@pytest.mark.parametrize(
    "answer",
    [
        "Jordan can cover 9 pending orders (13 units) until 11.",
        "Use Priya initially for 9 pending orders (13 units), with Jordan covering her 10:30–10:45 break.",
        "A-1000 can cover the 9 BOPIS orders (13 units).",
    ],
)
def test_supported_primary_or_relief_choice_passes(answer):
    assert score(make(answer)) == 1.0


def test_roster_recommendation_and_order_do_not_control_the_answer():
    inv = make("Alex can cover 9 pending orders (13 units) until 11.")
    inv.intermediate_data.tool_responses[0].response["rows"][0].update(
        first_name="Alex", associate_id="A-new"
    )
    assert score(inv) == 1.0


@pytest.mark.parametrize(
    "change",
    [
        {"skills": ["cash_wrap"]},
        {"current_task": "checkout"},
        {"assigned_tasks": [{"id": "active-task"}]},
        {"shift_start": "2026-10-03T10:00:00-05:00"},
        {"shift_end": "2026-10-03T10:30:00-05:00"},
        {"shift_start": "invalid"},
        {"store_id": "S-other"},
        {"assigned_tasks": None},
    ],
)
def test_unqualified_busy_out_of_window_or_wrong_store_is_not_available(change):
    inv = make()
    inv.intermediate_data.tool_responses[0].response["rows"][0].update(change)
    assert score(inv) == 0.0


@pytest.mark.parametrize(
    "breaks,protected",
    [
        ([{"associate_id": "A-1000", "start": "10:00", "end": "10:15"}], []),
        ([], [{"associate_id": "A-1000", "zone": "cash_wrap", "until": "11:00"}]),
    ],
)
def test_overlapping_break_or_protected_assignment_is_not_available(breaks, protected):
    inv = make()
    inv.intermediate_data.tool_responses[1].response["rows"][0]["payload"] = {
        "breaks": breaks,
        "protected_assignments": protected,
    }
    assert score(inv) == 0.0


def test_priya_without_relief_does_not_cover_her_break():
    assert score(make("Priya can cover all 9 pending orders until 11 without a break.")) == 0.0


@pytest.mark.parametrize(
    "kind", ["missing", "failed", "wrong_id", "wrong_name", "wrong_store", "no_rules"]
)
def test_claims_require_matched_scoped_successful_sources(kind):
    inv = make()
    response = inv.intermediate_data.tool_responses[0]
    if kind == "missing":
        inv.intermediate_data.tool_responses = []
    elif kind == "failed":
        response.response["status"] = "ERROR"
    elif kind == "wrong_id":
        response.id = "other"
    elif kind == "wrong_name":
        response.name = "other"
    elif kind == "wrong_store":
        response.response["store_id"] = "S-other"
    elif kind == "no_rules":
        inv.intermediate_data.tool_responses.pop(1)
    assert score(inv) == 0.0


def test_wrong_queue_units_still_fail():
    assert score(make("Jordan can cover 9 pending BOPIS orders (12 units).")) == 0.0
    assert score(make("Jordan can cover 14 pending BOPIS orders (13 units).")) == 0.0


def test_generic_roster_needs_complete_assignment_evidence():
    inv = make()
    call = inv.intermediate_data.tool_uses[0]
    call.name = "query_store_data"
    call.args = {"resource": "roster"}
    response = inv.intermediate_data.tool_responses[0]
    response.name = call.name
    response.response["store_id"] = "S-014"
    for row in response.response["rows"]:
        row.pop("assigned_tasks")
    assert score(inv) == 0.0
    inv.intermediate_data.tool_uses.append(
        types.FunctionCall(name="query_store_data", id="tasks", args={"resource": "tasks"})
    )
    inv.intermediate_data.tool_responses.append(
        types.FunctionResponse(
            name="query_store_data",
            id="tasks",
            response={"status": "SUCCESS", "store_id": "S-014", "rows": [], "total_matching": 0},
        )
    )
    assert score(inv) == 1.0
    incomplete = deepcopy(inv)
    incomplete.intermediate_data.tool_responses[-1].response["total_matching"] = 10
    assert score(incomplete) == 0.0
