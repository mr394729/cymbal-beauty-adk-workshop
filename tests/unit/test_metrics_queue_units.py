"""A paired order/unit claim must retain the actual workload quantities."""
import pytest
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.genai import types

from eval.metrics import _order_unit_pairs, _queue_pair_claims_match


def invocation(answer, quantities=(1, 2, 1, 1, 1, 2, 1, 2, 2)):
    call = types.FunctionCall(id="queue", name="get_pickup_workload", args={})
    response = types.FunctionResponse(id=call.id, name=call.name, response={"status": "SUCCESS", "rows": [{
        "pending_order_count": len(quantities), "orders": [{"units": n} for n in quantities]}]})
    return Invocation(user_content=types.Content(parts=[types.Part(text="Who should cover picking?")]),
        final_response=types.Content(parts=[types.Part(text=answer)]),
        intermediate_data=IntermediateData(tool_uses=[call], tool_responses=[response]))


@pytest.mark.parametrize("answer,expected", [
    ("9 orders (12 units)", False), ("9 orders (13 units)", True),
    ("9 pending BOPIS orders for 13 units", True), ("12 units across 9 pickup orders", False),
    ("13 units across 9 pickup orders", True), ("3 orders (4 units) of cream; 9 orders in all.", True),
    ("9 orders; a 12-unit shipment is delayed", True),
])
def test_known_queue_pairs_preserve_quantities_without_confusing_other_counts(answer, expected):
    assert _queue_pair_claims_match(invocation(answer)) is expected


def test_changed_source_quantities_are_used_instead_of_fixed_scenario_answer():
    assert _queue_pair_claims_match(invocation("3 orders (17 units)", quantities=(2, 4, 11)))
    assert not _queue_pair_claims_match(invocation("3 orders (13 units)", quantities=(2, 4, 11)))
    assert _order_unit_pairs("9 orders (13 units)") == [(9, 13)]
