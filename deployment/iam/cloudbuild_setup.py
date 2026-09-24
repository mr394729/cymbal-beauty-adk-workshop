"""Plan, apply and verify namespace-scoped Cloud Build triggers.

Defaults to an offline plan with disabled triggers. Connection OAuth must already
be complete before --apply can link the repository. --enable is explicit; this
script never starts a build or grants promotion approval.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path

OPTIONAL_RUNTIME = ("SOP_DATA_STORE", "MEMORY_BANK_ENGINE", "CYMBAL_MCP_URL", "CYMBAL_MCP_AUDIENCE",
                    "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT", "CYMBAL_MCP_SCOPE_SECRET", "MODEL_ARMOR_TEMPLATE")


def read_runtime_settings(path):
    """Read assignments without executing shell or accepting secret values."""
    if not path:
        return {}
    values = {}
    for line in Path(path).read_text().splitlines():
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        if parts[0] == "export":
            parts = parts[1:]
        if len(parts) != 1 or "=" not in parts[0]:
            raise ValueError("Runtime settings must contain plain KEY=value assignments")
        key, value = parts[0].split("=", 1)
        if key in {"CYMBAL_MCP_SCOPE_KEY", "TOKEN", "PASSWORD", "GOOGLE_APPLICATION_CREDENTIALS"}:
            raise ValueError("Runtime settings accept secret references, never credential values")
        if key in OPTIONAL_RUNTIME:
            values[key] = value
    mcp = [values.get(k, "") for k in OPTIONAL_RUNTIME if k.startswith("CYMBAL_MCP_")]
    if any(mcp) and not all(mcp):
        raise ValueError("All four MCP connection settings are required together")
    if values.get("CYMBAL_MCP_SCOPE_SECRET") and not re.fullmatch(r"[A-Za-z0-9_-]+:[0-9]+", values["CYMBAL_MCP_SCOPE_SECRET"]):
        raise ValueError("MCP signing secret must be a pinned secret-id:version reference")
    return values


def plan(project, owner, repository, namespace, region="us-central1", connection="github", *, enable=False,
         scope="dev", eval_namespace=None, runtime_settings=None):
    for value, pattern in ((project, r"[a-z][a-z0-9-]{4,61}[a-z0-9]"),
                           (owner, r"[A-Za-z0-9-]+"), (repository, r"[A-Za-z0-9_.-]+"),
                           (namespace, r"[a-z][a-z0-9]{2,11}"), (connection, r"[A-Za-z0-9_-]+"),
                           (region, r"[a-z]+-[a-z]+[0-9]")):
        if not re.fullmatch(pattern, value):
            raise ValueError(f"Invalid resource identifier: {value!r}")
    if eval_namespace and not re.fullmatch(r"[a-z][a-z0-9]{2,11}", eval_namespace):
        raise ValueError("Invalid evaluation namespace")
    if scope not in {"dev", "ladder"}:
        raise ValueError("scope must be dev or ladder")
    base = f"projects/{project}/locations/{region}/connections/{connection}"
    repo_resource = f"{base}/repositories/{repository}"
    specs = [("ci", "ci", "pr", "cicd-evaluator", {}),
             ("deploy-dev", "deploy", "push", "cicd-deployer-dev", {"_ENV": "dev"})]
    if scope == "ladder":
        specs += [("deploy-preprod", "deploy", "manual", "cicd-deployer-preprod", {"_ENV": "preprod"}),
                  ("prod-canary", "deploy", "manual", "cicd-deployer-prod", {"_ENV": "prod"}),
                  ("prod-promote-10", "promote", "manual", "cicd-deployer-prod", {"_ENV": "prod", "_PERCENT": "10"}),
                  ("prod-promote-100", "promote", "manual", "cicd-deployer-prod", {"_ENV": "prod", "_PERCENT": "100"}),
                  ("prod-rollback", "rollback", "manual", "cicd-deployer-prod", {"_ENV": "prod"})]
    triggers = []
    for name, config, event, account, substitutions in specs:
        trigger = {"name": f"{namespace}-{name}", "description": f"Cymbal {namespace}: {name}",
                   "disabled": not enable, "tags": ["cymbal-store-ops", f"namespace-{namespace}"],
                   "serviceAccount": f"projects/{project}/serviceAccounts/{account}@{project}.iam.gserviceaccount.com",
                   "substitutions": {"_NAMESPACE": namespace, **substitutions},
                   "approvalConfig": {"approvalRequired": event == "manual"}}
        if name == "ci":
            trigger["substitutions"].update({"_EVAL_NAMESPACE": eval_namespace or namespace,
                                               "_REPO_RESOURCE": repo_resource, "_RISK_EVENT": "pr"})
        if name == "deploy-dev":
            trigger["substitutions"].update({"_" + k: v for k, v in (runtime_settings or {}).items()})
        if event == "manual":
            trigger.update({"eventType": "MANUAL",
                "sourceToBuild": {"repository": repo_resource, "ref": "refs/heads/main", "repoType": "GITHUB"},
                "gitFileSource": {"path": f"cloudbuild/{config}.yaml", "repository": repo_resource, "repoType": "GITHUB"}})
        else:
            event_filter = {"pullRequest": {"branch": "^main$", "commentControl": "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"}} if event == "pr" else {"push": {"branch": "^main$"}}
            trigger.update({"filename": f"cloudbuild/{config}.yaml",
                            "repositoryEventConfig": {"repository": repo_resource, "repositoryType": "GITHUB", **event_filter}})
        triggers.append(trigger)
    return {"project": project, "region": region, "connection": base, "repository": repo_resource,
            "remote_uri": f"https://github.com/{owner}/{repository}.git", "triggers": triggers,
            "read_token_access": {"scope": "dedicated_connection", "resource": base,
                "role": "roles/cloudbuild.readTokenAccessor",
                "member": f"serviceAccount:cicd-evaluator@{project}.iam.gserviceaccount.com"}}


def gcloud(*args):
    result = subprocess.run(["gcloud", *args, "--format=json", "--quiet"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout or "{}")


def verify_definition(expected, actual):
    """Compare owned fields while allowing service defaults and output metadata."""
    def matches(want, got):
        if isinstance(want, dict):
            return isinstance(got, dict) and all(matches(v, got.get(k, False if v is False else None)) for k, v in want.items())
        return want == got
    differences = [key for key, value in expected.items()
                   if not matches(value, actual.get(key, False if value is False else {} if isinstance(value, dict) else None))]
    for key in ("github", "triggerTemplate", "pubsubConfig", "webhookConfig", "repositoryEventConfig", "sourceToBuild", "gitFileSource", "filename"):
        if key not in expected and actual.get(key):
            differences.append(key)
    return differences


def normalize_project(value, project, number):
    """Canonicalize only this project's ID/number aliases, never another project."""
    if isinstance(value, str):
        return value.replace(f"projects/{number}/", f"projects/{project}/")
    if isinstance(value, list):
        return [normalize_project(v, project, number) for v in value]
    if isinstance(value, dict):
        return {k: normalize_project(v, project, number) for k, v in value.items()}
    return value


