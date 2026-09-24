"""Quickstart 12 — A2A agent (agents across teams).

Another team's assistant (the regional operations desk) that delegates store questions to the store operations app
over the Agent2Agent protocol. The store operations team serves its app with
`adk api_server --a2a quickstarts/12-a2a-agent/server --port 8002`, which publishes the agent card in
server/cymbal_store_ops/agent.json; this agent only needs the card URL (`RemoteA2aAgent`). Nothing about the store
operations app's internals is imported here.
"""
from __future__ import annotations

import os
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402

A2A_BASE = os.environ.get("STORE_OPS_A2A_URL", "http://localhost:8002")
CARD = f"{A2A_BASE}/a2a/cymbal_store_ops/.well-known/agent-card.json"


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    store_ops = RemoteA2aAgent(
        name="cymbal_store_ops_remote", agent_card=CARD,
        description="The Cymbal Beauty store operations app, reached over A2A: a store's start-of-day priorities, "
                    "on-shelf availability, BOPIS coverage, shrink, coaching and store tasks.")
    return LlmAgent(
        name="a2a_agent",
        model=workshop_model(cfg),
        description="The regional operations desk; hands store-level questions to the store operations app over A2A.",
        instruction="You are the Cymbal Beauty regional operations desk assistant, built by another team. For anything "
                    "about one store's operations (priorities, on-shelf availability, BOPIS coverage, shrink, coaching, "
                    "store tasks), transfer to cymbal_store_ops_remote and relay its answer; keep the employee id the "
                    "user gives in the message, because the store operations app signs them in with it. Answer "
                    "questions about the regional desk itself in one or two sentences.",
        sub_agents=[store_ops],
    )


def create_app() -> App:
    return App(name="a2a_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
