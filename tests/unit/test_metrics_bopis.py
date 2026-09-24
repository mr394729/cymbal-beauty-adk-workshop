"""bopis_count_invariant: an order count on a line about the hero product must be its order count.

The text below is real. On 2026-09-20 a start-of-day plan said "4 pending BOPIS orders" for a product with three
orders totalling four units, and the consultant answered "3 pending BOPIS orders totaling 4 units" in the next
turn. Both numbers were in the data; only the label moved, and no gate criterion looked at it."""
from __future__ import annotations

import pytest

LIVE_PLAN_WRONG = ("- **P-0101** (Lumière Hydra Cream): Check backroom (**7** on hand, shelf at **0**) to fulfill "
                   "**4** pending BOPIS orders.")
LIVE_PLAN_RIGHT = ("- **P-0101** (Lumière Hydra Cream): Check backroom (**7** on hand, shelf at **0**) to fulfill "
                   "**3** pending BOPIS orders (**4** units).")
LIVE_CONSULTANT = ("Lumière Hydra Cream (**P-0101**) has **0** units on the shelf and **7** in the backroom.\n"
                   "There are **3** pending BOPIS orders totaling **4** units waiting to be picked.")
STORE_TOTAL = "Coverage: assign Priya to clear the **9** pending BOPIS orders for Lumière Hydra Cream and the rest."
OTHER_PRODUCT = "- **P-0548** (Bloom Concealer): restock the shelf; **1** pending BOPIS order."


def _invocation(prompt: str, answer: str):
    from google.adk.evaluation.eval_case import Invocation
    from google.genai import types

    return Invocation(user_content=types.Content(role="user", parts=[types.Part(text=prompt)]),
                      final_response=types.Content(role="model", parts=[types.Part(text=answer)]))


def _score(answer: str) -> float:
    from eval.metrics import bopis_count_invariant

    inv = _invocation("Give me my start-of-day plan.", answer)
    return bopis_count_invariant(None, [inv], [inv]).overall_score


@pytest.mark.parametrize("answer, ok", [
    (LIVE_PLAN_WRONG, False),     # units reported as orders — the defect
    (LIVE_PLAN_RIGHT, True),      # both counts, correctly labelled
    (LIVE_CONSULTANT, True),      # the consultant's wording, which was already right
    (STORE_TOTAL, True),          # the store-wide order count is also a legitimate figure
    (OTHER_PRODUCT, True),        # a line about another product is not this metric's business
    ("No pickups are waiting.", True),
])
def test_a_unit_count_reported_as_an_order_count_fails(answer, ok):
    assert _score(answer) == (1.0 if ok else 0.0)
