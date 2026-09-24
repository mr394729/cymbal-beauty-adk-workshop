"""Data contract probe: exercise the data backend contract without a model in the loop.

    uv run python scripts/probe_data_contract.py

Prints the backend's describe() block, the domain tools the store manager agent gets, the governed raw-SQL
tools of the NL2SQL extension, then runs one get_osa_exceptions() for the hero store and one
execute_sql("DELETE ...") which must be refused by the guard before any warehouse is touched, then one SELECT. Exit 1, with
the error printed, if the refusal does not happen or either read fails: `probe ok` means all three behaved. There is no
fallback: a backend that fails its healthcheck stops the probe with the reason.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

# ADK announces its experimental feature flags with a UserWarning at import; they are not the probe's output.
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _tool_names(tools: list) -> list[str]:
    names: list[str] = []
    for t in tools:
        if hasattr(t, "get_tools"):  # a toolset (BigQueryToolset): expand it
            names.extend(x.name for x in asyncio.run(t.get_tools()))
        else:
            names.append(t.name)
    return names


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=3, help="rows to request from get_osa_exceptions")
    a = ap.parse_args()

    from agents.cymbal_store_ops.tools import domain_tools
    from agents.cymbal_store_ops.tools.data_backend import make_backend

    backend = make_backend()  # eager healthcheck: raises RuntimeError with the reason if the data is not there
    info = backend.describe()
    print(f"== backend: {backend.name}")
    for k, v in info.items():
        print(f"   {k:<13} {v}")

    print("== domain tools (what the core agent calls; identical on every backend)")
    for fn in (domain_tools.get_osa_exceptions, domain_tools.check_store_stock, domain_tools.get_bopis_demand,
               domain_tools.get_shift_roster, domain_tools.get_traffic_and_backlog, domain_tools.get_shrink_signals,
               domain_tools.get_coaching_signals, domain_tools.create_store_task, domain_tools.delegate_task):
        print(f"   {fn.__name__:<20} {(fn.__doc__ or '').strip().splitlines()[0]}")

    print("== raw SQL tools (the NL2SQL extension: BigQueryToolset, WriteMode.BLOCKED)")
    for name in _tool_names(backend.sql_tools()):
        print(f"   {name}")

    from agents.cymbal_store_ops import fixtures as F
    print(f"== get_osa_exceptions(store_id={F.HERO_STORE_ID!r}, limit={a.rows})")
    r = backend.get_osa_exceptions(store_id=F.HERO_STORE_ID, limit=a.rows)
    print(f"   status={r['status']}  rows={len(r.get('rows', []))}")
    osa_error = None if r.get("status") == "SUCCESS" else r.get("error_details") or r.get("status")
    if osa_error:
        print(f"   error: {osa_error}")
    for row in r.get("rows", []):
        print(f"   {row['product_id']}  {row['product_name']:<28} shelf {row['on_shelf_qty']:>2}  backroom {row['backroom_qty']:>2}"
              f"  on hand {row['on_hand']:>2}  reorder point {row['reorder_point']:>2}  {row.get('recommendation', '')}")

    prefix = info["table_prefix"]
    delete = f"DELETE FROM `{prefix}.products` WHERE TRUE"
    print(f"== execute_sql({delete!r})")
    r = backend.execute_sql(delete)
    print(f"   {json.dumps(r)}")
    if r.get("status") != "ERROR":
        print("PROBE FAILED: the DELETE was not refused")
        return 1

    select = f"SELECT product_id, name, price_usd FROM `{prefix}.products` ORDER BY rating_avg DESC LIMIT 3"
    print(f"== execute_sql({select!r})")
    r = backend.execute_sql(select)
    print(f"   status={r['status']}  rows={json.dumps(r.get('rows', r.get('error_details')))}")
    if osa_error or r.get("status") != "SUCCESS":
        print(f"PROBE FAILED: {'get_osa_exceptions' if osa_error else 'the SELECT'} did not succeed (the error is above)")
        return 1
    print("probe ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
