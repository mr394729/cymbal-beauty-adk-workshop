"""Loud pre-flight for the workshop. Prints a PASS/FAIL/WARN/SKIP table and exits 1 on any FAIL.

    uv run python scripts/check_env.py --stage prereqs   # tools, ADC, project, APIs, location, model
    uv run python scripts/check_env.py --stage ready     # datasets, row counts, fixtures for STORE_OPS_ENV; the
                                                         # optional SOP data store when SOP_DATA_STORE is set
    uv run python scripts/check_env.py                   # both

Every FAIL row carries the command that fixes it. There is no fallback: if a check fails, stop and fix it.
Sign-in comes first: application default credentials must refresh a token and the gcloud CLI must print one. When
either cannot, the cloud checks (project, APIs, model) are reported as SKIP "not checked: sign in first", never as
"disabled", because an expired sign-in makes every API look disabled. WARN rows (APIs only `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` needs) do
not fail the run.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT))

REQUIRED_APIS = ["aiplatform.googleapis.com", "bigquery.googleapis.com"]
# What deployment/deploy.py calls besides aiplatform: the staging bucket (Cloud Storage) and the runtime service
# account it passes (IAM credentials). Secret Manager only when the environment declares secret_env_vars.
DEPLOY_APIS = ["storage.googleapis.com", "iamcredentials.googleapis.com"]
SECRET_API = "secretmanager.googleapis.com"
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"
ADC_FIX = "gcloud auth application-default login"
GCLOUD_FIX = "gcloud auth login"


@dataclass
class Row:
    check: str
    ok: bool
    detail: str
    fix: str = ""
    level: str = ""          # "" = PASS/FAIL by ok; "WARN" = advisory (never fails); "SKIP" = not checked

    @property
    def status(self) -> str:
        return self.level or ("PASS" if self.ok else "FAIL")


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def skipped(check: str, why: str) -> Row:
    return Row(check, True, why, level="SKIP")


def model_name() -> str:
    return os.environ.get("MODEL", "gemini-3.8-flash")


def deploy_apis(env: str | None = None) -> list[str]:
    """The APIs `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` calls beyond the required ones, for STORE_OPS_ENV's config."""
    import yaml

    env = env or os.environ.get("STORE_OPS_ENV", "dev")
    path = ROOT / "agents" / "cymbal_store_ops" / "config" / "envs" / f"{env}.yaml"
    secrets = (yaml.safe_load(path.read_text()) or {}).get("secret_env_vars") if path.exists() else None
    return DEPLOY_APIS + ([SECRET_API] if secrets else [])


def adc_row() -> Row:
    """Application default credentials that can actually get a token: a present but expired sign-in fails here."""
    try:
        import google.auth
        from google.auth.transport.requests import Request

        creds, adc_project = google.auth.default(scopes=[CLOUD_PLATFORM])
        creds.refresh(Request())
    except Exception as e:  # noqa: BLE001 — every failure here means "sign in again"
        return Row("ADC present", False, f"cannot get a token: {type(e).__name__}: {str(e)[:140]}", ADC_FIX)
    principal = getattr(creds, "service_account_email", None) or getattr(creds, "_account", None) or type(creds).__name__
    return Row("ADC present", True, f"{principal}, token refreshed (quota project: {adc_project or 'none'})")


def gcloud_cli_row() -> Row:
    """The gcloud CLI's own sign-in (bq and `uv run python data/generate.py && bash data/load.sh --env dev` use it, not ADC). The token itself is never printed."""
    rc, out = sh(["gcloud", "auth", "print-access-token", "--quiet"])
    if rc != 0:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        reason = next((ln for ln in lines if ln.startswith("ERROR:")), lines[-1] if lines else "no output")
        return Row("gcloud CLI signed in", False, reason[:160], GCLOUD_FIX)
    rc, account = sh(["gcloud", "config", "get-value", "account"])
    return Row("gcloud CLI signed in", True, account.splitlines()[-1] if rc == 0 and account else "token ok")


