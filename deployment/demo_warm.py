"""Warm the console surfaces the opening primer tours, and print the tabs to have open.

    uv run python deployment/demo_warm.py [--env dev]

It checks the deployment's revisions, the registry entry and the effective identity, then sends one real turn so
the engine is warm and has just written a trace. Anything missing stops the run with the command that fixes it —
a tour that opens an empty page is worse than no tour.

What it does not do: read Cloud Trace back, or touch the local developer UI. Verify those two yourself — open the
deployment's Traces tab and look for the turn this printed, and run `uv run adk web agents --port 8000` and send one prompt.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deployment._common import (  # noqa: E402
    ENVS,
    DeployError,
    client_for,
    get_engine,
    list_revisions,
    load_config,
    resolve_engine_name,
    short_revision,
    traffic_view,
)
from deployment.smoke import DEFAULT_PROMPT, stream  # noqa: E402

CONSOLE = "https://console.cloud.google.com"


def registry_row(display_name: str, project: str, location: str) -> str:
    """The engine's Agent Registry row, or "" when the registry does not list it yet."""
    if not shutil.which("gcloud"):
        raise DeployError("gcloud is not on PATH, so the registry tour cannot be checked.\nFix: install the gcloud CLI, then run this again.")
    out = subprocess.run(  # noqa: S603
        ["gcloud", "agent-registry", "agents", "list", f"--project={project}", f"--location={location}",
         f"--filter=displayName={display_name}", "--format=value(displayName)"],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise DeployError(f"`gcloud agent-registry agents list` failed:\n{out.stderr.strip()}\n"
                          "Fix: check the sign-in and that the Agent Registry API is enabled on this project.")
    return out.stdout.strip()


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="dev", choices=ENVS)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    a = ap.parse_args()

    cfg = load_config(a.env)
    project, location = cfg.project, cfg.agent_engine["location"]
    client = client_for(cfg)
    name = resolve_engine_name(cfg, client)          # raises with `uv run python deployment/release.py && uv run python deployment/deploy.py --env <env> --release release.json` when there is no engine
    engine = get_engine(client, name)
    engine_id = name.rsplit("/", 1)[-1]
    # The engine's own display name, not one rebuilt from the namespace: an engine deployed before the namespace
    # convention still has to be found in the registry by the name the registry actually holds.
    display_name = engine.api_resource.display_name or f"cymbal-store-ops-{cfg.namespace}-{a.env}"

    revisions = list_revisions(client, name)
    if not revisions:
        raise DeployError(f"{display_name} has no revisions, so the scale tour has nothing to show.\n"
                          f"Fix: uv run python deployment/release.py && uv run python deployment/deploy.py --env {a.env} --release release.json")
    traffic = traffic_view(engine)
    identity = engine.api_resource.spec.effective_identity
    if not identity:
        raise DeployError(f"{display_name} reports no effective identity, so the govern tour has nothing to show in "
                          f"its Identity column.\nFix: check agent_engine.service_account in "
                          f"agents/cymbal_store_ops/config/envs/{a.env}.yaml, then redeploy with `uv run python deployment/release.py && uv run python deployment/deploy.py --env {a.env} --release release.json`.")

    row = registry_row(display_name, project, location)
    if not row:
        raise DeployError(f"Agent Registry returned no row for {display_name} in {project}/{location}, although the "
                          "engine itself was found.\nFix: list the registry unfiltered "
                          f"(`gcloud agent-registry agents list --project={project} --location={location}`) and check "
                          "the display name there before concluding anything; registration can lag a fresh deploy.")

    calls, final, errors, _ = stream(client.agent_engines.get(name=name), a.prompt, user_id="demo-warm")
    if errors:
        raise DeployError(f"The warm-up turn had tools answer with an error: {', '.join(errors)}.\n"
                          f"Fix: read the ERROR entries for reasoning engine {engine_id} in project {project}. "
                          f"`uv run python scripts/check_env.py --stage ready (with STORE_OPS_ENV={a.env})` checks the data with your own credentials, not the engine's "
                          "runtime identity, so it can pass while the engine still cannot read.")
    if not calls:
        raise DeployError("The warm-up turn called no tool, so the trace it leaves behind shows nothing worth "
                          "touring.\nFix: run it again with the default prompt; if it repeats, read the routing in "
                          "agents/cymbal_store_ops/prompts/root.md and the engine's logs.")
    if not final.strip():
        raise DeployError(f"The warm-up ran {', '.join(calls)} and then ended without an answer.\n"
                          f"Fix: read the ERROR entries for reasoning engine {engine_id} in project {project}; a "
                          "runtime exception ends a turn this way.")

    print(f"engine        {display_name} ({engine_id})")
    print(f"revisions     {len(revisions)}, newest {short_revision(revisions[-1]["name"])}, traffic {traffic.get('mode', '?')}")
    print(f"identity      {identity}")
    print(f"registry      {row}")
    print(f"warm turn     {len(calls)} tool call(s): {', '.join(calls)}")
    print(f"              answer starts: {final[:80]}…")
    print()
    print("Tabs for the four tours:")
    print("  build       the ADK developer UI at http://localhost:8000 (uv run adk web agents --port 8000), one answered turn already in it")
    print(f"  scale       Agent Platform > Agents > Deployments > {display_name}")
    print(f"  govern      Agent Registry > Agents > {display_name}")
    print(f"  optimise    that deployment's Traces tab, or {CONSOLE}/traces/list?project={project}")
    print(f"  pipeline    {CONSOLE}/cloud-build/builds?project={project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())   # DeployError is a SystemExit: it prints its own message and exits 1
