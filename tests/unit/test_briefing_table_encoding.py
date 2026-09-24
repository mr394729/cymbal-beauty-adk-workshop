"""Writer-only tables round-trip source facts, including unknown and exceptional values."""
import json
from copy import deepcopy

import pytest

from agents.cymbal_store_ops.sub_agents.briefing_facts import pack_writer_tables
from tests.unit.test_briefing_signals import MANAGER, branch, outputs, run


def unpack(value):
    if isinstance(value, dict):
        if set(value) in ({"columns", "records"}, {"columns", "records", "common"}):
            common = unpack(value.get("common", {}))
            return [{**deepcopy(common), **dict(zip(value["columns"], [unpack(cell) for cell in row], strict=True))}
                    for row in value["records"]]
        return {key: unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unpack(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_real_branch_evidence_round_trips_without_changing_stored_sources(fake_backend):
    original_bytes = packed_bytes = 0
    for area in ("inventory", "coverage", "shrink"):
        facts = outputs(await run(branch(area), MANAGER))[f"temp:briefing_{area}"]
        before = deepcopy(facts)
        packed = pack_writer_tables(facts)
        assert unpack(packed) == facts == before
        original_bytes += len(json.dumps(facts))
        packed_bytes += len(json.dumps(packed))
    assert packed_bytes < original_bytes * .75


def test_absent_null_boolean_zero_and_new_source_fields_stay_distinct():
    facts = {"rows": [
        {"id": "A", "common_long_field": "Same source metadata", "value": False},
        {"id": "B", "common_long_field": "Same source metadata", "value": 0},
        {"id": "C", "common_long_field": "Same source metadata", "value": None}],
        "heterogeneous": [{"id": "A"}, {"id": "B", "value": None}, {"id": "C", "new_field": "failed pick"}],
        "failed_source": {"status": "ERROR", "source": "allocation", "error_details": "Unavailable"}}
    reconstructed = unpack(pack_writer_tables(facts))
    assert json.dumps(reconstructed, sort_keys=True) == json.dumps(facts, sort_keys=True)
    assert "value" not in reconstructed["heterogeneous"][0]


def test_identical_records_keep_cardinality_and_nested_exceptions():
    row = {"long_shared_field": "A long shared description retained once", "measurements": {"available": None}}
    facts = [deepcopy(row) for _ in range(5)]
    packed = pack_writer_tables(facts)
    assert isinstance(packed, dict) and len(packed["records"]) == 5
    assert unpack(packed) == facts
    changed = deepcopy(facts)
    changed[-1]["measurements"]["available"] = 7
    assert unpack(pack_writer_tables(changed)) == changed
