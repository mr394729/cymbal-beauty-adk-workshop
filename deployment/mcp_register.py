"""Register actual discovered schemas, then independently verify endpoint and all tools."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

SOURCES = ["https://docs.cloud.google.com/agent-registry/register-mcp-servers",
           "https://docs.cloud.google.com/agent-registry/manage-mcp-tools"]


def verification(record, endpoint, expected):
    urls = {item.get("url") for item in record.get("interfaces", [])}
    names = {tool.get("name") for tool in record.get("tools", [])}
    return endpoint in urls and expected == names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "namespace", "url"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--env", choices=["dev"], default="dev")
    parser.add_argument("--toolspec", type=Path, required=True)
    parser.add_argument("--operation", choices=["create", "update"], default="create")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", args.namespace):
        parser.error("Invalid workshop namespace.")
    if args.location in {"us", "eu"}:
        parser.error("Agent Registry manual MCP entries require a supported region or global.")
    spec = json.loads(args.toolspec.read_text())
    names = {tool["name"] for tool in spec["tools"]}
    if not names or len(args.toolspec.read_bytes()) > 10 * 1024:
        parser.error("Provide the nonempty actual tools/list specification, at most 10 KB.")
    name = f"cymbal-store-mcp-{args.namespace}-{args.env}"
    cmd = ["gcloud", "agent-registry", "services", args.operation, name,
        "--project", args.project, "--location", args.location,
        "--mcp-server-spec-content", json.dumps(spec, separators=(",", ":")), "--quiet"]
    if args.operation == "create":
        cmd += ["--display-name", name, "--mcp-server-spec-type", "tool-spec",
                "--interfaces", f"url={args.url},protocolBinding=jsonrpc"]
    print(shlex.join(cmd))
    if not args.apply:
        print("Then verify the separate MCP registry entry includes the exact endpoint and tool names.")
        return
    subprocess.run(cmd, check=True)
    args.out.mkdir(parents=True, exist_ok=True)
    for attempt in range(12):
        listing = json.loads(subprocess.check_output(["gcloud", "agent-registry", "mcp-servers", "list",
            "--project", args.project, "--location", args.location, "--filter", f"displayName={name}",
            "--format=json"], text=True))
        matches = [item for item in listing if verification(item, args.url, names)]
        if len(matches) == 1:
            detail = json.loads(subprocess.check_output(["gcloud", "agent-registry", "mcp-servers", "describe",
                matches[0]["name"], "--project", args.project, "--location", args.location, "--format=json"], text=True))
            if verification(detail, args.url, names):
                (args.out / "registry-entry.json").write_text(json.dumps(detail, indent=2) + "\n")
                print(json.dumps({"verified": True, "name": detail["name"], "endpoint": args.url, "tools": sorted(names)}))
                return
        if attempt < 11:
            time.sleep(5)
    raise SystemExit("Registration submitted, but endpoint/tools were not verified within 60 s. Inspect Agent Registry; do not call this ready.")


if __name__ == "__main__":
    main()
