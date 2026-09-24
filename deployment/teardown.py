"""Delete the engine (and all its revisions) for one environment.

    uv run python deployment/teardown.py --env dev --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deployment._common import (  # noqa: E402
    ENVS,
    DeployError,
    client_for,
    deployment_info_path,
    engine_namespace_guard,
    existing_engine_name,
    load_config,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", required=True, choices=ENVS)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    if not a.yes:
        raise DeployError("refusing without --yes (this deletes the engine and every revision)")
    cfg = load_config(a.env)
    client = client_for(cfg)
    name = existing_engine_name(client, cfg)
    p = deployment_info_path(a.env)
    if name is None:
        # Nothing deployed for this namespace and env: say so and let `uv run python deployment/teardown.py --env dev --yes && bash data/teardown.sh --env dev --yes` go on to the datasets.
        print(f"no engine labelled ns={cfg.namespace} env={cfg.env} in {cfg.project}: nothing to delete")
    else:
        engine_namespace_guard(client.agent_engines.get(name=name), cfg)
        client.agent_engines.delete(name=name, force=True)
        print(f"deleted {name}")
    if p.exists():
        p.unlink()
        print(f"removed {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
