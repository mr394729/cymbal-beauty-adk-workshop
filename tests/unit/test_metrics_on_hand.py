"""stock_invariant reads the on-hand figure only: the stale value (7 + 5 = 12) equals the reorder point and the delayed
shipment, and the first live gate failed a correct answer on that collision."""
from __future__ import annotations

import pytest

LIVE = ("- **On-shelf availability:** 0 units on shelf, with 7 units in the backroom (7 total on hand vs. a reorder point "
        "of 12). An inbound replenishment shipment of 12 units is currently delayed.")
STALE = "Lumière Hydra Cream shows 12 on hand (0 on shelf, 12 in the backroom) against a reorder point of 12."


@pytest.mark.parametrize("text, value, expected", [
    (LIVE, 7, True), (LIVE, 12, False),
    (STALE, 12, True), (STALE, 7, False),
    ("On-hand: 7 units vs. reorder point 12", 7, True), ("On-hand: 7 units vs. reorder point 12", 12, False),
    ("Total on-hand is 7; a 12-unit replenishment is delayed.", 12, False),
    ("There are 7 units on hand.", 7, True),
    # Four answers sampled live on 2026-09-18 (pass 3); the third failed the gate before the gap was widened.
    ("there are **0** units on the shelf and **7** in the backroom (**7** on hand total), which is below the reorder point of **12**.", 7, True),
    ("Total on hand is **7**, which is below the reorder point of **12**.", 7, True),
    ("Key details: - **7** units total on hand, below the reorder point of **12**. - **3** pending BOPIS orders", 7, True),
    ("Key details: - **7** units total on hand, below the reorder point of **12**. - **3** pending BOPIS orders", 12, False),
    ("Key details: - On hand: **7** units", 7, True),
    ("An inbound shipment of 12 units is delayed. On hand: 7.", 12, False),
    ("An inbound shipment of 12 units is delayed. On hand: 7.", 7, True),
    ("A shipment of 12 units is delayed, keeping store inventory at 7 units against a reorder threshold of 12.", 7, True),
    ("A shipment of 12 units is delayed, keeping store inventory at 7 units against a reorder threshold of 12.", 12, False),
    ("Current stock is 7 units; 12 units are on order.", 7, True),
    ("Current stock is 7 units; 12 units are on order.", 12, False),
    ("Store inventory is 12 units with 7 allocated.", 12, True),
    ("Store inventory is 12 units with 7 allocated.", 7, False),
    ("Store inventory of 12 units inbound is delayed.", 12, False),
    ("Backroom inventory is 12 units; shelf stock is unknown.", 12, False),
])
def test_on_hand_figure_is_not_confused_with_other_quantities(text, value, expected):
    from eval.metrics import _says_on_hand

    assert _says_on_hand(text, value) is expected


def _invocation(prompt: str, answer: str):
    from google.adk.evaluation.eval_case import Invocation
    from google.genai import types

    return Invocation(user_content=types.Content(role="user", parts=[types.Part(text=prompt)]),
                      final_response=types.Content(role="model", parts=[types.Part(text=answer)]))


def _with_stock(answer, *, rows=None, name="get_inventory_context", args=None, status="SUCCESS",
                call_id="stock-1", response_id="stock-1", response_name=None, envelope_store=None):
    from google.adk.evaluation.eval_case import IntermediateData
    from google.genai import types

    inv = _invocation("Why is Lumière Hydra Cream flagged?", answer)
    data = {"status": status, "rows": rows if rows is not None else [{"stock": {
        "product_id": "P-0101", "store_id": "S-014", "on_hand": 7,
        "on_shelf_qty": 0, "backroom_qty": 7, "reorder_point": 12}}]}
    if envelope_store is not None:
        data["store_id"] = envelope_store
    inv.intermediate_data = IntermediateData(
        tool_uses=[types.FunctionCall(name=name, id=call_id, args=args or {})],
        tool_responses=[types.FunctionResponse(name=response_name or name, id=response_id, response=data)])
    return inv


def _score(inv):
    from eval.metrics import stock_invariant
    reference = _invocation("Why is Lumière Hydra Cream flagged?", "7 on hand.")
    return stock_invariant(None, [inv], [reference]).overall_score


@pytest.mark.parametrize("answer", [LIVE,
    "The sales shelf is empty (0 units), while 7 units are stored in backroom bay B2.",
    "Four of the seven units in B2 are reserved. The remaining three can go to the shelf.",
    "Store inventory at 7 units; the 12-unit shipment is delayed."])
