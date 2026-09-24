#!/usr/bin/env bash
# Remove the Cymbal Beauty BigQuery dataset for one environment.
#
#   data/teardown.sh --env dev [--project PROJECT] [--namespace NS] [--yes]
#
# Deletes <project>.cymbal_beauty_<ns>_<env> with all its tables (your namespace only). Refuses to run without --yes so it is never
# triggered by accident. Deployed agents are torn down separately with:
#   uv run python deployment/teardown.py --env <env>
set -euo pipefail
# Settings from the repository's .env fill in only variables that are not already set, so a value on the command
# line (GOOGLE_CLOUD_PROJECT=... WORKSHOP_NAMESPACE=... bash <script>) always wins.
REPO_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"
if [[ -f "$REPO_ENV" ]]; then
  while IFS='=' read -r key value; do
    value="${value%\"}"; value="${value#\"}"
    if [[ -z "${!key:-}" ]]; then export "$key=$value"; fi
  done < <(grep -E '^[A-Z_][A-Z0-9_]*=' "$REPO_ENV")
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-}"; NS="${WORKSHOP_NAMESPACE:-}"; ENV_NAME=""; BACKEND="bigquery"; YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --namespace) NS="$2"; shift 2 ;;
    --env)     ENV_NAME="$2"; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    --yes)     YES=1; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$ENV_NAME" ]] || { echo "ERROR: --env is required (dev|preprod|prod)" >&2; exit 2; }
[[ -n "$NS" ]] || { echo "ERROR: WORKSHOP_NAMESPACE is not set: run \`uv run python scripts/namespace.py\` (or pass --namespace)" >&2; exit 2; }
[[ "$YES" == 1 ]] || { echo "Refusing to delete without --yes. This removes cymbal_beauty_${NS}_${ENV_NAME}." >&2; exit 2; }
if [[ "$BACKEND" != "bigquery" ]]; then
  echo "ERROR: --backend must be bigquery (got '$BACKEND')" >&2; exit 2
fi
[[ -n "$PROJECT" ]] || { echo "ERROR: GOOGLE_CLOUD_PROJECT is not set (or pass --project)" >&2; exit 2; }
ds="cymbal_beauty_${NS}_${ENV_NAME}"
if bq --project_id="$PROJECT" ls -d 2>/dev/null | awk '{print $1}' | grep -qx "$ds"; then
  bq --project_id="$PROJECT" rm -r -f -d "$PROJECT:$ds" && echo "deleted $PROJECT:$ds"
else
  echo "not present: $PROJECT:$ds"
fi
