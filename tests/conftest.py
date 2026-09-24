from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
# Unit tests never touch the cloud; give them a project id only if none is configured.
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "unit-test-project"
# No namespace default here: the offline suites (tests/unit, tests/quickstarts) pin their own, and the live suites
# (tests/eval, tests/integration) refuse to start without the one `uv run python scripts/namespace.py` wrote into .env.


@pytest.fixture
def fake_backend(monkeypatch):
    """Route every tool at the in-memory backend and reset config caches."""
    from agents.cymbal_store_ops import config
    from agents.cymbal_store_ops.tools import data_backend, domain_tools
    from agents.cymbal_store_ops.tools.backends.fake import FakeBackend

    original = data_backend.make_backend
    config.load_env_config.cache_clear()
    original.cache_clear()
    fb = FakeBackend()
    monkeypatch.setattr(data_backend, "make_backend", lambda cfg=None: fb)
    monkeypatch.setattr(domain_tools, "make_backend", lambda cfg=None: fb)
    yield fb
    config.load_env_config.cache_clear()
    original.cache_clear()


class FakeToolContext:
    """The parts of ToolContext the domain tools use: state, and the confirmation round-trip."""

    def __init__(self, state: dict | None = None, confirmed: bool | None = None) -> None:
        self.state = state if state is not None else {}
        self.tool_confirmation = None if confirmed is None else type("Confirmation", (), {"confirmed": confirmed})()
        self.confirmation_requests: list[dict] = []
        self.invocation_id = "inv-1"

    def new_request(self) -> FakeToolContext:
        """Simulate the next user request (a new invocation), as a real session would."""
        self.invocation_id = f"inv-{int(self.invocation_id.split('-')[1]) + 1}"
        return self

    def request_confirmation(self, hint: str | None = None, payload: dict | None = None) -> None:
        self.confirmation_requests.append({"hint": hint, "payload": payload})
