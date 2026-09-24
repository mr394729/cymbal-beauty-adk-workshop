#!/usr/bin/env bash
# List the roles a principal holds on the project (direct project-level bindings).
#
#   bash skills/gcp-integration/scripts/whoami_iam.sh [--project PROJECT] [--sa SERVICE_ACCOUNT_EMAIL | --member MEMBER]
#
# Default principal = the active gcloud account. Dataset- and secret-level bindings are not project
# bindings; check them with `bq get-iam-policy` and `gcloud secrets get-iam-policy` (hints printed below).
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
MEMBER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --sa) MEMBER="serviceAccount:$2"; shift 2 ;;
    --member) MEMBER="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$PROJECT" ]] || { echo "ERROR: set GOOGLE_CLOUD_PROJECT or pass --project" >&2; exit 2; }
command -v gcloud >/dev/null || { echo "ERROR: gcloud not found" >&2; exit 2; }

if [[ -z "$MEMBER" ]]; then
  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
  [[ -n "$account" ]] || { echo "ERROR: no active gcloud account (gcloud auth login)" >&2; exit 1; }
  case "$account" in
    *.gserviceaccount.com) MEMBER="serviceAccount:$account" ;;
    *) MEMBER="user:$account" ;;
  esac
fi

echo "principal: $MEMBER"
echo "project:   $PROJECT"
roles="$(gcloud projects get-iam-policy "$PROJECT" --flatten='bindings[].members' \
  --filter="bindings.members:$MEMBER" --format='value(bindings.role)' 2>&1)" || {
  echo "ERROR: cannot read the IAM policy of $PROJECT (needs resourcemanager.projects.getIamPolicy):" >&2
  echo "$roles" >&2; exit 1; }
if [[ -z "$roles" ]]; then
  echo "no project-level roles for $MEMBER"
else
  echo "project-level roles:"; echo "$roles" | sed 's/^/  /'
fi
echo
echo "resource-level bindings to check separately:"
echo "  bq show --format=prettyjson $PROJECT:cymbal_beauty_${WORKSHOP_NAMESPACE:-<namespace>}_dev   # dataset access entries (READER)"
echo "  gcloud secrets get-iam-policy <secret> --project $PROJECT   # secretAccessor"
echo "  gcloud iam service-accounts get-iam-policy <sa-email>       # serviceAccountUser / workloadIdentityUser"