def model_probe_row(model: str) -> Row:
    try:
        from google import genai
        t = time.time()
        # Keep the client referenced for the whole call: a temporary genai.Client() can be garbage-collected and
        # closed before the request is sent ("Cannot send a request, as the client has been closed").
        client = genai.Client()
        # The SDK logs "Direct use of automatic function calling (AFC) … is not recommended" on every plain call;
        # a warning about a feature this probe does not use would be the first thing an attendee reads.
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)
        try:
            r = client.models.generate_content(model=model, contents="Reply with exactly: ok")
        finally:
            client.close()
        return Row(f"model probe: {model}", "ok" in (r.text or "").lower(), f"{(r.text or '').strip()!r} in {time.time() - t:.1f}s")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        fix = ("wrong location, not wrong model: set GOOGLE_CLOUD_LOCATION=global" if "404" in msg
               else "check that aiplatform.googleapis.com is enabled and your identity has roles/aiplatform.user")
        return Row(f"model probe: {model}", False, msg[:140], fix)


def prereqs() -> list[Row]:
    rows: list[Row] = []
    for tool, hint in [("uv", "curl -LsSf https://astral.sh/uv/install.sh | sh"), ("gcloud", "install the Google Cloud SDK"),
                       ("bq", "gcloud components install bq"), ("git", "install git")]:
        rows.append(Row(f"tool: {tool}", shutil.which(tool) is not None, shutil.which(tool) or "missing", hint))
    rows.append(Row("python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0], "uv python install 3.12"))

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    rows.append(Row("GOOGLE_CLOUD_PROJECT set", bool(project) and project != "your-project-id", project or "unset",
                    "cp .env.example .env and set GOOGLE_CLOUD_PROJECT"))
    rows.append(Row("GOOGLE_GENAI_USE_VERTEXAI=TRUE", os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE",
                    os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "unset"), "set GOOGLE_GENAI_USE_VERTEXAI=TRUE in .env"))
    ns = os.environ.get("WORKSHOP_NAMESPACE", "")
    import re
    rows.append(Row("WORKSHOP_NAMESPACE set", bool(re.match(r"^[a-z][a-z0-9]{2,11}$", ns)), ns or "unset",
                    "uv run python scripts/namespace.py   (writes a short id derived from your sign-in into .env; or uv run python scripts/namespace.py --set <name>)"))
    loc = os.environ.get("GOOGLE_CLOUD_LOCATION", "")
    rows.append(Row("GOOGLE_CLOUD_LOCATION=global", loc == "global", loc or "unset",
                    'Gemini 3.x is served from the global endpoint; set GOOGLE_CLOUD_LOCATION=global (regional = 404)'))

    adc = adc_row()
    cli = gcloud_cli_row()
    rows += [adc, cli]
    cloud_rows = ["project reachable", *(f"api enabled: {api}" for api in REQUIRED_APIS),
                  *(f"api enabled (deploy only): {api}" for api in deploy_apis()), f"model probe: {model_name()}"]
    if not project:
        return rows + [skipped(name, "not checked: set GOOGLE_CLOUD_PROJECT first") for name in cloud_rows]
    if not (adc.ok and cli.ok):
        return rows + [skipped(name, "not checked: sign in first") for name in cloud_rows]

    rc, out = sh(["gcloud", "projects", "describe", project, "--format=value(projectNumber)"])
    rows.append(Row("project reachable", rc == 0, out[:80], f"gcloud config set project {project}; check the id and your access"))
    if rc != 0:
        return rows + [skipped(name, "not checked: the project is not reachable") for name in cloud_rows[1:]]
    rc, out = sh(["gcloud", "services", "list", "--enabled", f"--project={project}", "--format=value(config.name)"], 90)
    if rc != 0:
        rows.append(Row("api list", False, out[-140:], f"your identity needs serviceusage.services.list on {project}"))
        return rows + [skipped(name, "not checked: the enabled APIs could not be listed") for name in cloud_rows[1:]]
    enabled = set(out.split())
    for api in REQUIRED_APIS:
        rows.append(Row(f"api enabled: {api}", api in enabled, "enabled" if api in enabled else "disabled",
                        f"gcloud services enable {api} --project {project}"))
    for api in deploy_apis():
        on = api in enabled
        rows.append(Row(f"api enabled (deploy only): {api}", True, "enabled" if on else "disabled: `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` needs it",
                        "" if on else f"gcloud services enable {api} --project {project}", "" if on else "WARN"))
    if loc == "global":
        rows.append(model_probe_row(model_name()))
    else:
        rows.append(skipped(f"model probe: {model_name()}", "not checked: GOOGLE_CLOUD_LOCATION must be global"))
    return rows



def ready() -> list[Row]:
    rows: list[Row] = []
    import fixtures as F
    env = os.environ.get("STORE_OPS_ENV", "dev")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    ns = os.environ.get("WORKSHOP_NAMESPACE", "")
    if not ns:
        return [Row("WORKSHOP_NAMESPACE set", False, "unset", "uv run python scripts/namespace.py")]
    adc = adc_row()
    if not adc.ok:   # an expired sign-in would otherwise read as twelve missing tables with "uv run python data/generate.py && bash data/load.sh --env dev" fixes
        return [adc, skipped("datasets, row counts, fixtures", "not checked: sign in first")]
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project)
    except Exception as e:  # noqa: BLE001
        return [Row("bigquery client", False, str(e)[:120], "gcloud auth application-default login")]
    main = f"cymbal_beauty_{ns}_{env}"
    for table, expected in F.EXPECTED_ROW_COUNTS.items():
        try:
            n = list(client.query(f"SELECT COUNT(*) n FROM `{project}.{main}.{table}`").result())[0].n
            fix = "bash data/load.sh --env dev --tables store_tasks" if table == "store_tasks" else "uv run python data/generate.py && bash data/load.sh --env dev"
            rows.append(Row(f"{main}.{table} rows", n == expected, f"{n} (expected {expected})", fix))
        except Exception as e:  # noqa: BLE001
            rows.append(Row(f"{main}.{table} exists", False, str(e)[:100], "uv run python data/generate.py && bash data/load.sh --env dev"))

    def one(sql: str):
        return list(client.query(sql).result())[0]

    t = f"`{project}.{main}"
    try:
        r = one(f"""SELECT on_hand, on_shelf_qty, backroom_qty, reorder_point FROM {t}.store_inventory`
                    WHERE store_id='{F.HERO_STORE_ID}' AND product_id='{F.HERO_PRODUCT_ID}'""")
        ok_ = (r.on_hand, r.on_shelf_qty, r.backroom_qty, r.reorder_point) == (F.HERO_STORE_ON_HAND, F.HERO_STORE_ON_SHELF, F.HERO_STORE_BACKROOM, F.HERO_REORDER_POINT)
        rows.append(Row("fixture: hero OSA exception", ok_,
                        f"{F.HERO_PRODUCT_NAME} @ {F.HERO_STORE_CITY}: on_hand {r.on_hand}, shelf {r.on_shelf_qty}, backroom {r.backroom_qty}, reorder point {r.reorder_point}", "uv run python data/generate.py && bash data/load.sh --env dev"))
        r = one(f"""SELECT first_name, role, store_id FROM {t}.associates` WHERE associate_id='{F.HERO_MANAGER_ID}'""")
        rows.append(Row("fixture: hero manager", r.first_name == F.HERO_MANAGER_FIRST_NAME and r.role == "store_manager" and r.store_id == F.HERO_STORE_ID,
                        f"{F.HERO_MANAGER_ID} = {r.first_name} / {r.role} / {r.store_id}", "uv run python data/generate.py && bash data/load.sh --env dev"))
        r = one(f"""SELECT first_name, role, store_id, current_task FROM {t}.associates` WHERE associate_id='{F.HERO_ASSOCIATE_ID}'""")
        rows.append(Row("fixture: hero associate free", r.first_name == F.HERO_ASSOCIATE_FIRST_NAME and r.role == "associate"
                        and r.store_id == F.HERO_STORE_ID and r.current_task is None,
                        f"{F.HERO_ASSOCIATE_ID} = {r.first_name} / {r.role} / current_task {r.current_task}", "uv run python data/generate.py && bash data/load.sh --env dev"))
        r = one(f"""SELECT COUNT(*) n FROM {t}.bopis_orders` WHERE store_id='{F.HERO_STORE_ID}' AND status='pending'
                    AND promised_at <= TIMESTAMP('{F.FIXTURE_NOW_ISO[:11]}11:00:00{F.FIXTURE_NOW_ISO[19:]}')""")
        rows.append(Row("fixture: pending BOPIS by 11:00", r.n == F.HERO_BOPIS_PENDING, f"{r.n} (expected {F.HERO_BOPIS_PENDING})", "uv run python data/generate.py && bash data/load.sh --env dev"))
        r = one(f"""SELECT COUNT(*) n FROM {t}.shrink_events` WHERE store_id='{F.HERO_STORE_ID}' AND product_id='{F.SHRINK_PRODUCT_ID}'
                    AND event_ts BETWEEN TIMESTAMP_SUB(TIMESTAMP('{F.FIXTURE_NOW_ISO}'), INTERVAL 14 DAY) AND TIMESTAMP('{F.FIXTURE_NOW_ISO}')""")
        rows.append(Row("fixture: shrink events (14d)", r.n == F.SHRINK_EVENTS_14D, f"{F.SHRINK_PRODUCT_ID} @ {F.HERO_STORE_ID} = {r.n} (expected {F.SHRINK_EVENTS_14D})", "uv run python data/generate.py && bash data/load.sh --env dev"))
        r = one(f"""SELECT COUNT(*) n FROM {t}.store_tasks` WHERE store_id='{F.HERO_STORE_ID}' AND product_id='{F.HERO_PRODUCT_ID}' AND status='open'""")
        rows.append(Row("fixture: no open task for hero product", r.n == 0, f"{r.n} open task(s) for {F.HERO_PRODUCT_ID}", "bash data/load.sh --env dev --tables store_tasks"))
        r = one(f"""SELECT value FROM {t}.coaching_signals` WHERE associate_id='{F.COACHING_ASSOCIATE_ID}' AND period='{F.FIXTURE_WEEK}' AND metric='bopis_pick_rate'""")
        rows.append(Row("fixture: coaching signal", r.value < 0.6, f"{F.COACHING_ASSOCIATE_ID} bopis_pick_rate {r.value} in {F.FIXTURE_WEEK}", "uv run python data/generate.py && bash data/load.sh --env dev"))
    except Exception as e:  # noqa: BLE001
        rows.append(Row("fixtures", False, str(e)[:120], "uv run python data/generate.py && bash data/load.sh --env dev"))
    return rows + sop_data_store_rows()