def validate_dedicated_repository(repositories, spec, *, require_linked=False):
    """Read-token IAM is connection-scoped: this connection must hold only this repo."""
    expected_id = spec["repository"].rsplit("/", 1)[-1]
    if len(repositories) > 1:
        raise RuntimeError("Workshop connection contains other repositories; refusing connection-wide token access")
    for repository in repositories:
        if (repository.get("name", "").rsplit("/", 1)[-1] != expected_id or
                repository.get("remoteUri", "").removesuffix(".git") != spec["remote_uri"].removesuffix(".git")):
            raise RuntimeError("Workshop connection contains a different repository; use its dedicated connection")
    if require_linked and len(repositories) != 1:
        raise RuntimeError("Expected workshop repository is not linked")


def ensure_connection_read_access(spec, repositories, out, *, apply=False):
    validate_dedicated_repository(repositories, spec, require_linked=True)
    flags = ("--project=" + spec["project"], "--region=" + spec["region"])
    member = f"serviceAccount:cicd-evaluator@{spec['project']}.iam.gserviceaccount.com"
    role = "roles/cloudbuild.readTokenAccessor"
    if apply:
        gcloud("builds", "connections", "add-iam-policy-binding", spec["connection"],
               "--member=" + member, "--role=" + role, *flags)
    policy = gcloud("builds", "connections", "get-iam-policy", spec["connection"], *flags)
    verified = any(binding.get("role") == role and member in binding.get("members", [])
                   and not binding.get("condition") for binding in policy.get("bindings", []))
    result = {"resource": spec["connection"], "scope": "connection", "dedicated_repository": spec["repository"],
              "member": member, "role": role, "verified": verified}
    (out / "read-token-access.json").write_text(json.dumps(result, indent=2) + "\n")
    if not verified:
        raise RuntimeError("Dedicated connection read-token access is missing; rerun setup with --apply")
    return result


