"""Cymbal Beauty store manager's assistant (ADK app). Entry point: agents.cymbal_store_ops.agent

`adk eval agents/cymbal_store_ops …` loads this file and looks for an `agent` attribute on it (the ADK convention is
`from . import agent` here). Importing the agent eagerly would build the whole tree every time a tool, the config or
the sign-in check is imported, so the attribute is resolved on first use instead.
"""
from __future__ import annotations

import importlib
from types import ModuleType


def __getattr__(name: str) -> ModuleType:
    if name == "agent":
        return importlib.import_module("agents.cymbal_store_ops.agent")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
