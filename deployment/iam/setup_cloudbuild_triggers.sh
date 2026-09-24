#!/usr/bin/env bash
# Offline plan by default. Add --apply to configure; --enable arms triggers.
# setup_cloudbuild_triggers.sh PROJECT GH_OWNER GH_REPO NAMESPACE [--scope ladder] [--apply] [--enable]
set -euo pipefail
PROJECT="${1:?PROJECT}"; OWNER="${2:?GH_OWNER}"; REPO="${3:?GH_REPO}"; NS="${4:?NAMESPACE}"
shift 4
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/cloudbuild_setup.py" --project "$PROJECT" --owner "$OWNER" \
  --repository "$REPO" --namespace "$NS" "$@"
