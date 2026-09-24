"""The store operations app, served over A2A for quickstart 12 without changing it.

`adk api_server --a2a quickstarts/12-a2a-agent/server --port 8002` serves every folder here that has an `agent.json`
card; this folder only re-exports the app from `agents/cymbal_store_ops` and adds the card, so the team that owns the
app publishes it and the calling team needs nothing but the card URL.
"""
from agents.cymbal_store_ops.agent import app, root_agent  # noqa: F401
