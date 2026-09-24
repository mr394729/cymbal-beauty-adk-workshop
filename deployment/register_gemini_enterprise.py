"""Register the deployed concierge as an agent in a Gemini Enterprise app (Discovery Engine API).

    uv run python deployment/register_gemini_enterprise.py register --env dev --app-id <GE engine id> \
        [--display-name "Cymbal Beauty Concierge"] [--description "..."] [--icon-uri https://.../icon.png]
    uv run python deployment/register_gemini_enterprise.py list --app-id <GE engine id>
    uv run python deployment/register_gemini_enterprise.py update --app-id <id> --agent-id <id> [--env dev] [--description ...]
    uv run python deployment/register_gemini_enterprise.py delete --app-id <id> --agent-id <id>

Mechanics: a Gemini Enterprise app is a Discovery Engine *engine*; agents are children of its default
assistant. An ADK agent deployed to Agent Runtime (formerly Agent Engine) is registered with an
`adkAgentDefinition` that points at the reasoningEngine resource; Gemini Enterprise then calls it on
behalf of the signed-in user. Discovery Engine is always addressed at the `global` location, whatever
region the runtime lives in. Every failure is surfaced; nothing is retried or defaulted silently.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import google.auth
import google.auth.transport.requests
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API = "https://discoveryengine.googleapis.com/v1alpha"


def _headers(project: str) -> dict[str, str]:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json", "x-goog-user-project": project}


def _agents_url(project: str, app_id: str) -> str:
    return (f"{API}/projects/{project}/locations/global/collections/default_collection/engines/{app_id}"
            f"/assistants/default_assistant/agents")


def _reasoning_engine(env: str) -> str:
    sys.path.insert(0, str(ROOT))
    from deployment._common import client_for, load_config, resolve_engine_name

    cfg = load_config(env)
    return resolve_engine_name(cfg, client_for(cfg))   # AGENT_ENGINE_ID, else the engine labelled with your namespace


def _check(resp: requests.Response, what: str) -> dict:
    if resp.status_code >= 300:
        sys.exit(f"{what} failed: HTTP {resp.status_code}\n{resp.text[:1500]}")
    return resp.json() if resp.text else {}


def register(a) -> None:
    engine = _reasoning_engine(a.env)
    body = {
        "displayName": a.display_name,
        "description": a.description,
        "adkAgentDefinition": {
            "toolSettings": {"toolDescription": a.tool_description or a.description},
            "provisionedReasoningEngine": {"reasoningEngine": engine},
        },
    }
    if a.icon_uri:
        body["icon"] = {"uri": a.icon_uri}
    resp = requests.post(_agents_url(a.project, a.app_id), headers=_headers(a.project), json=body, timeout=60)
    agent = _check(resp, "register")
    print(json.dumps({"agent": agent.get("name"), "displayName": agent.get("displayName"), "state": agent.get("state"),
                      "reasoningEngine": engine}, indent=2))


def update(a) -> None:
    body, mask = {}, []
    if a.description:
        body["description"] = a.description
        mask.append("description")
    if a.display_name and a.display_name != "Cymbal Beauty Concierge":
        body["displayName"] = a.display_name
        mask.append("displayName")
    if a.env:
        body["adkAgentDefinition"] = {"toolSettings": {"toolDescription": a.tool_description or a.description or ""},
                                      "provisionedReasoningEngine": {"reasoningEngine": _reasoning_engine(a.env)}}
        mask.append("adkAgentDefinition")
    if not mask:
        sys.exit("nothing to update: pass --description, --display-name and/or --env")
    url = f"{_agents_url(a.project, a.app_id)}/{a.agent_id}?updateMask={','.join(mask)}"
    print(json.dumps(_check(requests.patch(url, headers=_headers(a.project), json=body, timeout=60), "update"), indent=2))


def list_agents(a) -> None:
    data = _check(requests.get(_agents_url(a.project, a.app_id), headers=_headers(a.project), timeout=60), "list")
    agents = data.get("agents", [])
    print(f"{len(agents)} agent(s) in {a.app_id}:")
    for ag in agents:
        eng = ag.get("adkAgentDefinition", {}).get("provisionedReasoningEngine", {}).get("reasoningEngine", "-")
        print(f"  {ag['name'].split('/')[-1]:22s} {ag.get('state', '?'):10s} {ag.get('displayName', '')!r}  -> {eng}")


def delete(a) -> None:
    _check(requests.delete(f"{_agents_url(a.project, a.app_id)}/{a.agent_id}", headers=_headers(a.project), timeout=60), "delete")
    print(f"deleted agent {a.agent_id} from {a.app_id}")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("register", "update", "list", "delete"):
        p = sub.add_parser(name)
        p.add_argument("--app-id", required=True, help="Gemini Enterprise app (Discovery Engine engine) id")
        if name in ("register", "update"):
            p.add_argument("--env", default="dev" if name == "register" else None)
            p.add_argument("--display-name", default="Cymbal Beauty Concierge")
            p.add_argument("--description", default="Product advice, store stock, salon bookings and Glow Rewards for Cymbal Beauty guests.")
            p.add_argument("--tool-description", default="")
            p.add_argument("--icon-uri", default="")
        if name in ("update", "delete"):
            p.add_argument("--agent-id", required=True)
    a = ap.parse_args()
    if not a.project:
        sys.exit("GOOGLE_CLOUD_PROJECT is not set")
    {"register": register, "update": update, "list": list_agents, "delete": delete}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
