"""Live suite: runs against your namespaced dataset, so it refuses to start without WORKSHOP_NAMESPACE, and refuses to
score while store_tasks holds lab writes. Both print one clean `ERROR:` line with the fix, not a traceback."""
from __future__ import annotations

import pytest


def pytest_configure(config):
    from agents.cymbal_store_ops.config import require_namespace
    from agents.cymbal_store_ops.preflight import require_sign_in
    from eval.preconditions import assert_fixture_state

    try:
        require_sign_in()          # one clean ERROR line with the fix when the sign-in has expired
    except SystemExit as e:
        raise pytest.UsageError(str(e)) from None
    try:
        ns = require_namespace()   # "Run `uv run python scripts/namespace.py`" when .env has none
        if ns == "unit":
            raise RuntimeError("WORKSHOP_NAMESPACE=unit is reserved for the offline tests. Run live suites on their own "
                               "(`uv run pytest tests/eval -q -k test_golden_gate_passes`, `uv run pytest tests/integration -q -m live`) with the namespace `uv run python scripts/namespace.py` wrote into .env.")
        assert_fixture_state()     # lab writes in store_tasks would make correct answers score as wrong
    except RuntimeError as e:
        raise pytest.UsageError(str(e)) from None
