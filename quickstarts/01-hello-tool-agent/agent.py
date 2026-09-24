"""Quickstart 01 — hello tool agent.

The smallest useful ADK agent: one LlmAgent, one function tool, one App. The tool is the store
operations app's `check_store_stock`, so the answer comes from the workshop dataset in BigQuery
through the shared DataBackend contract — no SQL, no fallbacks.

Copy this folder to start a new agent: rename the agent, swap the tool, keep the shape.
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import check_store_stock  # noqa: E402

INSTRUCTION = """You help Cymbal Beauty store associates answer one question: is a product in stock at our
stores in a given city (for a guest at the counter, or before sending them to another store)?

Always call check_store_stock with the product name and the city mentioned. Answer in one or two sentences:
store name, units on hand with how many are on the shelf and in the backroom, and whether pick-up (BOPIS) is
eligible. If the tool returns status ERROR, say what could not be checked. Never guess a quantity."""


def make_root_agent() -> LlmAgent:
    """Factory: a fresh agent per call (sub-agents and tools must not be shared between trees)."""
    cfg = load_env_config()  # loud RuntimeError if GOOGLE_CLOUD_PROJECT is unset
    return LlmAgent(
        name="hello_tool_agent",
        model=workshop_model(cfg),
        description="Answers whether a Cymbal Beauty product is in stock at stores in a city.",
        instruction=INSTRUCTION,
        tools=[check_store_stock],
    )


def create_app() -> App:
    return App(name="hello_tool_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
