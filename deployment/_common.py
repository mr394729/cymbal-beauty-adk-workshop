"""Shared helpers for the deployment scripts (no CLI of its own).

Every script in this folder imports from here so that one client factory, one resource-name
convention and one deployment record format exist. Nothing here falls back silently: a missing
value raises with the command that fixes it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env", override=False)  # same source and precedence as agents/cymbal_store_ops/config.py

BUILD_DIR = REPO_ROOT / "build"
DEPLOYMENT_DIR = REPO_ROOT / "deployment"
RELEASE_JSON = REPO_ROOT / "release.json"
ENVS = ("dev", "preprod", "prod")
API_VERSION = "v1beta1"  # revisions + traffic splitting are v1beta1 only (Preview)
WIF_POOL_ID = "cicd"


class DeployError(SystemExit):
    """Loud failure: the message is printed and the process exits 1."""

    def __init__(self, message: str) -> None:
        print(f"ERROR: {message}", file=sys.stderr)
        super().__init__(1)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(paths: list[Path]) -> str:
    """Stable digest of file names + contents (used for prompt/config versions)."""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(REPO_ROOT)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _git(*args: str) -> str | None:
    """Output of a git command, or None when git is not installed or this is not a checkout (a Cloud Build step
    runs in an image without git; `gcloud builds submit` ships a tarball without .git)."""
    try:
        p = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return p.stdout if p.returncode == 0 else None


def git_sha() -> str:
    """Full commit sha from the checkout; in a pipeline without git, the COMMIT_SHA the trigger passed in (Cloud
    Build's own substitution); 'uncommitted' when there is neither. Never a guess."""
    out = _git("rev-parse", "HEAD")
    if out and out.strip():
        return out.strip()
    return os.environ.get("COMMIT_SHA", "").strip() or "uncommitted"


def git_dirty() -> bool:
    out = _git("status", "--porcelain", "--untracked-files=no")
    return bool(out and out.strip())


def label_value(value: str) -> str:
    """Google Cloud label values: lowercase, [a-z0-9_-], max 63 chars."""
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in value.lower())
    return out[:63]


# --------------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------------

def load_config(env: str):
    """Load config/envs/<env>.yaml through the agent's own loader (same precedence rules)."""
    if env not in ENVS:
        raise DeployError(f"--env must be one of {ENVS}, got {env!r}")
    os.environ["STORE_OPS_ENV"] = env
    from agents.cymbal_store_ops.config import load_env_config

    load_env_config.cache_clear()
    try:
        return load_env_config(env)
    except RuntimeError as e:
        raise DeployError(str(e)) from e


def agent_engine_settings(cfg) -> dict[str, Any]:
    ae = dict(cfg.agent_engine)
    ae["display_name"] = cfg.engine_display_name
    for key in ("location", "service_account", "traffic"):
        if not ae.get(key):
            raise DeployError(f"config/envs/{cfg.env}.yaml agent_engine.{key} is missing")
    if ae["traffic"] not in ("latest", "manual"):
        raise DeployError(f"agent_engine.traffic must be latest|manual, got {ae['traffic']!r}")
    ae.setdefault("min_instances", 0)
    ae.setdefault("agent_engine_id", "")
    # identity: "service_account" (default) or "agent" = Agent Identity (a SPIFFE identity issued to the engine itself).
    # gateway: an agent-to-anywhere Agent Gateway resource name; outbound MCP calls are routed and governed through it.
    ae.setdefault("identity", "service_account")
    ae.setdefault("gateway", "")
    if ae["identity"] not in ("service_account", "agent"):
        raise DeployError(f"agent_engine.identity must be service_account or agent, got {ae['identity']!r}")
    if ae["gateway"] and "/agentGateways/" not in str(ae["gateway"]):
        raise DeployError("agent_engine.gateway must be projects/<project>/locations/<location>/agentGateways/<name>")
    return ae


def service_account_email(cfg) -> str:
    sa = str(cfg.agent_engine["service_account"])
    return sa if "@" in sa else f"{sa}@{cfg.project}.iam.gserviceaccount.com"


def staging_bucket(cfg) -> str:
    """gs://<project>-cymbal-store-ops-staging unless AGENT_STAGING_BUCKET overrides it."""
    bucket = os.environ.get("AGENT_STAGING_BUCKET", "").strip() or f"gs://{cfg.project}-cymbal-store-ops-staging"
    if not bucket.startswith("gs://"):
        raise DeployError("AGENT_STAGING_BUCKET must start with gs://")
    return bucket


