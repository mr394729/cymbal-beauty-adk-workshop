"""Dev-only store-event infrastructure. Defaults to a reviewable plan; --apply performs it.

https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions
https://docs.cloud.google.com/firestore/docs/manage-databases
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import yaml


def run(args: list[str], *, capture=False):
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def present(args: list[str]) -> bool:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode == 0:
        return True
    if (
        "NOT_FOUND" in result.stderr
        or "not found" in result.stderr.lower()
        or "does not exist" in result.stderr.lower()
    ):
        return False
    raise RuntimeError(result.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--runtime-sa", required=True)
    ap.add_argument("--frontend-sa", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--out", default="build/events-deployment.json")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", args.namespace):
        ap.error("namespace must be 3–12 lowercase letters/digits")
    project, ns, region = args.project, args.namespace, args.region
    service = f"cymbal-store-events-{ns}-dev"
    database = f"cymbal-events-{ns}-dev"
    push_sa_id = f"events-{ns}-dev-push"
    push_sa = f"{push_sa_id}@{project}.iam.gserviceaccount.com"
    plan = {
        "project": project,
        "region": region,
        "database": database,
        "service": service,
        "topic": service,
        "subscription": service + "-push",
        "push_sa": push_sa,
        "runtime_sa": args.runtime_sa,
        "frontend_sa": args.frontend_sa,
        "image": args.image,
        "engine": args.engine,
        "applied": args.apply,
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.apply:
        return
    run(
        [
            "gcloud",
            "services",
            "enable",
            "firestore.googleapis.com",
            "pubsub.googleapis.com",
            "run.googleapis.com",
            "--project",
            project,
            "--quiet",
        ]
    )
    if not present(
        [
            "gcloud",
            "firestore",
            "databases",
            "describe",
            "--database",
            database,
            "--project",
            project,
            "--format=json",
        ]
    ):
        run(
            [
                "gcloud",
                "firestore",
                "databases",
                "create",
                "--database",
                database,
                "--location",
                region,
                "--type",
                "firestore-native",
                "--project",
                project,
                "--quiet",
            ]
        )
    if not present(
        ["gcloud", "pubsub", "topics", "describe", service, "--project", project, "--format=json"]
    ):
        run(
            [
                "gcloud",
                "pubsub",
                "topics",
                "create",
                service,
                "--project",
                project,
                "--labels",
                f"ns={ns},env=dev",
                "--quiet",
            ]
        )
    if not present(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "describe",
            push_sa,
            "--project",
            project,
            "--format=json",
        ]
    ):
        run(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "create",
                push_sa_id,
                "--project",
                project,
                "--quiet",
            ]
        )
    condition = (
        f'expression=resource.name=="projects/{project}/databases/{database}",title={database}'
    )
    for principal in (args.frontend_sa, args.runtime_sa):
        run(
            [
                "gcloud",
                "projects",
                "add-iam-policy-binding",
                project,
                "--member",
                "serviceAccount:" + principal,
                "--role",
                "roles/datastore.user",
                "--condition",
                condition,
                "--quiet",
                "--format=none",
            ]
        )
    run(
        [
            "gcloud",
            "pubsub",
            "topics",
            "add-iam-policy-binding",
            service,
            "--project",
            project,
            "--member",
            "serviceAccount:" + args.frontend_sa,
            "--role",
            "roles/pubsub.publisher",
            "--quiet",
            "--format=none",
        ]
    )
    number = run(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"], capture=True
    )
    run(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            push_sa,
            "--project",
            project,
            "--member",
            f"serviceAccount:service-{number}@gcp-sa-pubsub.iam.gserviceaccount.com",
            "--role",
            "roles/iam.serviceAccountTokenCreator",
            "--quiet",
            "--format=none",
        ]
    )
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import firestore_admin_v1 as admin

    client = admin.FirestoreAdminClient()
    parent = f"projects/{project}/databases/{database}/collectionGroups/event_jobs"
    index = admin.Index(
        query_scope=admin.Index.QueryScope.COLLECTION,
        fields=[
            admin.Index.IndexField(
                field_path="owner", order=admin.Index.IndexField.Order.ASCENDING
            ),
            admin.Index.IndexField(
                field_path="created_at", order=admin.Index.IndexField.Order.DESCENDING
            ),
        ],
    )
    existing = list(client.list_indexes(parent=parent))
    if not any(
        [(f.field_path, f.order) for f in i.fields[:2]]
        == [(f.field_path, f.order) for f in index.fields]
        for i in existing
    ):
        try:
            client.create_index(parent=parent, index=index).result(timeout=600)
        except AlreadyExists:
            pass
    if args.build:
        config = {
            "steps": [
                {
                    "name": "gcr.io/cloud-builders/docker",
                    "args": [
                        "build",
                        "-f",
                        "services/store_events/Dockerfile",
                        "-t",
                        args.image,
                        ".",
                    ],
                }
            ],
            "images": [args.image],
            "timeout": "1200s",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as file:
            yaml.safe_dump(config, file)
            file.flush()
            run(
                [
                    "gcloud",
                    "builds",
                    "submit",
                    ".",
                    "--project",
                    project,
                    "--region",
                    region,
                    "--config",
                    file.name,
                    "--quiet",
                ]
            )
    url = f"https://{service}-{number}.{region}.run.app"
    environment = {
        "GOOGLE_CLOUD_PROJECT": project,
        "WORKSHOP_NAMESPACE": ns,
        "STORE_OPS_ENV": "dev",
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "GOOGLE_CLOUD_LOCATION": "global",
        "EVENTS_PROJECT": project,
        "EVENTS_DATABASE": database,
        "EVENTS_COLLECTION": "event_jobs",
        "EVENTS_TOPIC": service,
        "EVENTS_ENGINE": args.engine,
        "EVENTS_PUSH_AUDIENCE": url,
        "EVENTS_PUSH_SA": push_sa,
    }
    run(
        [
            "gcloud",
            "run",
            "deploy",
            service,
            "--project",
            project,
            "--region",
            region,
            "--image",
            args.image,
            "--service-account",
            args.runtime_sa,
            "--no-allow-unauthenticated",
            "--timeout",
            "300",
            "--concurrency",
            "4",
            "--max-instances",
            "3",
            "--memory",
            "1Gi",
            "--cpu",
            "1",
            "--set-env-vars",
            ",".join(f"{k}={v}" for k, v in environment.items()),
            "--labels",
            f"ns={ns},env=dev",
            "--quiet",
        ]
    )
    run(
        [
            "gcloud",
            "run",
            "services",
            "add-iam-policy-binding",
            service,
            "--project",
            project,
            "--region",
            region,
            "--member",
            "serviceAccount:" + push_sa,
            "--role",
            "roles/run.invoker",
            "--quiet",
            "--format=none",
        ]
    )
    sub = service + "-push"
    verb = (
        "update"
        if present(
            [
                "gcloud",
                "pubsub",
                "subscriptions",
                "describe",
                sub,
                "--project",
                project,
                "--format=json",
            ]
        )
        else "create"
    )
    command = [
        "gcloud",
        "pubsub",
        "subscriptions",
        verb,
        sub,
        "--project",
        project,
        "--push-endpoint",
        url + "/push",
        "--push-auth-service-account",
        push_sa,
        "--push-auth-token-audience",
        url,
        "--ack-deadline",
        "300",
        "--quiet",
    ]
    if verb == "create":
        command += ["--topic", service, "--min-retry-delay", "10s", "--max-retry-delay", "60s"]
    run(command)
    plan.update(
        url=url,
        frontend_env={
            k: environment[k]
            for k in ("EVENTS_PROJECT", "EVENTS_DATABASE", "EVENTS_COLLECTION", "EVENTS_TOPIC")
        },
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
