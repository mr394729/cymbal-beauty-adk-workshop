"""Agent Identity for a deployed engine: the IAM the agent's own principal needs, granted after the engine exists.

With `agent_engine.identity: agent` in config/envs/<env>.yaml the engine is created with `identity_type:
AGENT_IDENTITY` and no service account. Google Cloud then issues the engine a SPIFFE identity, reported as
`spec.effectiveIdentity`; IAM bindings use it as `principal://<effectiveIdentity>`. The identity does not exist
until the engine does, so a first deploy is two steps: create the engine without code, bind these roles, then
update it with the package (deploy.py does this when the option is on).

    uv run python deployment/agent_identity.py --env dev --engine projects/P/locations/L/reasoningEngines/ID [--apply]

Docs: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment._common import DeployError, load_config, staging_bucket  # noqa: E402

# The same project roles the runtime service account gets in iam/setup_wif.sh.
PROJECT_ROLES = ["roles/aiplatform.user", "roles/bigquery.jobUser", "roles/cloudtrace.agent", "roles/logging.logWriter",
                 "roles/monitoring.metricWriter", "roles/discoveryengine.viewer", "roles/modelarmor.user",
                 "roles/serviceusage.serviceUsageConsumer"]


def run(cmd: list[str], apply: bool) -> None:
    print(("  " if apply else "  (dry run) ") + " ".join(cmd))
    if apply:
        subprocess.run(cmd, check=True, capture_output=True, text=True)


def effective_identity(engine_name: str) -> str:
    """spec.effectiveIdentity of the engine: a service account email, or an agents.global… path for Agent Identity."""
    out = subprocess.run(["gcloud", "ai", "reasoning-engines", "describe", engine_name, "--format=value(spec.effectiveIdentity)"],
                         capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        # the gcloud surface lags the API; read the resource directly
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        location = engine_name.split("/locations/")[1].split("/")[0]
        resp = AuthorizedSession(credentials).get(f"https://{location}-aiplatform.googleapis.com/v1beta1/{engine_name}", timeout=60)
        resp.raise_for_status()
        return resp.json()["spec"]["effectiveIdentity"]
    return out.stdout.strip()


def principal_for(identity: str) -> str:
    if identity.endswith(".gserviceaccount.com"):
        raise DeployError(f"{identity} is a service account; this engine does not use Agent Identity "
                          "(set agent_engine.identity: agent before the engine is created; an existing engine cannot be switched)")
    return f"principal://{identity}"


def bind(cfg, engine_name: str, *, apply: bool) -> str:
    principal = principal_for(effective_identity(engine_name))
    project, dataset = cfg.project, cfg.bigquery.dataset
    print(f"agent identity: {principal}")
    for role in PROJECT_ROLES:
        run(["gcloud", "projects", "add-iam-policy-binding", project, f"--member={principal}", f"--role={role}", "--condition=None", "--quiet"], apply)
    # the package is read from the staging bucket at deploy time (legacy bucket roles are not allowed for agent identities)
    run(["gcloud", "storage", "buckets", "add-iam-policy-binding", staging_bucket(cfg), f"--member={principal}", "--role=roles/storage.objectViewer"], apply)
    # dataset reader plus writes to store_tasks only, as iam/setup_wif.sh grants the service account
    print(f"  dataset {dataset}: READER for the principal, dataEditor on store_tasks (bq CLI, see iam/setup_wif.sh for the exact form)")
    if apply:
        subprocess.run(["bq", "add-iam-policy-binding", f"--member={principal}", "--role=roles/bigquery.dataViewer", f"{project}:{dataset}"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["bq", "add-iam-policy-binding", f"--member={principal}", "--role=roles/bigquery.dataEditor", f"{project}:{dataset}.store_tasks"],
                       check=True, capture_output=True, text=True)
    return principal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", required=True)
    parser.add_argument("--engine", required=True, help="projects/P/locations/L/reasoningEngines/ID")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.env)
    bind(cfg, args.engine, apply=args.apply)
    if not args.apply:
        print("read only: pass --apply to bind the roles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