def engine_name_from_config(cfg) -> str | None:
    """Fully-qualified reasoningEngines name from AGENT_ENGINE_ID (pipelines) or agent_engine.agent_engine_id, or None."""
    raw = str(os.environ.get("AGENT_ENGINE_ID") or cfg.agent_engine.get("agent_engine_id") or "").strip()
    if not raw:
        return None
    if raw.startswith("projects/"):
        return raw
    return f"projects/{cfg.project}/locations/{cfg.agent_engine['location']}/reasoningEngines/{raw}"


ENGINE_APP_LABEL = "cymbal-store-ops"


def staging_dir(cfg, app: str = "store-ops") -> str:
    """The folder in the shared staging bucket one deploy writes its pickle and packages to. It carries the namespace
    and the environment: the SDK's default is a single `agent_engine/` folder, so two people deploying at the same
    time in one project would overwrite each other's upload and one engine could be built from the other's code."""
    return f"agent_engine/{label_value(cfg.namespace)}/{label_value(app)}-{label_value(cfg.env)}"


def engine_labels(cfg) -> dict[str, str]:
    """The labels that identify one environment's engine for one namespace (deploy.py writes them)."""
    return {"app": ENGINE_APP_LABEL, "ns": label_value(cfg.namespace), "env": label_value(cfg.env)}


def find_engines_by_labels(client, cfg) -> list[str]:
    """Every engine in the project carrying this namespace's app/ns/env labels (normally zero or one)."""
    want = engine_labels(cfg)
    found = []
    for engine in client.agent_engines.list():
        labels = dict(engine.api_resource.labels or {})
        if all(labels.get(k) == v for k, v in want.items()):
            found.append(engine.api_resource.name)
    return found


def existing_engine_name(client, cfg) -> str | None:
    """The engine a deploy updates: AGENT_ENGINE_ID / agent_engine.agent_engine_id when set, else the one engine
    labelled for this namespace and environment, else None (the deploy creates it). A fresh pipeline checkout has
    no local record, so the labels, not a file, are what make repeated deploys update instead of duplicate."""
    name = engine_name_from_config(cfg)
    if name:
        return name
    found = find_engines_by_labels(client, cfg)
    if len(found) > 1:
        raise DeployError(
            f"{len(found)} engines are labelled ns={cfg.namespace} env={cfg.env}: {found}. Keep one, delete the others "
            "(`uv run python scripts/resources.py` lists them), or set AGENT_ENGINE_ID to the one to use.")
    return found[0] if found else None


def resolve_engine_name(cfg, client) -> str:
    """The engine to operate on (smoke, traffic, remote eval, teardown, frontend): as existing_engine_name, loud if none."""
    name = existing_engine_name(client, cfg)
    if name:
        return name
    raise DeployError(
        f"no engine for namespace {cfg.namespace}, env={cfg.env} in {cfg.project}: deploy first "
        f"(`uv run python deployment/release.py && uv run python deployment/deploy.py --env {cfg.env} --release release.json`), or set AGENT_ENGINE_ID / agent_engine.agent_engine_id in config/envs/{cfg.env}.yaml")


# --------------------------------------------------------------------------------------------
# Vertex AI client (Agent Engine / Agent Runtime, v1beta1)
# --------------------------------------------------------------------------------------------

def make_client(project: str, location: str, credentials=None):
    """vertexai.Client pinned to v1beta1.

    google-cloud-aiplatform 1.165 prints a FutureWarning that vertexai.Client is deprecated in favour of
    agentplatform.Client; both resolve to the same _genai client (agentplatform/__init__.py lazily
    imports `._genai.client`). The warning is filtered here so CI logs stay readable.
    """
    warnings.filterwarnings("ignore", message=r".*vertexai\.Client class is deprecated.*", category=FutureWarning)
    import vertexai
    from google.genai.types import HttpOptions

    kwargs: dict[str, Any] = {"project": project, "location": location,
                              "http_options": HttpOptions(api_version=API_VERSION)}
    if credentials is not None:
        kwargs["credentials"] = credentials
    return vertexai.Client(**kwargs)


def client_for(cfg, credentials=None):
    return make_client(cfg.project, cfg.agent_engine["location"], credentials)


def get_engine(client, name: str):
    return client.agent_engines.get(name=name)


def list_revisions(client, engine_name: str) -> list[dict[str, Any]]:
    """[{name, create_time, state}] oldest first (runtimes.revisions.list, v1beta1)."""
    rows = []
    for rev in client.agent_engines.runtimes.revisions.list(name=engine_name):
        r = rev.api_resource
        rows.append({
            "name": r.name,
            "create_time": r.create_time.isoformat() if r.create_time else None,
            "state": str(r.state.value if hasattr(r.state, "value") else r.state) if r.state else None,
        })
    rows.sort(key=lambda x: x["create_time"] or "")
    return rows


