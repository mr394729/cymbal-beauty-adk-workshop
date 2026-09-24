"""The evidence script reads the jobs view the caller may list: the user's own by default, the project's on request."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evidence.py"


def _module():
    spec = importlib.util.spec_from_file_location("evidence", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_default_scope_is_the_users_own_jobs_and_project_scope_is_explicit():
    ev = _module()
    assert "`region-us`.INFORMATION_SCHEMA.JOBS_BY_USER" in ev.query_for("user", "us")
    assert "`region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT" in ev.query_for("project", "us")
    assert "JOBS_BY_PROJECT" not in ev.query_for("user", "us")
    with pytest.raises(ValueError):
        ev.query_for("everyone", "us")


def test_the_statement_keeps_its_namespace_filter_and_parameters():
    sql = _module().query_for("user", "us")
    assert "key = 'ns' AND value = @ns" in sql and "@hours" in sql and "@lim" in sql
