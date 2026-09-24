"""Stage the quickstart catalog for the ADK developer UI.

    uv run python scripts/quickstart_apps.py            # every quickstart → build/quickstart_apps/qs_<name>/
    uv run adk web build/quickstart_apps --port 8001    # then pick qs_05_data_analyst_agent, and so on

The quickstart folders are named for reading (05-data-analyst-agent); the developer UI needs package names
(qs_05_data_analyst_agent). Pointing `adk web` at `quickstarts/` lists the folders and then answers every message
with 404 "Invalid agent name" and an empty screen (ADK 2.9, seen in a browser), so this stages a copy under names
it accepts. Re-run it after you change a quickstart; the copies are not the source.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment.deploy_quickstart import QS, package_name, stage  # noqa: E402

APPS_DIR = ROOT / "build" / "quickstart_apps"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("apps", nargs="*", help="quickstart folder names; default: all of them")
    a = ap.parse_args()
    apps = a.apps or sorted(p.name for p in QS.iterdir() if p.is_dir() and p.name[:2].isdigit())
    for app in apps:
        if not (QS / app / "agent.py").exists():
            raise SystemExit(f"quickstarts/{app}/agent.py does not exist; the catalog is {', '.join(sorted(p.name for p in QS.iterdir() if p.name[:2].isdigit()))}")
        stage(app, APPS_DIR, with_agents=False)
        print(f"{app:<32} -> {APPS_DIR.relative_to(ROOT)}/{package_name(app)}")
    print(f"\nuv run adk web {APPS_DIR.relative_to(ROOT)} --port 8001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
