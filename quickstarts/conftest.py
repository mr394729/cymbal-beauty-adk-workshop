"""Test wiring for the whole catalog, loaded before any quickstart package is imported.

Environment values the agents need to construct (project, SOP data store, topic, API key) exist here without cloud
access; real runs set them in .env. The fixtures route every domain tool at the in-memory FakeBackend.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

QUICKSTARTS = Path(__file__).resolve().parent
for p in (str(QUICKSTARTS.parent), str(QUICKSTARTS)):
    if p not in sys.path:
        sys.path.insert(0, p)
for key, value in {
    "GOOGLE_CLOUD_PROJECT": "unit-test-project",
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "GOOGLE_CLOUD_LOCATION": "global",
    "WORKSHOP_NAMESPACE": "unit",
    "ORDERS_API_KEY": "demo-key",
    "RECOMMENDATIONS_TOPIC": "projects/unit-test-project/topics/cymbal-store-ops-recommendations-unit",
}.items():
    os.environ.setdefault(key, value)
os.environ["WORKSHOP_NAMESPACE"] = "unit"   # hermetic: never the attendee's namespace from .env
os.environ["SOP_DATA_STORE"] = (            # the unit namespace's data store name; nothing is called at build time
    "projects/unit-test-project/locations/global/collections/default_collection/dataStores/cymbal-store-sops-unit")


_ADC_PATCH = pytest.StashKey()


def pytest_configure(config):
    """Package imports construct apps before fixtures; unit collection needs no ADC."""
    from google.auth.credentials import AnonymousCredentials

    credentials_patch = patch("google.auth.default", return_value=(AnonymousCredentials(), "unit-test-project"))
    credentials_patch.start()
    config.stash[_ADC_PATCH] = credentials_patch


def pytest_unconfigure(config):
    credentials_patch = config.stash.get(_ADC_PATCH, None)
    if credentials_patch is not None:
        credentials_patch.stop()


@pytest.fixture
def fake_backend(monkeypatch):
    from agents.cymbal_store_ops import config
    from agents.cymbal_store_ops.tools import data_backend, domain_tools
    from agents.cymbal_store_ops.tools.backends.fake import FakeBackend

    config.load_env_config.cache_clear()
    data_backend.make_backend.cache_clear()
    fb = FakeBackend()
    monkeypatch.setattr(data_backend, "make_backend", lambda cfg=None: fb)
    monkeypatch.setattr(domain_tools, "make_backend", lambda cfg=None: fb)
    yield fb
    config.load_env_config.cache_clear()


@pytest.fixture
def quickstart(request):
    """The `agent` module of the quickstart whose tests are running, imported the way the staged copy under build/quickstart_apps is imported by the developer UI."""
    folder = Path(request.path).resolve().parents[1].name
    return importlib.import_module(f"{folder}.agent")
