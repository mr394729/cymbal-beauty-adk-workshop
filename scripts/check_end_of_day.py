"""Run a real model/tool journey and save its actual ADK report artifact locally."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(out: Path):
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from agents.cymbal_store_ops.agent import create_app
    from agents.cymbal_store_ops.tools.data_backend import prewarm
    from frontend.server import DEMO_IDENTITIES

    await asyncio.to_thread(prewarm)
    app = create_app()
    runner = InMemoryRunner(app=app)
    user_id = "report-review-manager"
    session = await runner.session_service.create_session(app_name=app.name, user_id=user_id,
                                                         state=dict(DEMO_IDENTITIES["manager"]))
    question = ("Create the end-of-day PDF for Friday, October 2. I need the important commercial insights, "
                "what went well and specific follow-up for the next shift. Explain the meaningful changes "
                "and tensions, not just the headline totals. Keep it concise and grounded in the records.")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    events = []
    async with asyncio.timeout(300):
        async for event in runner.run_async(user_id=user_id, session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=question)])):
            events.append(event.model_dump(mode="json", exclude_none=True))
            (out / "events.json").write_text(json.dumps(events, indent=2, default=str))
    elapsed = time.monotonic() - started
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.json").write_text(json.dumps(events, indent=2, default=str))
    scope = dict(app_name=app.name, user_id=user_id, session_id=session.id)
    keys = await runner.artifact_service.list_artifact_keys(**scope)
    if not keys:
        raise RuntimeError("Agent did not create an artifact; inspect events.json.")
    artifacts = []
    for filename in keys:
        versions = await runner.artifact_service.list_versions(**scope, filename=filename)
        version = max(versions)
        part = await runner.artifact_service.load_artifact(**scope, filename=filename, version=version)
        if not part.inline_data or part.inline_data.mime_type != "application/pdf":
            continue
        (out / filename).write_bytes(part.inline_data.data)
        artifacts.append({"filename": filename, "version": version, "bytes": len(part.inline_data.data)})
    result = {"elapsed_seconds": round(elapsed, 2), "artifacts": artifacts,
              "model": os.environ.get("MODEL", "configured model"), "session_id": session.id}
    (out / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    await runner.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/artifacts/agent-run"))
    args = parser.parse_args()
    asyncio.run(run(args.out))
