"""Environment configuration for the Cymbal Beauty store-operations agents.

Precedence (highest first): process environment → config/envs/<env>.yaml → nothing (loud error).
The project id is never read from YAML: it always comes from GOOGLE_CLOUD_PROJECT.

Every resource name carries WORKSHOP_NAMESPACE, so twenty people can work in one shared project without
touching each other's datasets or engines: dataset `cymbal_beauty_<namespace>_<env>`, engine
`cymbal-store-ops-<namespace>-<env>`, job label `ns=<namespace>`. `uv run python scripts/namespace.py` writes it into .env.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)

VALID_FAULTS = ("none", "stale_stock", "stale_backlog")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]{2,11}$")


@dataclass(frozen=True)
class DataLimits:
    max_query_result_rows: int = 50
    maximum_bytes_billed: int = 104_857_600
    statement_timeout_s: int = 60


@dataclass(frozen=True)
class BigQueryConfig:
    dataset: str
    location: str
    job_labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvConfig:
    env: str
    project: str
    namespace: str
    model: str
    model_location: str
    thinking_level: str
    fault: str
    data: DataLimits
    bigquery: BigQueryConfig
    store_tasks_require_confirmation: bool
    agent_engine: dict
    secret_env_vars: dict
    plan_writer_thinking_level: str | None = None  # the briefing writer alone; None = thinking_level

    @property
    def dialect(self) -> str:
        return "BigQuery Standard SQL"

    @property
    def engine_display_name(self) -> str:
        return engine_display_name(self.namespace, self.env)


def dataset_name(namespace: str, env: str) -> str:
    return f"cymbal_beauty_{namespace}_{env}"


def engine_display_name(namespace: str, env: str) -> str:
    return f"cymbal-store-ops-{namespace}-{env}"


def require_namespace() -> str:
    """WORKSHOP_NAMESPACE, validated. Never derived here: `uv run python scripts/namespace.py` writes it once, visibly, into .env."""
    ns = os.environ.get("WORKSHOP_NAMESPACE", "").strip()
    if not ns:
        raise RuntimeError(
            "WORKSHOP_NAMESPACE is not set. Run `uv run python scripts/namespace.py` (it writes a short id derived from your sign-in "
            "into .env) or set WORKSHOP_NAMESPACE=<3-12 lowercase letters or digits> in .env. It keeps your datasets "
            "and engines apart from everyone else's in a shared project.")
    if not NAMESPACE_RE.match(ns):
        raise RuntimeError(f"WORKSHOP_NAMESPACE={ns!r} must be 3-12 lowercase letters or digits, starting with a letter.")
    return ns


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("your-"):
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and set it (no defaults are assumed).")
    return value


@cache
def load_env_config(env: str | None = None) -> EnvConfig:
    env = env or os.environ.get("STORE_OPS_ENV", "dev")
    path = AGENT_DIR / "config" / "envs" / f"{env}.yaml"
    if not path.exists():
        raise RuntimeError(f"Unknown STORE_OPS_ENV={env!r}: {path} does not exist (dev|preprod|prod).")
    raw = yaml.safe_load(path.read_text()) or {}
    project = _require("GOOGLE_CLOUD_PROJECT")
    namespace = require_namespace()
    fault = os.environ.get("STORE_OPS_FAULT", "none") or "none"
    if fault not in VALID_FAULTS:
        raise RuntimeError(f"STORE_OPS_FAULT={fault!r} is not one of {VALID_FAULTS}.")
    d = raw.get("data", {})
    bq = raw.get("bigquery", {})
    return EnvConfig(
        env=env,
        project=project,
        namespace=namespace,
        model=os.environ.get("MODEL", raw.get("model", "gemini-3.8-flash")),
        model_location=raw.get("model_location", "global"),   # pinned on the model client, not read from the runtime env
        thinking_level=os.environ.get("THINKING_LEVEL", raw.get("thinking_level", "medium")),
        plan_writer_thinking_level=os.environ.get("PLAN_WRITER_THINKING_LEVEL") or raw.get("plan_writer_thinking_level") or None,
        fault=fault,
        data=DataLimits(
            max_query_result_rows=int(d.get("max_query_result_rows", 50)),
            maximum_bytes_billed=int(d.get("maximum_bytes_billed", 104_857_600)),
            statement_timeout_s=int(d.get("statement_timeout_s", 60)),
        ),
        bigquery=BigQueryConfig(
            dataset=dataset_name(namespace, env),
            location=os.environ.get("BQ_LOCATION", "US"),
            job_labels={**{str(k): str(v) for k, v in (bq.get("job_labels") or {}).items()}, "ns": namespace},
        ),
        store_tasks_require_confirmation=bool((raw.get("store_tasks") or {}).get("require_confirmation", True)),
        agent_engine=dict(raw.get("agent_engine") or {}),
        secret_env_vars=dict(raw.get("secret_env_vars") or {}),
    )
