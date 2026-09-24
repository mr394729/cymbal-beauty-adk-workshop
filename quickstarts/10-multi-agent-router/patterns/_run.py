"""Shared runner for the pattern scripts: run one prompt, print every transfer, tool call, route and state delta."""
from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from agents.cymbal_store_ops import fixtures as F  # noqa: E402

# The demo identity. In the app, identify_demo_user (lab) or the signed-in device (production) writes these keys;
# the domain tools read the store from user:store_id, never from the prompt.
MANAGER_STATE = {"user:user_id": F.HERO_MANAGER_ID, "user:store_id": F.HERO_STORE_ID,
                 "user:role": "store_manager", "user:first_name": F.HERO_MANAGER_FIRST_NAME}


def _line(value: object, width: int = 160) -> str:
    return " ".join(str(value).split())[:width]


def _who(ev) -> str:
    """The agent or graph node behind an event (a Workflow authors its function nodes' events itself)."""
    path = ev.node_info.path if ev.node_info else None
    return path.rsplit("/", 1)[-1].split("@")[0] if path else ev.author


def run(agent, prompt: str, state: dict | None = None, show: tuple[str, ...] = ()) -> str:
    """Run `prompt` in a fresh session seeded with `state`; print the trace, the final text and the `show` state keys."""
    async def main() -> str:
        runner = InMemoryRunner(agent=agent, app_name=agent.name)
        session = await runner.session_service.create_session(app_name=agent.name, user_id="demo", state=dict(state or {}))
        print(f"  [prompt] {prompt}")
        final = ""
        async for ev in runner.run_async(user_id="demo", session_id=session.id,
                                         new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
            for part in (ev.content.parts if ev.content and ev.content.parts else []):
                if part.function_call:
                    kind = "transfer" if part.function_call.name == "transfer_to_agent" else "tool"
                    print(f"  [{kind}] {_who(ev)} -> {part.function_call.name}({dict(part.function_call.args or {})})")
                if part.text and not part.thought and ev.is_final_response():
                    final = part.text
            if ev.output is not None and not ev.content and ev.is_final_response():
                final = str(ev.output)          # a function node's result has no content, only an output
            if ev.actions and ev.actions.route is not None:
                print(f"  [route] {_who(ev)} -> {ev.actions.route!r}")
            if ev.actions and ev.actions.state_delta:
                print(f"  [state] {_who(ev)}: {list(ev.actions.state_delta)}")
        print(f"  [final] {_line(final)}")
        done = await runner.session_service.get_session(app_name=agent.name, user_id="demo", session_id=session.id)
        for key in show:
            print(f"  [{key}] {_line(done.state.get(key, '<not in state>'), 240)}")
        return final
    return asyncio.run(main())