def test_correct_evidence_does_not_require_particular_answer_wording(answer):
    assert _score(_with_stock(answer)) == 1.0


@pytest.mark.parametrize("changes", [
    {"rows": []}, {"status": "ERROR"}, {"call_id": None}, {"response_id": "other"},
    {"response_name": "other"}, {"name": "inventory_excellence"},
    {"rows": [{"stock": {"product_id": "P-other", "store_id": "S-014", "on_hand": 7}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-other", "on_hand": 7}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-014", "on_hand": 12}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-014", "on_hand": 7,
                           "on_shelf_qty": 0, "backroom_qty": 12}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-014", "on_hand": None}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-014", "on_hand": True}}]},
    {"rows": [{"stock": {"product_id": "P-0101", "store_id": "S-014", "reorder_point": 7,
                           "inbound_qty": 7}}]},
])
def test_correct_prose_cannot_replace_valid_source_evidence(changes):
    assert _score(_with_stock(LIVE, **changes)) == 0.0


def test_stale_claim_and_conflicting_observations_fail():
    assert _score(_with_stock(STALE)) == 0.0
    rows = [{"stock": {"product_id": "P-0101", "store_id": "S-014", "on_hand": n}} for n in (7, 12)]
    assert _score(_with_stock(LIVE, rows=rows)) == 0.0
    assert _score(_invocation("Why is Lumière Hydra Cream flagged?", LIVE)) == 0.0


@pytest.mark.parametrize("name", ["get_product_stock", "check_store_stock", "get_osa_exceptions", "list_store_inventory"])
def test_native_stock_paths_and_complete_decomposition(name):
    row = {"product_id": "P-0101", "on_shelf_qty": 0, "backroom_qty": 7}
    assert _score(_with_stock(LIVE, rows=[row], name=name, envelope_store="S-014")) == 1.0


def test_generic_exact_product_projection_and_unscoped_aggregates():
    args = {"resource": "inventory", "filters": [{"field": "product_id", "operator": "eq", "value": "P-0101"}]}
    assert _score(_with_stock(LIVE, rows=[{"on_hand": 7}], name="query_store_data", args=args,
                             envelope_store="S-014")) == 1.0
    assert _score(_with_stock(LIVE, rows=[{"on_hand": 7}], name="query_store_data",
                             args={"resource": "inventory"}, envelope_store="S-014")) == 0.0
    assert _score(_with_stock(LIVE, rows=[{"category": "Skincare", "sum_on_hand": 7}], name="query_store_data",
                             args={"resource": "inventory"}, envelope_store="S-014")) == 0.0


def test_count_source_is_required_only_when_reference_states_stock():
    from eval.metrics import stock_invariant
    prompt = "How many pickup orders are waiting on Lumière Hydra Cream?"
    reference = _invocation(prompt, "3 pickup orders for 4 units.")
    good = _invocation(prompt, "3 pickup orders for 4 units.")
    assert stock_invariant(None, [good], [reference]).overall_score == 1.0
    stale = _invocation(prompt, "3 orders are waiting; the store shows 12 on hand.")
    assert stock_invariant(None, [stale], [reference]).overall_score == 0.0
    assert stock_invariant(None, [good], []).overall_score == 0.0


@pytest.mark.parametrize("filters", [None, []])
def test_nullable_generic_filters_do_not_break_scoped_rows(filters):
    row = {"product_id": "P-0101", "on_hand": 7}
    assert _score(_with_stock(LIVE, name="query_store_data", rows=[row], envelope_store="S-014",
                             args={"resource": "inventory", "filters": filters})) == 1.0


def test_exact_filtered_sum_and_default_equality_are_valid_stock_paths():
    args = {"resource": "inventory", "filters": [{"field": "product_id", "value": "P-0101"}],
            "measures": [{"operation": "sum", "field": "on_hand"}]}
    for value, score in [(7, 1.0), (12, 0.0)]:
        assert _score(_with_stock(LIVE, name="query_store_data", rows=[{"sum_on_hand": value}],
                                 args=args, envelope_store="S-014")) == score
    # An aggregate alias without the corresponding requested measure is not evidence.
    args["measures"] = []
    assert _score(_with_stock(LIVE, name="query_store_data", rows=[{"sum_on_hand": 7}],
                             args=args, envelope_store="S-014")) == 0.0
