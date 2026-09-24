"""Fault checks prove the designated invariant failed without requiring every case to fail."""
import pytest

from eval.fault_assertions import fault_was_detected


@pytest.mark.parametrize('score', ['0.0', '0.5', '0.75'])
def test_below_unchanged_threshold_is_a_detected_fault(score):
    message = f'Following are all the test failures.\ncoverage_invariant for agents.cymbal_store_ops.agent Failed. Expected 1.0, but got {score}.'
    assert fault_was_detected(message, 'coverage_invariant')


@pytest.mark.parametrize('message', [
    'plan_invariant for agent Failed. Expected 1.0, but got 0.0.',
    'coverage_invariant for agent Failed. Expected 0.5, but got 0.0.',
    'coverage_invariant for agent Failed. Expected 1.0, but got 1.0.',
    'coverage_invariant for agent Failed. Expected 1.0, but got nan.',
    'coverage_invariant for agent Failed. Expected 1.0, but got -1.0.',
    'coverage_invariant was not evaluated.',
    'Connection refused',
])
def test_other_failures_unavailable_results_or_lowered_threshold_do_not_count(message):
    assert not fault_was_detected(message, 'coverage_invariant')
