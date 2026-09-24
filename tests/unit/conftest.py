"""Unit tests are hermetic: a fixed namespace and project, whatever the attendee's .env says."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("WORKSHOP_NAMESPACE", "unit")   # collection-time imports; the fixture below pins it per test
os.environ["SOP_DATA_STORE"] = ""   # empty, not absent: .env cannot fill it in (load_dotenv keeps existing keys)


@pytest.fixture(autouse=True)
def _unit_namespace(monkeypatch):
    from agents.cymbal_store_ops import config

    monkeypatch.setenv("WORKSHOP_NAMESPACE", "unit")
    monkeypatch.setenv("SOP_DATA_STORE", "")   # policy_lookup off unless a test turns it on
    config.load_env_config.cache_clear()
    yield
    config.load_env_config.cache_clear()