def configure(spec, out, *, apply=False):
    project, region = spec["project"], spec["region"]
    flags = ("--project=" + project, "--region=" + region)
    connection = gcloud("builds", "connections", "describe", spec["connection"], *flags)
    state = connection.get("installationState", {})
    (out / "connection.json").write_text(json.dumps(connection, indent=2) + "\n")
    if state.get("stage") != "COMPLETE":
        raise RuntimeError(f"Connection is {state.get('stage', 'unknown')}. Required account authorization: {state.get('actionUri', 'inspect connection.json')}")
    repos = gcloud("builds", "repositories", "list", "--connection=" + spec["connection"], *flags)
    validate_dedicated_repository(repos, spec)
    found = next((r for r in repos if r["name"].split("/repositories/")[-1] == spec["repository"].split("/repositories/")[-1]), None)
    if found and found.get("remoteUri", "").removesuffix(".git") != spec["remote_uri"].removesuffix(".git"):
        raise RuntimeError("Existing repository resource points to a different GitHub repository")
    if not found:
        if not apply:
            raise RuntimeError("Repository is not yet linked")
        found = gcloud("builds", "repositories", "create", spec["repository"], "--connection=" + spec["connection"],
                       "--remote-uri=" + spec["remote_uri"], *flags)
    # Re-read after linking and before the connection-scoped IAM grant.
    repos = gcloud("builds", "repositories", "list", "--connection=" + spec["connection"], *flags)
    token_access = ensure_connection_read_access(spec, repos, out, apply=apply)
    project_number = gcloud("projects", "describe", project)["projectNumber"]
    existing = normalize_project(gcloud("builds", "triggers", "list", *flags), project, project_number)
    by_name = {t["name"]: t for t in existing}
    for trigger in spec["triggers"]:
        current = by_name.get(trigger["name"])
        if current and not verify_definition(trigger, current):
            continue
        if not apply:
            continue
        definition = dict(trigger)
        if current:
            # Omitting a settings file must not erase previously configured
            # optional services on the next trigger update.
            existing_options = {k: v for k, v in current.get("substitutions", {}).items()
                                if k.removeprefix("_") in OPTIONAL_RUNTIME}
            definition["substitutions"] = {**existing_options, **definition["substitutions"]}
        if current:
            definition["id"] = current["id"]
        path = out / f"{trigger['name']}.json"
        path.write_text(json.dumps(definition, indent=2) + "\n")
        gcloud("builds", "triggers", "import", "--source=" + str(path), *flags)
    actual = normalize_project(gcloud("builds", "triggers", "list", *flags), project, project_number)
    by_name = {t["name"]: t for t in actual}
    results = [{"name": t["name"], "id": by_name.get(t["name"], {}).get("id"),
                "differences": verify_definition(t, by_name.get(t["name"], {}))} for t in spec["triggers"]]
    (out / "verification.json").write_text(json.dumps({"connection_complete": True, "repository": found,
        "triggers": results, "read_token_access": token_access, "builds_started": 0}, indent=2) + "\n")
    if any(r["differences"] for r in results):
        raise RuntimeError("Trigger configuration differs; inspect verification.json")
    print(json.dumps({"verified_triggers": len(results), "builds_started": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "owner", "repository", "namespace"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--connection", default="github")
    parser.add_argument("--eval-namespace")
    parser.add_argument("--runtime-settings", type=Path, help="Dev optional-service assignments; pinned secret references only")
    parser.add_argument("--scope", choices=("dev", "ladder"), default="dev")
    parser.add_argument("--out", type=Path, default=Path("build/cloudbuild-setup"))
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    spec = plan(args.project, args.owner, args.repository, args.namespace, args.region, args.connection,
                enable=args.enable, scope=args.scope, eval_namespace=args.eval_namespace,
                runtime_settings=read_runtime_settings(args.runtime_settings))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "plan.json").write_text(json.dumps(spec, indent=2) + "\n")
    for trigger in spec["triggers"]:
        (args.out / f"{trigger['name']}.json").write_text(json.dumps(trigger, indent=2) + "\n")
    print(json.dumps({"plan": str(args.out / "plan.json"), "triggers": len(spec["triggers"]),
                      "enabled": args.enable, "apply": args.apply}))
    if args.apply or args.verify:
        configure(spec, args.out, apply=args.apply)


if __name__ == "__main__":
    main()
