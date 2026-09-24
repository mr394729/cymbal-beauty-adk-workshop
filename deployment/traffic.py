"""Revision traffic for a deployed engine (manual split; prod).

    uv run python deployment/traffic.py list     --env prod
    uv run python deployment/traffic.py promote  --env prod --percent 10 [--revision <name>]   # newest by default
    uv run python deployment/traffic.py rollback --env prod --to <revision>   # 100 % back to a named revision
    uv run python deployment/traffic.py prune    --env prod        # delete revisions with 0 % traffic (keeps newest 3)

Every change is a PATCH of traffic_config; the SDK waits for the operation and the observed config is
re-read and asserted. Percentages must sum to 100. Nothing is retried or defaulted silently.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deployment._common import (  # noqa: E402
    ENVS,
    DeployError,
    assert_traffic,
    client_for,
    get_engine,
    list_revisions,
    load_config,
    manual_traffic_config,
    print_json,
    read_deployment_info,
    resolve_engine_name,
    set_traffic,
    short_revision,
    traffic_view,
    write_deployment_info,
)


def cmd_list(client, name: str) -> None:
    engine = get_engine(client, name)
    view = traffic_view(engine)
    revs = list_revisions(client, name)
    print(f"{name}\ntraffic mode: {view['mode']}")
    targets = {short_revision(k): v for k, v in view["targets"].items()}   # the API names revisions by project number
    newest = revs[-1]["name"] if revs else None
    show_state = any(r["state"] for r in revs)   # revisions.list does not return a state today; print it only if it does
    for r in revs:
        if view["mode"] == "manual":
            share = f"{targets.get(short_revision(r['name']), 0)}%"
        elif view["mode"] == "always_latest":
            share = "100% (latest)" if r["name"] == newest else "0%"
        else:
            share = "traffic not configured"
        state = f"{r['state'] or '':12s} " if show_state else ""
        print(f"  revision {short_revision(r['name']):12s} {state}created {r['create_time'] or '?':32s} {share}")


def cmd_promote(client, cfg, name: str, percent: int, revision: str | None) -> None:
    revs = list_revisions(client, name)
    if not revs:
        raise DeployError("engine has no revisions")
    target = resolve_revision(revs, revision) if revision else revs[-1]["name"]
    current = traffic_view(get_engine(client, name))
    if percent >= 100:
        split = {target: 100}
    else:
        # everything not going to the target stays with the revision currently serving the most traffic
        others = {k: v for k, v in current["targets"].items() if k != target}
        keep = max(others, key=others.get) if others else next((r["name"] for r in reversed(revs) if r["name"] != target), None)
        if keep is None:
            raise DeployError("no other revision to keep traffic on; promote with --percent 100")
        split = {target: percent, keep: 100 - percent}
    set_traffic(client, name, manual_traffic_config(split))
    observed = assert_traffic(client, name, split)
    info = read_deployment_info(cfg.env) or {"env": cfg.env, "resource_name": name}
    if info.get("revision") != target:
        info["previous_revision"] = info.get("revision")
    info["revision"] = target
    info["traffic"] = observed
    write_deployment_info(cfg.env, info)
    print_json({"promoted": short_revision(target), "traffic": observed})


def resolve_revision(revs: list[dict], wanted: str) -> str:
    """Accept the full name (project id or number form) or just the revision id; return the engine's own name for it."""
    for r in revs:
        if r["name"] == wanted or short_revision(r["name"]) == short_revision(wanted):
            return r["name"]
    raise DeployError(f"{wanted} is not a revision of this engine (see `traffic.py list`)")


def cmd_rollback(client, cfg, name: str, prev: str) -> None:
    prev = resolve_revision(list_revisions(client, name), prev)
    info = read_deployment_info(cfg.env) or {"env": cfg.env, "resource_name": name}
    set_traffic(client, name, manual_traffic_config({prev: 100}))
    observed = assert_traffic(client, name, {prev: 100})
    info["previous_revision"], info["revision"], info["traffic"] = info.get("revision"), prev, observed
    write_deployment_info(cfg.env, info)
    print_json({"rolled_back_to": short_revision(prev), "traffic": observed})


def cmd_prune(client, name: str, keep: int) -> None:
    view = traffic_view(get_engine(client, name))
    revs = list_revisions(client, name)
    candidates = [r["name"] for r in revs[:-keep] if view["targets"].get(r["name"], 0) == 0]
    for r in candidates:
        client.agent_engines.runtimes.revisions.delete(name=r)
        print(f"deleted {short_revision(r)}")
    print(f"pruned {len(candidates)} revision(s); kept newest {keep} and any with traffic")


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "promote", "rollback", "prune"])
    ap.add_argument("--env", required=True, choices=ENVS)
    ap.add_argument("--percent", type=int, default=None)
    ap.add_argument("--revision", default=None, help="promote: the candidate (default: newest)")
    ap.add_argument("--to", default=None, help="rollback: the full revision name to send 100 %% of traffic to")
    ap.add_argument("--keep", type=int, default=3)
    a = ap.parse_args()
    cfg = load_config(a.env)
    client = client_for(cfg)
    name = resolve_engine_name(cfg, client)
    if a.cmd == "list":
        cmd_list(client, name)
    elif a.cmd == "promote":
        if a.percent is None or not 0 < a.percent <= 100:
            raise DeployError("promote needs --percent 1..100")
        cmd_promote(client, cfg, name, a.percent, a.revision)
    elif a.cmd == "rollback":
        if not a.to:
            raise DeployError("rollback needs --to <full revision name> (see `traffic.py list`)")
        cmd_rollback(client, cfg, name, a.to)
    else:
        cmd_prune(client, name, a.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
