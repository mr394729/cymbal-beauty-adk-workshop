"""Quickstart 10 — multi-agent router.

A coordinator whose sub-agents' `description` fields are the routing table. Two operating modes side by
side: `coaching_specialist` is a chat sub-agent (the coordinator transfers the conversation to it) and
`stock_lookup` is `single_turn` (the coordinator calls it like a tool with only its input schema). The full
pattern set — sequential, parallel, loop, workflow graph — is in patterns/ (run with `uv run python quickstarts/10-multi-agent-router/patterns/01_coordinator_vs_single_turn.py`).
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents.cymbal_store_ops.callbacks import (  # noqa: E402
    enforce_role_before_tool,
    enforce_store_scope_before_tool,
)
from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    check_store_stock,
    get_coaching_signals,
    identify_demo_user,
)


class StockQuery(BaseModel):
    product_name: str = Field(description="product name as the manager said it")
    city: str = Field(description="city of the stores to check")


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    coaching = LlmAgent(
        name="coaching_specialist",
        description="Coaching and development questions about an associate: signals, training suggestions.",
        instruction="You answer coaching questions. Use identify_demo_user when a manager gives their id "
                    "(a demo sign-in), then get_coaching_signals for the associate named. Summarise development "
                    "opportunities and suggest training in under 100 words, as short paragraphs or a short list with no "
                    "headings; never make or recommend HR or disciplinary decisions.",
        tools=[identify_demo_user, get_coaching_signals],
        # people data: the signed-in store and a manager role, enforced in code on the agent that owns the call
        before_tool_callback=[enforce_store_scope_before_tool, enforce_role_before_tool])
    # A district-desk lookup across the stores of one city, so it is not store-scoped. In the capstone the same
    # question is limited to district managers by enforce_store_scope_before_tool.
    stock = LlmAgent(
        name="stock_lookup", mode="single_turn", input_schema=StockQuery, include_contents="none",
        description="How much of one product do the stores in one city hold, on shelf and in the backroom?",
        instruction="Call check_store_stock with the product_name and city given; report each store's on-shelf, "
                    "backroom and on-hand counts in one sentence.",
        tools=[check_store_stock], output_key="last_stock_check")
    return LlmAgent(
        name="multi_agent_router",
        model=workshop_model(cfg),
        description="Routes store questions to a coaching specialist (chat) or a stock lookup (single turn).",
        instruction="You are the Cymbal Beauty district desk. Coaching questions go to coaching_specialist; stock "
                    "questions use stock_lookup; anything else, say what you can help with. Never answer from memory.",
        sub_agents=[coaching, stock],
    )


def create_app() -> App:
    return App(name="multi_agent_router", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
