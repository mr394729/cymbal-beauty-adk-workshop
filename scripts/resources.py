"""List, or delete, every workshop resource that carries your namespace.

    uv run python scripts/resources.py                    # list (uv run python scripts/resources.py)
    uv run python scripts/resources.py --delete --yes     # delete all of them (uv run python scripts/resources.py --delete --yes)

What counts as yours: Agent Runtime engines labelled ns=<namespace> (store operations and quickstarts),
BigQuery datasets cymbal_beauty_<namespace>_*, the Vertex AI Search data store cymbal-store-sops-<namespace>, the Pub/Sub topic
and subscription cymbal-store-ops-recommendations-<namespace>[-pull], your folders in the shared staging bucket
(agent_engine/<namespace>/ from deploys, sops/<namespace>/ from the SOP upload), and local
deployment_info.<namespace>.*.json records. Nothing without your namespace is listed or touched, so this is safe in a shared project. Each delete is
printed; a failure is reported and the script exits 1 after trying the rest.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
REGION = os.environ.get("AGENT_ENGINE_LOCATION", "us-central1")


def sh(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr).strip()


def find(project: str, ns: str) -> dict[str, list]:
    from google.api_core.exceptions import NotFound
    from google.cloud import discoveryengine_v1 as de

    from agents.cymbal_store_ops.tools.policy_lookup import sop_data_store_name
    from deployment._common import make_client

    found: dict[str, list] = {"engines": [], "datasets": [], "data_stores": [], "pubsub": [], "staged": [], "local": []}
    client = make_client(project, REGION)
    for engine in client.agent_engines.list():
        res = engine.api_resource
        if dict(res.labels or {}).get("ns") == ns:
            found["engines"].append({"name": res.name, "display_name": res.display_name})
    rc, out = sh(["bq", f"--project_id={project}", "ls", "--format=json", "--max_results=1000"])
    if rc != 0:
        raise SystemExit(f"bq ls failed: {out[:200]}")
    for d in json.loads(out or "[]"):
        ds = d["datasetReference"]["datasetId"]
        if ds.startswith(f"cymbal_beauty_{ns}_"):
            found["datasets"].append(ds)
    try:
        store = de.DataStoreServiceClient().get_data_store(name=sop_data_store_name(project, ns))
        found["data_stores"].append({"name": store.name, "display_name": store.display_name})
    except NotFound:
        pass  # no SOP data store in this namespace: nothing to list
    name = f"cymbal-store-ops-recommendations-{ns}"
    if sh(["gcloud", "pubsub", "subscriptions", "describe", f"{name}-pull", f"--project={project}"])[0] == 0:
        found["pubsub"].append(f"subscription {name}-pull")
    if sh(["gcloud", "pubsub", "topics", "describe", name, f"--project={project}"])[0] == 0:
        found["pubsub"].append(f"topic {name}")
    found["staged"] = [url for url in staged_folders(project, ns) if sh(["gcloud", "storage", "ls", url, f"--project={project}"])[0] == 0]
    found["local"] = [str(p.relative_to(ROOT)) for p in (ROOT / "deployment").glob(f"deployment_info.{ns}.*.json")]
    return found


def staged_folders(project: str, ns: str) -> list[str]:
    """This namespace's folders in the staging bucket the room shares: what deploys uploaded, and the SOP pages."""
    bucket = os.environ.get("AGENT_STAGING_BUCKET", "").strip() or f"gs://{project}-cymbal-store-ops-staging"
    return [f"{bucket}/agent_engine/{ns}/", f"{bucket}/sops/{ns}/"]


def delete(project: str, found: dict[str, list]) -> int:
    from google.cloud import discoveryengine_v1 as de

    from deployment._common import make_client

    failures = 0
    client = make_client(project, REGION)

    def attempt(label: str, fn) -> None:
        nonlocal failures
        try:
            fn()
            print(f"deleted {label}")
        except Exception as e:  # noqa: BLE001 — reported; the rest still get their turn
            failures += 1
            print(f"FAILED  {label}: {type(e).__name__}: {str(e)[:200]}")

    for e in found["engines"]:
        attempt(f"engine {e['display_name']}", lambda e=e: client.agent_engines.delete(name=e["name"], force=True))
    for ds in found["datasets"]:
        def rm_ds(ds=ds):
            rc, out = sh(["bq", f"--project_id={project}", "rm", "-r", "-f", "-d", f"{project}:{ds}"])
            if rc != 0:
                raise RuntimeError(out)
        attempt(f"dataset {ds}", rm_ds)
    for d in found["data_stores"]:
        def rm_store(d=d):
            """Confirmed by reading the store back until NotFound: the delete operation can finish with neither a
            response nor an error ("Unexpected state: Long-running operation had neither response nor error set",
            seen live on 2026-09-16 and on teardown 2026-09-17) although the store is gone."""
            from google.api_core.exceptions import NotFound
            stores = de.DataStoreServiceClient()
            try:
                stores.delete_data_store(name=d["name"])
            except NotFound:
                return
            deadline = time.time() + 900
            while time.time() < deadline:
                try:
                    stores.get_data_store(name=d["name"])
                except NotFound:
                    return
                time.sleep(10)
            raise RuntimeError(f"{d['name']} still exists 900 s after the delete request; check the console and run teardown-all again")
        attempt(f"data store {d['display_name']}", rm_store)
    for item in found["pubsub"]:
        kind, name = item.split(" ", 1)
        def rm_ps(kind=kind, name=name):
            rc, out = sh(["gcloud", "pubsub", f"{kind}s", "delete", name, f"--project={project}", "--quiet"])
            if rc != 0:
                raise RuntimeError(out)
        attempt(item, rm_ps)
    for url in found["staged"]:
        def rm_staged(url=url):
            rc, out = sh(["gcloud", "storage", "rm", "--recursive", url, f"--project={project}", "--quiet"])
            if rc != 0:
                raise RuntimeError(out)
        attempt(f"staged files {url}", rm_staged)
    for rel in found["local"]:
        attempt(rel, lambda rel=rel: (ROOT / rel).unlink())
    return failures


def main() -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in(cli=True)   # gcloud and bq are used for Pub/Sub and datasets   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or sys.exit("GOOGLE_CLOUD_PROJECT is not set")
    ns = os.environ.get("WORKSHOP_NAMESPACE") or sys.exit("WORKSHOP_NAMESPACE is not set: run `uv run python scripts/namespace.py`")
    found = find(project, ns)
    total = sum(len(v) for v in found.values())
    print(f"namespace {ns} in project {project}: {total} resource(s)")
    for kind, items in found.items():
        for item in items:
            print(f"  {kind:<11} {item['display_name'] if isinstance(item, dict) else item}")
    if not a.delete:
        return 0
    if not a.yes:
        raise SystemExit("refusing to delete without --yes")
    failures = delete(project, found)
    print(f"{total - failures} deleted, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
