"""Build and deploy one IAM-protected MCP service. Default: print the plan only."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def command(args, apply=False):
    print(shlex.join(args), flush=True)
    if apply:
        subprocess.run(args, check=True)


def json_command(args):
    return json.loads(subprocess.check_output(args, text=True))


def plan(args):
    service = f"cymbal-store-mcp-{args.namespace}-{args.env}"
    env = ",".join([f"GOOGLE_CLOUD_PROJECT={args.project}", f"WORKSHOP_NAMESPACE={args.namespace}",
        f"STORE_OPS_ENV={args.env}", f"CYMBAL_MCP_AUDIENCE={args.audience}",
        f"CYMBAL_MCP_TRUSTED_CALLERS={args.caller_service_account}", "STORE_OPS_PREWARM=0"])
    return ["gcloud", "run", "deploy", service, "--project", args.project, "--region", args.region,
        "--image", args.image, "--service-account", args.runtime_service_account,
        "--no-allow-unauthenticated", "--add-custom-audiences", args.audience,
        "--set-env-vars", env, "--set-secrets", f"CYMBAL_MCP_SCOPE_KEY={args.scope_secret}",
        "--min-instances", "1", "--max-instances", "3", "--concurrency", "20",
        "--cpu", "1", "--memory", "1Gi", "--timeout", "120",
        "--labels", f"app=cymbal-store-mcp,ns={args.namespace},env={args.env}", "--quiet"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "namespace", "image", "audience", "runtime-service-account",
                 "caller-service-account", "scope-secret"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--env", choices=["dev"], default="dev")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", args.namespace):
        parser.error("Namespace must be 3–12 lowercase letters/digits, starting with a letter.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+:[1-9][0-9]*", args.scope_secret):
        parser.error("--scope-secret must be SECRET_NAME:NUMERIC_VERSION, never latest.")
    if not args.audience.startswith("https://") or "," in args.audience or args.audience.endswith("/"):
        parser.error("--audience must be a Cloud Run HTTPS origin without a trailing slash.")
    deploy = plan(args)
    if args.build:
        # Upload only these two code trees, not .env, credentials, data/out or build artifacts.
        if args.apply:
            with tempfile.TemporaryDirectory(prefix="cymbal-mcp-build-") as temp:
                root = Path(temp)
                ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", ".adk", "build")
                shutil.copytree(args.repo / "agents", root / "agents", ignore=ignore)
                shutil.copytree(args.repo / "services/store_mcp", root / "services/store_mcp", ignore=ignore)
                config = {"steps": [{"name": "gcr.io/cloud-builders/docker",
                    "args": ["build", "-f", "services/store_mcp/Dockerfile", "-t", args.image, "."]}],
                    "images": [args.image]}
                (root / "cloudbuild.json").write_text(json.dumps(config))
                command(["gcloud", "builds", "submit", str(root), "--config", str(root / "cloudbuild.json"),
                    "--project", args.project, "--region", args.region, "--quiet"], True)
        else:
            print("BUILD: isolated context containing agents/ and services/store_mcp/ only.")
    service = f"cymbal-store-mcp-{args.namespace}-{args.env}"
    if args.apply:
        # Existing public access must be addressed explicitly, not left behind by an update.
        matches = json_command(["gcloud", "run", "services", "list", "--project", args.project,
            "--region", args.region, "--filter", f"metadata.name={service}", "--format=json"])
        if matches:
            policy = json_command(["gcloud", "run", "services", "get-iam-policy", service,
                "--project", args.project, "--region", args.region, "--format=json"])
            if any(member in {"allUsers", "allAuthenticatedUsers"} for binding in policy.get("bindings", [])
                   for member in binding.get("members", [])):
                raise SystemExit("Existing service has public IAM members; resolve those explicitly before deployment.")
    command(deploy, args.apply)
    command(["gcloud", "run", "services", "add-iam-policy-binding", service,
        "--project", args.project, "--region", args.region, "--member",
        f"serviceAccount:{args.caller_service_account}", "--role", "roles/run.invoker", "--quiet"], args.apply)
    if args.apply:
        policy = json_command(["gcloud", "run", "services", "get-iam-policy", service,
            "--project", args.project, "--region", args.region, "--format=json"])
        assert not any(member in {"allUsers", "allAuthenticatedUsers"} for binding in policy.get("bindings", [])
                       for member in binding.get("members", [])), "Service IAM is public."
        service_info = json_command(["gcloud", "run", "services", "describe", service,
            "--project", args.project, "--region", args.region, "--format=json"])
        print(json.dumps({"service": service, "status_url": service_info["status"]["url"],
                          "client_url": args.audience + "/mcp", "iam_checked": True}))
    print("Registration and authenticated tool probes are separate: use mcp_probe.py then mcp_register.py.")


if __name__ == "__main__":
    main()
