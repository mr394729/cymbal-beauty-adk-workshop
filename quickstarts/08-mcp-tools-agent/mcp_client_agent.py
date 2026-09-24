"""Run quickstart 08's MCP client agent from the terminal and print what crosses the MCP boundary.

    uv run python quickstarts/08-mcp-tools-agent/mcp_client_agent.py

The agent (quickstarts/08-mcp-tools-agent/agent.py) starts cymbal_mcp_server.py as a child process over stdio,
discovers its tools, and answers one question for Dana, the Naperville store manager: the session starts signed
in, the way the app seeds it. The store-scope guard and `stamp_signed_in_store` run before each call, so the store
reaches the server as an argument the model never typed. The agent never imports the server: swap the
`command`/`args` for any other MCP server (a remote server uses StreamableHTTPConnectionParams instead) and the
agent is unchanged.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from google.adk.runners import InMemoryRunner
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

ROOT = Path(__file__).resolve().parents[2]
QUICKSTART = ROOT / "quickstarts" / "08-mcp-tools-agent" / "agent.py"
sys.path.insert(0, str(ROOT))

from agents.cymbal_store_ops import fixtures as F  # noqa: E402

QUESTION = "How much Lumière Hydra Cream do we have, and why is it flagged?"
SIGNED_IN = {"user:user_id": F.HERO_MANAGER_ID, "user:store_id": F.HERO_STORE_ID, "user:role": "store_manager",
             "user:first_name": F.HERO_MANAGER_FIRST_NAME}


def load_quickstart():
    spec = importlib.util.spec_from_file_location("mcp_tools_agent", QUICKSTART)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def envelope(response: dict) -> dict:
    """The tool's own {"status", "rows"} envelope from an MCP CallToolResult (sent as JSON text content)."""
    texts = [c.get("text", "") for c in response.get("content", []) if c.get("type") == "text"]
    try:
        return json.loads(texts[0]) if texts else response
    except json.JSONDecodeError:
        return response


async def main() -> int:
    app = load_quickstart().app
    agent = app.root_agent
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="lab", state=SIGNED_IN)
    toolset = next(t for t in agent.tools if isinstance(t, BaseToolset))   # the quickstart's stdio toolset
    print(f"== tools discovered over MCP: {[t.name for t in await toolset.get_tools()]}")
    print(f"== signed in: {F.HERO_MANAGER_FIRST_NAME} ({F.HERO_MANAGER_ID}), store_manager at {F.HERO_STORE_ID}")
    print(f"== question: {QUESTION}")
    final = ""
    async for ev in runner.run_async(user_id="lab", session_id=session.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=QUESTION)])):
        for fc in ev.get_function_calls() or []:
            print(f"   call (as the model wrote it): {fc.name}({json.dumps(fc.args, ensure_ascii=False)})")
        for fr in ev.get_function_responses() or []:
            env = envelope(fr.response or {})
            rows = env.get("rows") or []
            stores = sorted({r.get("store_id") for r in rows if r.get("store_id")})
            print(f"   response: {fr.name} -> status={env.get('status')} rows={len(rows)} stores={stores}"
                  + (f" error={env['error_details']}" if env.get("error_details") else ""))
        if ev.is_final_response() and ev.content and ev.content.parts and ev.content.parts[0].text:
            final = ev.content.parts[0].text
    print(f"== final: {final.strip()}")
    await runner.close()
    return 0 if final else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
