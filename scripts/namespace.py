"""Set or show your WORKSHOP_NAMESPACE: the short id that keeps your resources apart in a shared project.

    uv run python scripts/namespace.py                 # show it; if .env has none, derive one from your sign-in and write it
    uv run python scripts/namespace.py --set alex      # choose your own (3-12 lowercase letters or digits)

The derived id is `u` + the first six hex characters of sha256(your gcloud account, lower-cased): stable across
machines, unique enough for a room, and not your email. It is written into .env once, visibly; nothing in the repo
derives it silently at run time.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]{2,11}$")


def current() -> str | None:
    if not ENV_FILE.exists():
        return None
    m = re.search(r"^WORKSHOP_NAMESPACE=(\S*)\s*$", ENV_FILE.read_text(), flags=re.M)
    return m.group(1) if m and m.group(1) else None


def derive() -> str:
    p = subprocess.run(["gcloud", "config", "get-value", "account"], capture_output=True, text=True)
    account = p.stdout.strip()
    if p.returncode != 0 or not account or "@" not in account:
        raise SystemExit("no active gcloud account: run `gcloud auth login`, or choose a name with --set <name>")
    return "u" + hashlib.sha256(account.lower().encode()).hexdigest()[:6]


def write(ns: str) -> None:
    if not ENV_FILE.exists():
        raise SystemExit(".env does not exist: cp .env.example .env first")
    text = ENV_FILE.read_text()
    if re.search(r"^WORKSHOP_NAMESPACE=.*$", text, flags=re.M):
        text = re.sub(r"^WORKSHOP_NAMESPACE=.*$", f"WORKSHOP_NAMESPACE={ns}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nWORKSHOP_NAMESPACE={ns}\n"
    ENV_FILE.write_text(text)


def show(ns: str) -> None:
    print(f"WORKSHOP_NAMESPACE={ns}")
    print()
    print("Your resources (the same pattern for preprod and prod):")
    for label, value in [
        ("BigQuery dataset", f"cymbal_beauty_{ns}_dev"),
        ("Agent Runtime engine", f"cymbal-store-ops-{ns}-dev"),
        ("Quickstart engines", f"qs-{ns}-<quickstart>"),
        ("SOP data store (Vertex AI Search)", f"cymbal-store-sops-{ns}"),
        ("Pub/Sub topic (quickstart 11)", f"cymbal-store-ops-recommendations-{ns}"),
        ("BigQuery job label", f"ns={ns}"),
    ]:
        print(f"  {label:<30} {value}")
    print("\nList them any time with `uv run python scripts/resources.py`; remove them with `uv run python scripts/resources.py --delete --yes`.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="name", help="choose your namespace instead of deriving one")
    a = ap.parse_args()
    if a.name:
        if not NAMESPACE_RE.match(a.name):
            raise SystemExit(f"{a.name!r}: use 3-12 lowercase letters or digits, starting with a letter")
        write(a.name)
        show(a.name)
        return 0
    ns = current()
    if ns:
        if not NAMESPACE_RE.match(ns):
            raise SystemExit(f".env has WORKSHOP_NAMESPACE={ns!r}, which is invalid: fix it or run with --set <name>")
        show(ns)
        return 0
    ns = derive()
    write(ns)
    print(f"wrote WORKSHOP_NAMESPACE={ns} to .env (derived from your gcloud account)\n")
    show(ns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
