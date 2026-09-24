"""The remote agent is addressed by its card URL only; the served folder carries a valid card."""
from __future__ import annotations

import json
from pathlib import Path

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

SERVER = Path(__file__).resolve().parents[1] / "server" / "cymbal_store_ops"


def test_remote_agent_by_card_url(quickstart):
    (remote,) = quickstart.root_agent.sub_agents
    assert isinstance(remote, RemoteA2aAgent) and remote.name == "cymbal_store_ops_remote"
    assert quickstart.CARD.endswith("/a2a/cymbal_store_ops/.well-known/agent-card.json")


def test_served_card_parses_and_points_at_the_route():
    from google.adk.a2a import _compat

    data = json.loads((SERVER / "agent.json").read_text())
    card = _compat.parse_agent_card(dict(data))
    assert card.name == "cymbal_store_ops" and len(card.skills) == 3
    assert data["supportedInterfaces"][0]["url"].endswith("/a2a/cymbal_store_ops")


def test_served_folder_only_reexports_the_app():
    text = (SERVER / "agent.py").read_text()
    assert "from agents.cymbal_store_ops.agent import app, root_agent" in text
    assert (SERVER / "__init__.py").read_text().startswith("from . import agent")
