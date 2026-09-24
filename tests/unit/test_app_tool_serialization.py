"""Packaging succeeds only if every restored static tool can build its model schema."""
from __future__ import annotations

import inspect

import cloudpickle
from google.adk.tools import BaseTool, FunctionTool
from google.adk.tools.base_toolset import BaseToolset


def test_all_optional_app_static_tools_declare_after_pickle(monkeypatch):
    from agents.cymbal_store_ops.config import load_env_config

    values = {
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "WORKSHOP_NAMESPACE": "demo",
        "STORE_OPS_ENV": "dev",
        "STORE_OPS_PREWARM": "0",
        "SOP_DATA_STORE": "projects/test-project/locations/global/collections/default_collection/dataStores/cymbal-store-sops-demo",
        "MEMORY_BANK_ENGINE": "projects/test-project/locations/us-central1/reasoningEngines/123",
        "CYMBAL_MCP_URL": "https://store-mcp.example.run.app/mcp",
        "CYMBAL_MCP_AUDIENCE": "https://store-mcp.example.run.app",
        "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT": "agent-runtime@test-project.iam.gserviceaccount.com",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CYMBAL_MCP_SCOPE_KEY", raising=False)
    monkeypatch.delenv("MODEL_ARMOR_TEMPLATE", raising=False)
    load_env_config.cache_clear()
    try:
        from agents.cymbal_store_ops.agent import create_app
        app = cloudpickle.loads(cloudpickle.dumps(create_app()))
        seen, declarations, deferred = set(), [], []

        def visit(agent):
            if id(agent) in seen:
                return
            seen.add(id(agent))
            for value in getattr(agent, "tools", []):
                if isinstance(value, BaseToolset):
                    # MCP declarations are supplied by the server, not Python closure annotations.
                    # Discovery requires runtime credentials and is covered by transport tests.
                    deferred.append(type(value).__name__)
                    continue
                tool = FunctionTool(value) if inspect.isfunction(value) else value
                assert isinstance(tool, BaseTool), (agent.name, type(tool))
                declaration = tool._get_declaration()
                assert declaration and declaration.name, (agent.name, tool.name)
                declarations.append(declaration.name)
                child = getattr(tool, "agent", None)
                if child is not None:
                    visit(child)
            for child in agent.sub_agents:
                visit(child)

        visit(app.root_agent)
        assert {"remember_work_preference", "recall_work_preferences", "policy_lookup",
                "create_end_of_day_dashboard", "create_store_task", "daily_briefing"} <= set(declarations)
        # one MCP toolset for each agent that reads store data: the coordinator and five sub-agents
        assert deferred == ["ScopedMcpToolset"] * 6
        assert len(declarations) >= 20
    finally:
        load_env_config.cache_clear()