def traffic_view(engine) -> dict[str, Any]:
    """Observed traffic config of an engine: {"mode": "always_latest"|"manual"|"unset", "targets": {rev: pct}}."""
    tc = engine.api_resource.traffic_config
    if tc is None:
        return {"mode": "unset", "targets": {}}
    if tc.traffic_split_manual is not None:
        targets = {t.runtime_revision_name: int(t.percent or 0) for t in (tc.traffic_split_manual.targets or [])}
        return {"mode": "manual", "targets": targets}
    if tc.traffic_split_always_latest is not None:
        return {"mode": "always_latest", "targets": {}}
    return {"mode": "unset", "targets": {}}


def manual_traffic_config(targets: dict[str, int]) -> dict[str, Any]:
    """Build the traffic_config dict for traffic_split_manual; refuses anything that does not sum to 100."""
    if not targets:
        raise DeployError("a manual traffic split needs at least one target")
    for name, pct in targets.items():
        if not isinstance(pct, int) or pct < 0 or pct > 100:
            raise DeployError(f"percent for {name} must be an integer 0-100, got {pct!r}")
    total = sum(targets.values())
    if total != 100:
        raise DeployError(f"traffic percentages must sum to 100, got {total}: {targets}")
    return {"traffic_split_manual": {"targets": [
        {"runtime_revision_name": name, "percent": pct} for name, pct in targets.items() if pct > 0
    ]}}


def always_latest_traffic_config() -> dict[str, Any]:
    return {"traffic_split_always_latest": {}}


def set_traffic(client, engine_name: str, traffic_config: dict[str, Any]):
    """PATCH traffic_config (update_mask=traffic_config). The SDK polls the LRO to completion."""
    engine = client.agent_engines.update(name=engine_name, config={"traffic_config": traffic_config})
    return engine


def assert_traffic(client, engine_name: str, expected: dict[str, int] | None) -> dict[str, Any]:
    """Re-read the engine and assert the observed split equals `expected` (None = always_latest)."""
    observed = traffic_view(get_engine(client, engine_name))
    if expected is None:
        if observed["mode"] != "always_latest":
            raise DeployError(f"expected traffic_split_always_latest, observed {observed}")
    else:
        # the API reports revision names with the project number; compare on the revision id
        want = {short_revision(k): v for k, v in expected.items() if v > 0}
        got = {short_revision(k): v for k, v in observed["targets"].items()}
        if observed["mode"] != "manual" or got != want:
            raise DeployError(f"traffic split not applied: expected {want}, observed {observed}")
    return observed


def short_revision(name: str) -> str:
    return name.rsplit("/", 1)[-1] if name else ""


# --------------------------------------------------------------------------------------------
# Deployment records
# --------------------------------------------------------------------------------------------

def engine_namespace_guard(engine, cfg) -> None:
    """Refuse to touch an engine that another namespace owns (or one created before namespaces existed)."""
    labels = dict(getattr(engine.api_resource, "labels", None) or {})
    owner = labels.get("ns")
    if owner != cfg.namespace:
        raise DeployError(
            f"{engine.api_resource.name} belongs to namespace {owner or '(none)'}, not {cfg.namespace}. In a shared project "
            f"that is someone else's engine: remove deployment/deployment_info.{cfg.namespace}.{cfg.env}.json and unset "
            "AGENT_ENGINE_ID to create your own.")


def deployment_info_path(env: str) -> Path:
    from agents.cymbal_store_ops.config import require_namespace

    return DEPLOYMENT_DIR / f"deployment_info.{require_namespace()}.{env}.json"


def read_deployment_info(env: str) -> dict[str, Any] | None:
    p = deployment_info_path(env)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def write_deployment_info(env: str, data: dict[str, Any]) -> Path:
    p = deployment_info_path(env)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return p


def read_release(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DeployError(f"release manifest {path} not found: run `uv run python deployment/release.py`")
    return json.loads(path.read_text())


def verify_release(release: dict[str, Any], *, strict: bool) -> None:
    """The checkout must be the release: same requirements digest and, when strict, the same clean commit."""
    req = REPO_ROOT / release["requirements"]
    if not req.exists() or sha256_file(req) != release["requirements_sha256"]:
        raise DeployError(f"{req} does not match release.json: rerun `uv run python deployment/release.py`")
    if not strict:
        return
    agent_dir = REPO_ROOT / "agents" / "cymbal_store_ops"
    current = {"git_sha": git_sha(), "prompt_version": sha256_tree(sorted((agent_dir / "prompts").glob("*.md"))),
               "config_version": sha256_tree(sorted((agent_dir / "config" / "envs").glob("*.yaml")))}
    if git_dirty() or any(current[k] != release[k] for k in current):
        raise DeployError("stale candidate: this checkout (commit, prompts or config) differs from release.json, or is dirty")


def print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))