def sop_data_store_rows() -> list[Row]:
    """Optional: the Vertex AI Search data store behind policy_lookup. Unset is a pass (the tool is simply not
    registered); set means it must be this namespace's data store, exist, and hold documents."""
    value = os.environ.get("SOP_DATA_STORE", "").strip()
    if not value:
        return [Row("SOP data store (optional)", True, "SOP_DATA_STORE not set: policy_lookup is not registered")]
    from google.api_core.exceptions import GoogleAPICallError, NotFound
    from google.cloud import discoveryengine_v1 as de

    from agents.cymbal_store_ops.tools.policy_lookup import validate_data_store
    try:
        validate_data_store(value, os.environ.get("WORKSHOP_NAMESPACE", ""))
    except RuntimeError as e:
        return [Row("SOP_DATA_STORE names your data store", False, str(e)[:240], "uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup, then set the printed value")]
    rows = [Row("SOP_DATA_STORE names your data store", True, value.rsplit("/", 1)[-1])]
    try:
        de.DataStoreServiceClient().get_data_store(name=value)
        rows.append(Row("SOP data store exists", True, value))
    except NotFound:
        return rows + [Row("SOP data store exists", False, "not found", "uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup")]
    except GoogleAPICallError as e:
        return rows + [Row("SOP data store exists", False, str(e)[:140],
                           "gcloud services enable discoveryengine.googleapis.com; the identity needs roles/discoveryengine.viewer")]
    pager = de.DocumentServiceClient().list_documents(request={"parent": f"{value}/branches/default_branch", "page_size": 10})
    n = len(next(iter(pager.pages)).documents)
    rows.append(Row("SOP data store has documents", n > 0, f"{n}{'+' if n == 10 else ''} document(s)", "uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["prereqs", "ready", "all"], default="all")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows: list[Row] = []
    if a.stage in ("prereqs", "all"):
        rows += prereqs()
    if a.stage in ("ready", "all"):
        rows += ready()
    if a.json:
        print(json.dumps([{**r.__dict__, "status": r.status} for r in rows], indent=2))
    else:
        w = max(len(r.check) for r in rows)
        for r in rows:
            fix = f"\n       Fix: {r.fix}" if r.status in ("FAIL", "WARN") and r.fix else ""
            print(f"[{r.status}] {r.check:<{w}}  {r.detail}{fix}")
    print("\n" + summary(rows))
    return 1 if any(r.status == "FAIL" for r in rows) else 0


def summary(rows: list[Row]) -> str:
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
    extra = "".join(f", {counts[s]} {label}" for s, label in (("WARN", "warning(s)"), ("SKIP", "not checked")) if counts[s])
    return f"{counts['PASS']} passed, {counts['FAIL']} failed{extra}"


if __name__ == "__main__":
    raise SystemExit(main())
