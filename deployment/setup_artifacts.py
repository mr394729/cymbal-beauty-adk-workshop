"""Provision only the namespaced private report bucket; dry-run unless --apply."""
from __future__ import annotations

import argparse
import json
import re

from google.cloud import storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--env", choices=["dev"], default="dev")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,20}", args.namespace):
        parser.error("Use a lowercase workshop namespace.")
    name = f"{args.project}-cymbal-artifacts-{args.namespace}-{args.env}"
    client = storage.Client(project=args.project)
    bucket = client.bucket(name)
    exists = bucket.exists()
    roles = {
        "roles/storage.objectCreator": [f"serviceAccount:store-ops-{args.env}-runtime@{args.project}.iam.gserviceaccount.com"],
        "roles/storage.objectViewer": [f"serviceAccount:store-ops-{args.env}-runtime@{args.project}.iam.gserviceaccount.com",
                                       f"serviceAccount:store-ops-frontend@{args.project}.iam.gserviceaccount.com"],
    }
    print(json.dumps({"bucket": name, "exists": exists, "apply": args.apply, "bindings": roles}, indent=2))
    if not args.apply:
        return
    if not exists:
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"
        bucket.labels = {"app": "cymbal-store-ops", "ns": args.namespace, "env": args.env}
        bucket = client.create_bucket(bucket, location=args.location)
    else:
        bucket.reload()
        if bucket.labels.get("ns") != args.namespace or bucket.labels.get("env") != args.env:
            raise RuntimeError("Existing artifact bucket has different namespace/environment labels.")
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"
        bucket.patch()
    policy = bucket.get_iam_policy(requested_policy_version=3)
    for role, members in roles.items():
        binding = next((b for b in policy.bindings if b["role"] == role and not b.get("condition")), None)
        if binding is None:
            policy.bindings.append({"role": role, "members": set(members)})
        else:
            binding["members"].update(members)
    bucket.set_iam_policy(policy)
    bucket.reload()
    assert bucket.iam_configuration.public_access_prevention == "enforced"
    assert bucket.iam_configuration.uniform_bucket_level_access_enabled
    print("Verified private bucket and scoped artifact grants.")


if __name__ == "__main__":
    main()
