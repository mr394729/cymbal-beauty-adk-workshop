"""Deploy a quickstart to Agent Runtime, smoke it with one question, and (by default) delete it again.

    uv run python deployment/deploy_quickstart.py --app 01-hello-tool-agent [--keep] [--prompt "..."]
    uv run python deployment/deploy_quickstart.py --all                 # every quickstart, one after another
    uv run python deployment/deploy_quickstart.py --delete-all          # remove every quickstart engine in your namespace

Proves the shared deploy path works for any app in the catalog: the same `requirements` export, the same
runtime identity and staging bucket as the dev environment, `extra_packages` = the `agents` package plus the
quickstart, staged under an importable name (`qs_<folder>`). Engines are named `qs-<namespace>-<quickstart>` and labelled `app=quickstart`, `ns=<namespace>`;
nothing here touches the store operations engines or anyone else's namespace. A quickstart that cannot be built (a missing SOP data store, topic or API key) fails loudly
with the exception; it is not skipped.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "quickstarts"))

from deployment._common import (  # noqa: E402
    DeployError,
    client_for,
    label_value,
    load_config,
    service_account_email,
    staging_bucket,
    staging_dir,
)

QS = REPO_ROOT / "quickstarts"
DEFAULT_PROMPTS = {
    "01-hello-tool-agent": "How much Lumière Hydra Cream do the Naperville stores hold?",
    "10-multi-agent-router": "How much Lumière Hydra Cream do the Naperville stores hold?",
    # prompts that make the deployed agent call its tools, so a server or service that only breaks on the engine is caught
    "05-data-analyst-agent": "How many stores are in the dataset? Run the query.",
    "08-mcp-tools-agent": "I'm U-M014, the store manager at Naperville. Which products are missing from the shelf right now?",
    "09-guardrails-agent": "I'm U-M014, the store manager at Naperville. Why is Lumière Hydra Cream flagged?",
}
GENERIC_PROMPT = "Hello — in one sentence, what can you help with?"
# A tool the smoke must observe; an answer that skips it (e.g. "that tool is not available") is a failed smoke.
EXPECTED_TOOLS = {"01-hello-tool-agent": "check_store_stock", "05-data-analyst-agent": "execute_sql",
                  "08-mcp-tools-agent": "get_osa_exceptions", "09-guardrails-agent": "check_store_stock",
                  "10-multi-agent-router": "check_store_stock"}
ENV_PASSTHROUGH = ("SOP_DATA_STORE", "ORDERS_API_KEY", "ORDERS_API_URL", "RECOMMENDATIONS_TOPIC", "A2A_AGENT_URL")


def requirements_file() -> str:
    out = REPO_ROOT / "build" / "requirements.txt"
    out.parent.mkdir(exist_ok=True)
    cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--no-editable",
           "--no-header", "--no-annotate", "--extra", "quickstarts", "-o", str(out)]
    p = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if p.returncode != 0:
        raise DeployError(f"uv export failed: {p.stderr.strip()}")
    return str(out)


def stream(target, prompt: str) -> tuple[list[str], str, list[str]]:
    calls, final, errors = [], "", []
    for ev in target.stream_query(message=prompt, user_id="qs-smoke"):
        for part in (ev.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                calls.append(part["function_call"].get("name", "?"))
            fr = part.get("function_response")
            if fr and isinstance(fr.get("response"), dict) and fr["response"].get("status") == "ERROR":
                errors.append(fr.get("name", "?"))
            if part.get("text") and not ev.get("partial"):
                final = part["text"]
    return calls, final, errors


STAGING = REPO_ROOT / "build" / "qs_staging"
SKIP_DIRS = {"__pycache__", "tests", "eval", ".adk"}
MCP_SERVER = REPO_ROOT / "quickstarts" / "08-mcp-tools-agent" / "cymbal_mcp_server.py"


def package_name(app: str) -> str:
    """qs_03_form_completion_agent: an importable top-level name (the folder name starts with a digit)."""
    return "qs_" + re.sub(r"[^a-z0-9]+", "_", app.lower()).strip("_")


def stage(app: str, root: Path | None = None, *, with_agents: bool = True) -> tuple[Path, str]:
    """Copy the quickstart (and, for a deploy, `agents`) into a folder under names Python can import.

    The folder names start with a digit and contain dashes, which no importer accepts as a package name: the engine
    fails with "No module named '<app>'" (eight of twelve quickstarts, live) and the developer UI lists the folders
    but answers every message with 404 `Invalid agent name` and shows nothing (seen in a browser, ADK 2.9). The SDK
    tars each extra package under the path it is given, and cloudpickle stores every function the quickstart defines
    as a reference to its module, so a deploy stages `agents` next to the quickstart under the same top-level name.
    The developer UI needs only the quickstart: `agents` is importable from the project itself."""
    root = root or STAGING
    pkg = package_name(app)
    root.mkdir(parents=True, exist_ok=True)
    # Quickstart 12's server/ holds the A2A server's own agent; in the developer UI it would show up as a second app,
    # and the desk agent only needs its URL, so the UI copy leaves it out.
    ignore = shutil.ignore_patterns(*SKIP_DIRS, "*.pyc", *(() if with_agents else ("server",)))
    copies = [(QS / app, root / pkg)]
    if with_agents:
        copies.insert(0, (REPO_ROOT / "agents", root / "agents"))
    for src, dst in copies:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)
    if app.startswith("08-"):   # the stdio MCP server travels with the client agent (see quickstarts/08 agent.py)
        shutil.copy2(MCP_SERVER, root / pkg / MCP_SERVER.name)
    return root, pkg


def import_staged(app: str):
    """Import the staged copy so the pickle references qs_<app>.agent, the name the engine will have."""
    staging, pkg = stage(app)
    if str(staging) not in sys.path:
        sys.path.insert(0, str(staging))
    return importlib.import_module(f"{pkg}.agent"), staging, pkg


def deploy_one(app: str, *, keep: bool, prompt: str | None) -> dict:
    cfg = load_config("dev")
    client = client_for(cfg)
    from vertexai.agent_engines import AdkApp  # noqa: PLC0415

    module, staging, pkg = import_staged(app)   # raises with the real reason when a service is missing
    adk_app = AdkApp(app=module.create_app())
    env_vars = {"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "STORE_OPS_ENV": "dev", "WORKSHOP_NAMESPACE": cfg.namespace,
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true"}   # traces without message content (see deploy.py)
    for key in ENV_PASSTHROUGH:
        if os.environ.get(key):
            env_vars[key] = os.environ[key]
    config = {
        "display_name": f"qs-{cfg.namespace}-{app}",
        "description": f"Quickstart {app} (workshop catalog, dev)",
        "requirements": requirements_file(),
        "extra_packages": ["agents", pkg],   # relative to the staging dir: the tar keeps these names
        "staging_bucket": staging_bucket(cfg),
        "gcs_dir_name": staging_dir(cfg, app),
        "env_vars": env_vars,
        "service_account": service_account_email(cfg),
        "labels": {"env": "dev", "app": "quickstart", "quickstart": label_value(app), "ns": cfg.namespace},
        "min_instances": 0,
    }
    t0 = time.time()
    cwd = os.getcwd()
    os.chdir(staging)   # extra_packages paths are relative to the working directory
    try:
        engine = client.agent_engines.create(agent=adk_app, config=config)
    finally:
        os.chdir(cwd)
    name = engine.api_resource.name
    result = {"app": app, "engine": name, "deploy_seconds": round(time.time() - t0)}
    try:
        calls, final, errors = stream(client.agent_engines.get(name=name), prompt or DEFAULT_PROMPTS.get(app, GENERIC_PROMPT))
        result.update({"tool_calls": calls, "tool_errors": errors, "final": final[:300]})
        expected = EXPECTED_TOOLS.get(app)
        missing = expected if expected and expected not in calls else None
        result["smoke"] = "OK" if final and not errors and not missing else "FAILED"
        if missing:
            result["smoke_detail"] = f"expected a {missing} call; the agent answered without it"
    finally:
        if not keep:
            client.agent_engines.delete(name=name, force=True)
            result["deleted"] = True
    return result


def delete_all() -> list[str]:
    cfg = load_config("dev")
    client = client_for(cfg)
    gone = []
    for engine in client.agent_engines.list():
        res = engine.api_resource
        labels = dict(res.labels or {})
        if labels.get("app") == "quickstart" and labels.get("ns") == cfg.namespace:
            client.agent_engines.delete(name=res.name, force=True)
            gone.append(res.display_name)
    return gone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", help="quickstart folder name, e.g. 01-hello-tool-agent")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--keep", action="store_true", help="leave the engine running (default: delete after the smoke)")
    ap.add_argument("--prompt")
    ap.add_argument("--delete-all", action="store_true")
    a = ap.parse_args()
    if a.delete_all:
        print(json.dumps({"deleted": delete_all()}, indent=2))
        return 0
    apps = sorted(p.name for p in QS.iterdir() if p.is_dir() and p.name[:2].isdigit()) if a.all else [a.app]
    if not apps or apps == [None]:
        raise SystemExit("pass --app <folder>, --all or --delete-all")
    results, failed = [], 0
    for app in apps:
        try:
            r = deploy_one(app, keep=a.keep, prompt=a.prompt)
        except Exception as e:  # noqa: BLE001 — reported per app so the loop finishes; never hidden
            r = {"app": app, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        results.append(r)
        if r.get("error") or r.get("smoke") != "OK":
            failed += 1
        print(json.dumps(r, ensure_ascii=False), flush=True)   # one line per quickstart as it finishes (deploys take minutes)
    out = REPO_ROOT / "build" / "quickstart_deploys.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(f"written: {out}  ({len(apps) - failed} OK, {failed} not OK)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
