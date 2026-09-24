"""Unknown completion evidence stays unknown; explicit source criteria survive enrichment."""
import json
from copy import deepcopy

import pytest

from agents.cymbal_store_ops.tools.operations_tools import get_merchandising_work
from tests.conftest import FakeToolContext


def context():
    return FakeToolContext({'user:store_id': 'S-014', 'user:role': 'store_manager', 'user:user_id': 'U-M014'})


def test_missing_criteria_never_defaults_to_capacity_or_zero(fake_backend):
    before = deepcopy(fake_backend.operations)
    result = get_merchandising_work(context())
    assert result['status'] == 'SUCCESS'
    for directive in result['rows'][0]['payload']['directives']:
        assert directive['required_units'] is None
        assert directive['completion_criteria_status'] == 'not_recorded'
    assert fake_backend.operations == before


@pytest.mark.parametrize('evidence,expected', [
    ({'required_units': 0}, 'recorded'),
    ({'required_units': 5}, 'recorded'),
    ({'required_units': 23}, 'recorded'),
    ({'required_units': None}, 'not_recorded'),
    ({'completion_criteria': 'Place the approved label and record a photograph.'}, 'recorded'),
    ({'completion_criteria': {'approval': 'manager', 'photo_required': True}}, 'recorded'),
    ({'completion_criteria': ['approved label', 'dated photograph'], 'required_units': 7}, 'recorded'),
    ({'completion_criteria': ''}, 'not_recorded'),
    ({'completion_criteria': []}, 'not_recorded'),
    ({'completion_criteria': {}}, 'not_recorded'),
    ({'completion_criteria': None, 'required_units': None}, 'not_recorded'),
])
def test_changed_completion_evidence_is_retained_exactly_without_mutating_source(fake_backend, evidence, expected):
    source = next(r for r in fake_backend.operations if r['store_id'] == 'S-014' and r['system'] == 'directives')
    payload = json.loads(source['payload'])
    directive = payload['directives'][0]
    directive.update(evidence, due_time='11:15', estimated_minutes=19, dependency='A changed stock dependency', status='ready')
    source['payload'] = json.dumps(payload)
    before = deepcopy(fake_backend.operations)
    result = get_merchandising_work(context())
    actual = result['rows'][0]['payload']['directives'][0]
    for key,value in directive.items():
        assert actual[key] == value
    assert actual['required_units'] == evidence.get('required_units')
    assert actual['completion_criteria_status'] == expected
    assert fake_backend.operations == before
