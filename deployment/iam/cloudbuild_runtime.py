"""Record optional agent service configuration without resolving secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path

NAMES = ("SOP_DATA_STORE", "MEMORY_BANK_ENGINE", "CYMBAL_MCP_URL", "CYMBAL_MCP_AUDIENCE",
         "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT", "CYMBAL_MCP_SCOPE_SECRET", "MODEL_ARMOR_TEMPLATE")


def record(path=Path("build/runtime-features.json")):
    settings = {name: os.environ.get(name, "") for name in NAMES}
    mcp = [settings[name] for name in NAMES if name.startswith("CYMBAL_MCP_")]
    if any(mcp) and not all(mcp):
        raise ValueError("MCP deployment requires URL, audience, caller and pinned signing-secret reference")
    reference = settings["CYMBAL_MCP_SCOPE_SECRET"]
    if reference and (":" not in reference or not reference.rsplit(":", 1)[1].isdigit()):
        raise ValueError("MCP signing secret must use a pinned numeric version")
    if not Path("installation_scripts/install_report_browser.sh").is_file():
        raise ValueError("Missing report browser installation script in release source")
    document = {"git_sha": os.environ.get("COMMIT_SHA", ""), "namespace": os.environ["WORKSHOP_NAMESPACE"],
                "environment": os.environ["STORE_OPS_ENV"], "runtime_settings": settings,
                "secret_values_resolved": False,
                "browser_installation_script": "installation_scripts/install_report_browser.sh"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")
    return document


if __name__ == "__main__":
    record()
