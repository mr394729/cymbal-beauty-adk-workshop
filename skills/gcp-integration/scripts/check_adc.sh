#!/usr/bin/env bash
# Loud ADC check: who am I, which quota project, can a token be minted, is the project reachable.
#
#   bash skills/gcp-integration/scripts/check_adc.sh [--project PROJECT]
#
# Exit 1 on the first failing check with the command that fixes it. Never prints tokens or secrets.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

fail() { echo "[FAIL] $1"; echo "       Fix: $2"; exit 1; }
pass() { echo "[PASS] $1"; }

command -v gcloud >/dev/null || fail "gcloud not found" "install the Google Cloud SDK"

active="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
[[ -n "$active" ]] || fail "no active gcloud account" "gcloud auth login"
pass "gcloud account: $active"

adc_file="${GOOGLE_APPLICATION_CREDENTIALS:-${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json}"
[[ -f "$adc_file" ]] || fail "ADC file missing ($adc_file)" "gcloud auth application-default login"
pass "ADC file present"

quota="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("quota_project_id",""))' "$adc_file" 2>/dev/null || true)"
if [[ -n "$PROJECT" && "$quota" != "$PROJECT" ]]; then
  fail "ADC quota project is '${quota:-unset}', expected '$PROJECT'" "gcloud auth application-default set-quota-project $PROJECT"
fi
pass "ADC quota project: ${quota:-unset}"

if gcloud auth application-default print-access-token >/dev/null 2>&1; then
  pass "ADC token mints"
else
  fail "ADC token cannot be minted (expired or revoked)" "gcloud auth application-default login"
fi

if [[ -n "$PROJECT" ]]; then
  number="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || true)"
  [[ -n "$number" ]] || fail "project '$PROJECT' not reachable as $active" "gcloud config set project $PROJECT (and check roles with whoami_iam.sh)"
  pass "project $PROJECT reachable (number $number)"
  loc="${GOOGLE_CLOUD_LOCATION:-}"
  if [[ "$loc" == "global" ]]; then pass "GOOGLE_CLOUD_LOCATION=global"; else echo "[WARN] GOOGLE_CLOUD_LOCATION is '${loc:-unset}'; Gemini 3.x needs global"; fi
else
  echo "[WARN] GOOGLE_CLOUD_PROJECT unset; pass --project to check reachability"
fi
echo "ok"
