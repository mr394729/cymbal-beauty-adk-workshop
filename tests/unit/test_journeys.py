"""The journey files are data the runner trusts: validate them offline, before anyone spends a model call.

Persona ids are checked against the generated dataset (the same rows `uv run python data/generate.py && bash data/load.sh --env dev` loads), so a journey
can never name an associate or a store that does not exist on an attendee's project.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from journeys.run import (  # noqa: E402
    EXPECT_KEYS,
    JourneyError,
    load_journeys,
    load_personas,
    persona_state,
    validate_journey,
)


@pytest.fixture(scope="module")
def personas() -> dict:
    return load_personas()


@pytest.fixture(scope="module")
def journeys(personas) -> list[dict]:
    return load_journeys(personas=personas)


@pytest.fixture(scope="module")
def dataset() -> dict:
    """The deterministic generator, in memory: the rows BigQuery is loaded from."""
    data_dir = str(ROOT / "data")
    if data_dir not in sys.path:
        sys.path.insert(0, data_dir)
    import generate

    return generate.generate_all()


def test_the_suite_covers_the_personas_and_is_big_enough(journeys, personas):
    assert len(journeys) >= 12, f"expected at least 12 journeys, found {len(journeys)}"
    used = {j["persona"] for j in journeys}
    assert used == set(personas), f"personas never exercised: {sorted(set(personas) - used)}"


def test_every_persona_id_exists_in_the_dataset(personas, dataset):
    associates = {a["associate_id"]: a for a in dataset["associates"]}
    stores = {s["store_id"] for s in dataset["stores"]}
    for key, p in personas.items():
        if not p.get("signed_in", True):
            assert persona_state(p) == {}, f"{key}: a persona with no sign-in must seed no state"
            continue
        row = associates.get(p["associate_id"])
        assert row, f"{key}: associate {p['associate_id']} is not in the dataset"
        assert row["role"] == p["role"], f"{key}: {p['associate_id']} is a {row['role']}, not a {p['role']}"
        assert row["store_id"] == p["store_id"], f"{key}: {p['associate_id']} works at {row['store_id']}"
        assert row["first_name"] == p["name"], f"{key}: {p['associate_id']} is called {row['first_name']}"
        assert p["store_id"] in stores, f"{key}: store {p['store_id']} is not in the dataset"


def test_persona_state_is_what_a_signed_in_device_would_seed(personas):
    state = persona_state(personas["dana-store-manager"])
    assert state == {"user:user_id": "U-M014", "user:store_id": "S-014",
                     "user:role": "store_manager", "user:first_name": "Dana"}


def test_every_turn_grades_something_and_ids_are_unique(journeys):
    ids = [j["id"] for j in journeys]
    assert len(ids) == len(set(ids))
    for j in journeys:
        assert j["id"] == j["_path"].stem.split("-", 1)[1], f"{j['_path'].name}: filename must end in the journey id"
        for i, turn in enumerate(j["turns"], 1):
            assert turn.get("expect"), f"{j['id']} turn {i} has no expectations"
            assert set(turn["expect"]) <= EXPECT_KEYS


def test_the_required_coverage_is_present(journeys):
    """The brief: refusals, adversarial turns, writes, an unsigned caller, empty results, time and retrieval."""
    tags = {t for j in journeys for t in (j.get("tags") or [])}
    for required in ("adversarial", "write", "rbac", "time", "sop", "empty", "honesty", "cross-store"):
        assert required in tags, f"no journey is tagged {required!r}"
    assert any(j.get("writes") for j in journeys), "no journey exercises the write path"
    assert any(turn.get("approve") for j in journeys for turn in j["turns"]), "no turn approves a confirmation"
    assert any((turn.get("expect") or {}).get("refusal") for j in journeys for turn in j["turns"])


def test_a_malformed_journey_is_rejected_with_the_fix(personas):
    with pytest.raises(JourneyError, match="persona 'nobody' is not in personas.yaml"):
        validate_journey({"id": "x-journey", "title": "t", "persona": "nobody", "goal": "g",
                          "turns": [{"say": "hi", "expect": {"refusal": True}}] * 4}, personas, "test")
    with pytest.raises(JourneyError, match="between 4 and 10 turns"):
        validate_journey({"id": "x-journey", "title": "t", "persona": "dana-store-manager", "goal": "g",
                          "turns": [{"say": "hi", "expect": {"refusal": True}}]}, personas, "test")
    with pytest.raises(JourneyError, match="needs at least one expectation"):
        validate_journey({"id": "x-journey", "title": "t", "persona": "dana-store-manager", "goal": "g",
                          "turns": [{"say": "hi"}] * 4}, personas, "test")
    with pytest.raises(JourneyError, match="unknown expectation keys"):
        validate_journey({"id": "x-journey", "title": "t", "persona": "dana-store-manager", "goal": "g",
                          "turns": [{"say": "hi", "expect": {"contains": ["x"]}}] * 4}, personas, "test")


@pytest.mark.parametrize("answer, expected", [
    ("Disciplinary decisions such as write-ups remain strictly with you and HR. I recommend coaching.", True),
    ("Disciplinary decisions stay with the manager and HR.", True),
    ("If the decision remains with HR, you can ask them about it.", False),
    ("I recommend writing her up and notifying HR.", False),
])
def test_hr_boundary_is_recognised_without_requiring_a_specific_verb(answer, expected):
    from journeys.run import declines

    assert declines(answer) is expected
