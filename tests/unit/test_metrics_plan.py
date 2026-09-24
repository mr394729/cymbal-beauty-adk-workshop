"""A loss priority can name the product without using an internal id or a category label."""
from __future__ import annotations

import pytest
from google.adk.evaluation.eval_case import Invocation
from google.genai import types

from eval.metrics import plan_invariant


@pytest.mark.parametrize("loss", [
    "Audit Noir Velvet Eau de Parfum after $665 in losses across 6 events.",
    "Review recurring locked-case losses.",
    "Investigate shrink on P-0420.",
])
def test_loss_priority_is_recognised_by_product_name_or_signal(loss):
    answer = f"Check Lumière Hydra Cream backroom stock. Priya can cover BOPIS picking. {loss}"
    inv = Invocation(user_content=types.Content(parts=[types.Part(text="Give me my start-of-day plan.")]),
                     final_response=types.Content(parts=[types.Part(text=answer)]))
    assert plan_invariant(None, [inv], [inv]).overall_score == 1.0


def test_shelf_and_coverage_only_still_fail_the_plan_check():
    inv = Invocation(user_content=types.Content(parts=[types.Part(text="Give me my start-of-day plan.")]),
                     final_response=types.Content(parts=[types.Part(
                         text="Check Lumière Hydra Cream. Priya can cover BOPIS picking. Replenish Bloom Concealer.")]))
    assert plan_invariant(None, [inv], [inv]).overall_score == 0.0
