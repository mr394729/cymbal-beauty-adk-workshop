"""Starter pools preserve exact journey links without claiming unrun additions are evaluated."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = yaml.safe_load((ROOT / "frontend/scenarios.yaml").read_text())["scenarios"]
PROMPTS = [(s["id"], p) for s in SCENARIOS for p in s["prompts"]]
LINKED_PROMPTS = [(scenario, prompt) for scenario, prompt in PROMPTS if "journey" in prompt]


def _journey(name: str) -> dict:
    matches = sorted((ROOT / "journeys").glob(f"*{name}.yaml"))
    assert len(matches) == 1, f"{name}: expected one journey file, found {[m.name for m in matches]}"
    return yaml.safe_load(matches[0].read_text())


@pytest.mark.parametrize("scenario_id, prompt", LINKED_PROMPTS,
                         ids=[f"{s}-{p['journey']}-{p['turn']}" for s, p in LINKED_PROMPTS])
def test_every_linked_prompt_is_the_exact_journey_turn(scenario_id: str, prompt: dict) -> None:
    journey = _journey(prompt["journey"])
    assert journey["id"] == prompt["journey"], f"{scenario_id}: {prompt['journey']} is not that file's id"
    turns = journey["turns"]
    assert 1 <= prompt["turn"] <= len(turns), f"{scenario_id}: {prompt['journey']} has {len(turns)} turns"
    assert prompt["say"] == turns[prompt["turn"] - 1]["say"], (
        f"{scenario_id} quotes {prompt['journey']} turn {prompt['turn']}, which no longer says that")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_every_scenario_signs_in_as_a_demo_identity_the_server_knows(scenario: dict) -> None:
    from frontend.server import DEMO_IDENTITIES

    assert scenario["sign_in"] in DEMO_IDENTITIES, f"{scenario['id']}: unknown demo identity {scenario['sign_in']!r}"
    assert scenario["prompts"], f"{scenario['id']}: a scenario with no prompts is a dead chip"
    assert scenario["situation"].strip() and scenario["watch_for"].strip(), f"{scenario['id']}: needs both lines"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_pool_has_varied_standard_and_complex_requests_with_honest_coverage(scenario):
    prompts = scenario["prompts"]
    assert len({prompt["say"] for prompt in prompts}) == len(prompts)
    assert len({prompt["label"] for prompt in prompts}) == len(prompts)
    assert sum(prompt["complexity"] == "standard" for prompt in prompts) >= 6
    assert sum(prompt["complexity"] == "complex" for prompt in prompts) >= 4
    for prompt in prompts:
        assert prompt["complexity"] in {"standard", "complex"}
        if "journey" in prompt:
            assert prompt["validation_status"] == "journey_linked"
        else:
            assert prompt["validation_status"] == "not_run"
            assert "turn" not in prompt
    if scenario["sign_in"] == "associate":
        assert not any("Noor" in prompt["say"] or "recorded loss" in prompt["say"] for prompt in prompts)


def test_original_journey_coverage_is_preserved():
    assert len(LINKED_PROMPTS) == 24
