"""Quickstart 11 — ambient event agent (recommendation only).

Not a chat: the input is a store exception event (JSON), here an on-shelf availability (OSA) exception from a shelf
scan. The agent reads the product's stock position at that store (`check_store_stock`: on-shelf, backroom, on-hand
and the deterministic recommendation), drafts one recommendation with its rationale and publishes it to a Pub/Sub
topic (`PubSubToolset`, `publish_message` only) for the store manager to approve. It never creates a task. On Agent
Runtime the same agent is invoked by an event trigger; the README shows how to create the namespaced topic.
"""
from __future__ import annotations

import os
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.tools.pubsub import PubSubToolConfig, PubSubToolset  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import check_store_stock  # noqa: E402

INSTRUCTION = """You receive a store exception event as JSON with event_type, store_id, product_name and detected_at.
This agent handles event_type "osa_exception" (nothing on the shelf for a product). For any other event type, publish
nothing and reply that the event type is not handled here.
1. Call check_store_stock with the event's product_name and store_id.
2. Draft ONE recommendation from the tool result: the action is the tool's `recommendation` (backroom_check |
   replenish | cycle_count | escalate), and the rationale is one line with the on-shelf, backroom and on-hand counts.
3. Publish it with publish_message to the topic {topic} as JSON with the keys store_id, product_id, action, rationale
   and detected_at.
4. Reply in one sentence: the action, the store and the product, and that it was published for the manager to approve.
You recommend; the store manager decides. Never claim a task was created or stock was moved."""


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    topic = os.environ.get("RECOMMENDATIONS_TOPIC")
    if not topic:
        raise RuntimeError("RECOMMENDATIONS_TOPIC is not set: create the topic as the quickstart 11 README shows, then export it")
    return LlmAgent(
        name="ambient_event_agent",
        model=workshop_model(cfg),
        description="Turns a store on-shelf availability exception event into a published recommendation.",
        instruction=INSTRUCTION.format(topic=topic),
        tools=[check_store_stock, PubSubToolset(tool_filter=["publish_message"],
                                                pubsub_tool_config=PubSubToolConfig(project_id=cfg.project))],
    )


def create_app() -> App:
    return App(name="ambient_event_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
