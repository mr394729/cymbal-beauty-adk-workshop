"""Discover actual authenticated MCP tools and optionally read one exact SKU. No model calls."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agents.cymbal_store_ops.mcp_auth import Settings
from agents.cymbal_store_ops.mcp_connection import TOOLS, make_header_provider, registry_toolspec


async def probe(args):
    caller = os.environ["CYMBAL_MCP_CALLER_SERVICE_ACCOUNT"]
    settings = Settings(os.environ["CYMBAL_MCP_AUDIENCE"].rstrip("/"), os.environ["CYMBAL_MCP_SCOPE_KEY"],
        frozenset({caller}), os.environ["WORKSHOP_NAMESPACE"], os.environ["STORE_OPS_ENV"])
    def token():
        # Explicit impersonation for this operator probe; production factory uses workload metadata.
        return subprocess.check_output(["gcloud", "auth", "print-identity-token",
            "--impersonate-service-account", caller, "--audiences", settings.audience,
            "--include-email", "--project", args.project], text=True).strip()
    context = SimpleNamespace(state={"user:user_id": args.user, "user:store_id": args.store, "user:role": args.role})
    headers = await make_header_provider(settings, caller, token)(context)
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    async with httpx.AsyncClient(headers=headers, timeout=90) as http:
        async with streamable_http_client(settings.audience + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listing = await session.list_tools()
                spec = registry_toolspec([tool.model_dump(mode="json", exclude_none=True) for tool in listing.tools])
                assert {t["name"] for t in spec["tools"]} == set(TOOLS)
                encoded = json.dumps(spec, separators=(",", ":"))
                if len(encoded.encode()) > 10 * 1024:
                    raise ValueError("Actual tool specification exceeds Agent Registry's 10 KB upload cap.")
                (args.out / "toolspec.json").write_text(encoded + "\n")
                record = {"endpoint": settings.audience + "/mcp", "tool_names": sorted(TOOLS),
                          "discovery_seconds": time.perf_counter() - started}
                if args.product:
                    started = time.perf_counter()
                    result = await session.call_tool("get_product_stock", {"product_id": args.product})
                    if result.isError:
                        raise RuntimeError("MCP stock probe failed.")
                    data = result.structuredContent or json.loads(result.content[0].text)
                    assert data["status"] == "SUCCESS", data
                    record["stock"] = data
                    record["warm_read_seconds"] = time.perf_counter() - started
                (args.out / "probe.json").write_text(json.dumps(record, indent=2) + "\n")
                print(json.dumps(record))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("project", "user", "store"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--role", choices=["associate", "store_manager", "district_manager"], required=True)
    parser.add_argument("--product", default="")
    parser.add_argument("--out", type=Path, required=True)
    asyncio.run(probe(parser.parse_args()))


if __name__ == "__main__":
    main()
