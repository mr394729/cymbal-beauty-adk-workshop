#!/usr/bin/env bash
# Bootstrap identities for the workshop: service accounts, least-privilege roles, Workload Identity
# Federation provider (GitHub) and the staging bucket. Idempotent; prints the
# repository variables to set at the end. Never creates keys.
#
#   deployment/iam/setup_wif.sh PROJECT GH_OWNER GH_REPO --namespace NS [--github-repo-id N] [--attendee-group GROUP_EMAIL]
#
# NS is the facilitator's WORKSHOP_NAMESPACE (its datasets get the evaluator and runtime grants; attendees'
# `uv run python data/generate.py && bash data/load.sh --env dev` shares their own datasets with the runtime identities). --attendee-group grants a shared-project
# attendee group what the labs need (docs/SHARED_PROJECT.md).
#
# Identities (all in PROJECT):
#   cicd-evaluator@                read-only: runs the eval gate (model calls + dev datasets)
#   cicd-deployer-{dev,preprod,prod}@   deploys that env's engine; can act as that env's runtime SA
#   store-ops-{dev,preprod,prod}-runtime@   the engine's identity: model calls, its datasets, table-level writes, SOP search, its secrets
set -euo pipefail
PROJECT="${1:?PROJECT}"; GH_OWNER="${2:?GH_OWNER}"; GH_REPO="${3:?GH_REPO}"; shift 3
GH_REPO_ID=""; NS=""; ATTENDEES=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-repo-id) GH_REPO_ID="$2"; shift 2 ;;
    --namespace) NS="$2"; shift 2 ;;
    --attendee-group) ATTENDEES="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$NS" =~ ^[a-z][a-z0-9]{2,11}$ ]] || { echo "--namespace NS (3-12 lowercase letters or digits) is required" >&2; exit 2; }
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
POOL="cicd"; BUCKET="gs://${PROJECT}-cymbal-store-ops-staging"
say() { printf '\n== %s\n' "$*"; }

say "APIs"
gcloud services enable aiplatform.googleapis.com agentregistry.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  storage.googleapis.com cloudresourcemanager.googleapis.com discoveryengine.googleapis.com geminidataanalytics.googleapis.com \
  cloudtrace.googleapis.com telemetry.googleapis.com logging.googleapis.com monitoring.googleapis.com pubsub.googleapis.com \
  run.googleapis.com --project "$PROJECT" >/dev/null
echo "enabled"

ensure_sa() { gcloud iam service-accounts describe "$1@$PROJECT.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$1" --project "$PROJECT" --display-name "$2" >/dev/null; echo "  sa $1"; }
bind_project() {  # a service account created seconds ago can still be "not found": bounded retry, then fail
  for attempt in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$1@$PROJECT.iam.gserviceaccount.com" --role "$2" --condition=None --quiet >/dev/null 2>&1 && return 0
    echo "  waiting for $1 to propagate ($attempt/6)"; sleep 10
  done
  echo "could not bind $2 to $1" >&2; exit 1
}
# Dataset access is an entry in the dataset's access list (bq show -> edit -> bq update --source), per
# https://docs.cloud.google.com/bigquery/docs/control-access-to-resources-iam ; tables take IAM bindings directly.
bind_dataset() {
  local sa="$1@$PROJECT.iam.gserviceaccount.com" role="$2" ds="$3" f; f=$(mktemp)
  if ! bq --project_id="$PROJECT" show --format=prettyjson "$PROJECT:$ds" > "$f" 2>/dev/null; then
    echo "  dataset $ds does not exist yet: rerun this script after \`uv run python data/generate.py && bash data/load.sh --env ${ds##*_}\` to grant $1"; rm -f "$f"; return 0
  fi
  python3 - "$f" "$sa" "$role" <<'PY'
import json, sys
path, sa, role = sys.argv[1:]
d = json.load(open(path)); entry = {"role": role, "userByEmail": sa}
if not any(a.get("userByEmail") == sa for a in d["access"]):
    d["access"].append(entry); json.dump({"access": d["access"]}, open(path, "w"))
PY
  bq --project_id="$PROJECT" update --source "$f" "$PROJECT:$ds" >/dev/null; rm -f "$f"
}
bind_table() {
  bq --project_id="$PROJECT" show "$PROJECT:$3" >/dev/null 2>&1 || { echo "  table $3 does not exist yet: rerun after loading that environment's data"; return 0; }
  bq --project_id="$PROJECT" add-iam-policy-binding --member "serviceAccount:$1@$PROJECT.iam.gserviceaccount.com" --role "$2" "$PROJECT:$3" >/dev/null
}

say "staging bucket"
gsutil ls -b "$BUCKET" >/dev/null 2>&1 || gsutil mb -p "$PROJECT" -l us-central1 "$BUCKET" >/dev/null; echo "  $BUCKET"

say "evaluator"
ensure_sa cicd-evaluator "CI evaluator (read-only)"
# The evaluator only calls models: a custom role with aiplatform.endpoints.predict (roles/aiplatform.user would let it deploy).
gcloud iam roles describe cymbalModelCaller --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam roles create cymbalModelCaller --project "$PROJECT" --title "Cymbal model caller" \
       --description "Call Gemini on Vertex AI and nothing else" --permissions aiplatform.endpoints.predict --stage GA --quiet >/dev/null
bind_project cicd-evaluator "projects/$PROJECT/roles/cymbalModelCaller"
if gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" --filter="bindings.role:roles/aiplatform.user AND bindings.members:cicd-evaluator@" --format="value(bindings.role)" | grep -q .; then
  gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:cicd-evaluator@$PROJECT.iam.gserviceaccount.com" --role roles/aiplatform.user --quiet >/dev/null
  echo "  removed roles/aiplatform.user from cicd-evaluator (it allows engine creation)"
fi
# CI prereqs inspect API state; this grants no service activation or deployment access.
gcloud iam roles describe cymbalApiStatusReader --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam roles create cymbalApiStatusReader --project "$PROJECT" --title "Cymbal CI API status reader" \
       --description "List service enablement for CI prerequisites" --permissions serviceusage.services.list --stage GA --quiet >/dev/null
cymbal_api_reader_permissions=$(gcloud iam roles describe cymbalApiStatusReader --project "$PROJECT" --format="value(includedPermissions)")
if [ "$cymbal_api_reader_permissions" != "serviceusage.services.list" ]; then
  echo "cymbalApiStatusReader must contain only serviceusage.services.list; refusing a broader role" >&2
  exit 1
fi
bind_project cicd-evaluator "projects/$PROJECT/roles/cymbalApiStatusReader"
bind_project cicd-evaluator roles/bigquery.jobUser
bind_project cicd-evaluator roles/logging.logWriter   # same reason: the ci build must be able to write its own log
bind_dataset cicd-evaluator READER "cymbal_beauty_${NS}_dev"

for ENV in dev preprod prod; do
  say "runtime + deployer: $ENV"
  ensure_sa "store-ops-$ENV-runtime" "Store ops runtime ($ENV)"
  bind_project "store-ops-$ENV-runtime" roles/aiplatform.user
  bind_project "store-ops-$ENV-runtime" roles/serviceusage.serviceUsageConsumer  # authenticated artifact/API quota project
  bind_project "store-ops-$ENV-runtime" roles/bigquery.jobUser
  bind_project "store-ops-$ENV-runtime" roles/cloudtrace.agent          # GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true exports spans
  bind_project "store-ops-$ENV-runtime" roles/logging.logWriter
  bind_project "store-ops-$ENV-runtime" roles/monitoring.metricWriter
  bind_project "store-ops-$ENV-runtime" roles/modelarmor.user          # prompt screening when MODEL_ARMOR_TEMPLATE is set (notebook 06)
  bind_project "store-ops-$ENV-runtime" roles/discoveryengine.viewer    # policy_lookup searches the SOP data store
  bind_dataset "store-ops-$ENV-runtime" READER "cymbal_beauty_${NS}_$ENV"
  bind_table "store-ops-$ENV-runtime" roles/bigquery.dataEditor "cymbal_beauty_${NS}_$ENV.store_tasks"
  ensure_sa "cicd-deployer-$ENV" "CI deployer ($ENV)"
  bind_project "cicd-deployer-$ENV" roles/aiplatform.user
  bind_project "cicd-deployer-$ENV" roles/serviceusage.serviceUsageConsumer
  bind_project "cicd-deployer-$ENV" roles/logging.logWriter   # cloudbuild/*.yaml log to Cloud Logging only: without this a build runs and leaves no log
  gsutil iam ch "serviceAccount:cicd-deployer-$ENV@$PROJECT.iam.gserviceaccount.com:objectAdmin" "$BUCKET" >/dev/null
  # The SDK reads the bucket itself before it uploads (storage.buckets.get), which objectAdmin does not include:
  # without this a pipeline deploy dies with "does not have storage.buckets.get access" (seen 2026-09-18).
  gsutil iam ch "serviceAccount:cicd-deployer-$ENV@$PROJECT.iam.gserviceaccount.com:legacyBucketReader" "$BUCKET" >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "store-ops-$ENV-runtime@$PROJECT.iam.gserviceaccount.com" \
    --member "serviceAccount:cicd-deployer-$ENV@$PROJECT.iam.gserviceaccount.com" --role roles/iam.serviceAccountUser --project "$PROJECT" --quiet >/dev/null
  # secrets for this env are granted per secret when created: gcloud secrets add-iam-policy-binding <secret> --member ... --role roles/secretmanager.secretAccessor
done
# The Agent Engine service agent must be allowed to act as the runtime SAs it deploys with.
AE_AGENT="service-${NUM}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
for ENV in dev preprod prod; do
  gcloud iam service-accounts add-iam-policy-binding "store-ops-$ENV-runtime@$PROJECT.iam.gserviceaccount.com" \
    --member "serviceAccount:$AE_AGENT" --role roles/iam.serviceAccountUser --project "$PROJECT" --quiet >/dev/null
done

say "impersonation for the negative IAM tests (tests/iam): the bootstrap identity may mint tokens for the test identities"
CALLER=$(gcloud config get-value account 2>/dev/null)
for SA in store-ops-dev-runtime cicd-evaluator cicd-deployer-dev; do
  gcloud iam service-accounts add-iam-policy-binding "$SA@$PROJECT.iam.gserviceaccount.com" \
    --member "user:$CALLER" --role roles/iam.serviceAccountTokenCreator --project "$PROJECT" --quiet >/dev/null
done
echo "  $CALLER -> tokenCreator on store-ops-dev-runtime, cicd-evaluator, cicd-deployer-dev"

say "workload identity federation"
gcloud iam workload-identity-pools describe "$POOL" --project "$PROJECT" --location global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL" --project "$PROJECT" --location global --display-name "CI/CD identities" >/dev/null
echo "  pool $POOL"
# GitHub: trust only this repository (by numeric id when known — names can be reclaimed).
GH_COND="assertion.repository=='${GH_OWNER}/${GH_REPO}'"
[[ -n "$GH_REPO_ID" && "$GH_REPO_ID" != "0" ]] && GH_COND="assertion.repository_id=='${GH_REPO_ID}'"
gcloud iam workload-identity-pools providers describe github-oidc --project "$PROJECT" --location global --workload-identity-pool "$POOL" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc github-oidc --project "$PROJECT" --location global --workload-identity-pool "$POOL" \
       --issuer-uri "https://token.actions.githubusercontent.com" \
       --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref,attribute.workflow=assertion.workflow" \
       --attribute-condition "$GH_COND" >/dev/null
echo "  provider github-oidc (condition: $GH_COND)"
PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GH_OWNER}/${GH_REPO}"
gcloud iam service-accounts add-iam-policy-binding "cicd-evaluator@$PROJECT.iam.gserviceaccount.com" \
  --member "$PRINCIPAL_SET" --role roles/iam.workloadIdentityUser --project "$PROJECT" --quiet >/dev/null
echo "  github PR workflows -> cicd-evaluator (read-only)"

if [[ -n "$ATTENDEES" ]]; then
  say "attendee group (shared project): $ATTENDEES"
  for ROLE in roles/aiplatform.user roles/bigquery.jobUser roles/bigquery.user roles/serviceusage.serviceUsageConsumer roles/pubsub.editor roles/logging.viewer roles/cloudtrace.user roles/agentregistry.viewer roles/discoveryengine.admin; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "group:$ATTENDEES" --role "$ROLE" --condition=None --quiet >/dev/null && echo "  $ROLE"
  done
  gcloud iam service-accounts add-iam-policy-binding "store-ops-dev-runtime@$PROJECT.iam.gserviceaccount.com" \
    --member "group:$ATTENDEES" --role roles/iam.serviceAccountUser --project "$PROJECT" --quiet >/dev/null && echo "  serviceAccountUser on store-ops-dev-runtime"
  gsutil iam ch "group:$ATTENDEES:objectAdmin" "$BUCKET" >/dev/null && echo "  objectAdmin on $BUCKET"
  gsutil iam ch "group:$ATTENDEES:legacyBucketReader" "$BUCKET" >/dev/null && echo "  legacyBucketReader on $BUCKET (the SDK reads the bucket before it uploads)"
fi

say "set these repository variables (nothing here is secret)"
cat <<VARS
gh variable set GCP_PROJECT_ID --body "$PROJECT"
gh variable set WORKSHOP_NAMESPACE --body "$NS"
gh variable set GCP_REGION --body "us-central1"
gh variable set WIF_PROVIDER --body "projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/providers/github-oidc"
gh variable set WIF_EVALUATOR_SA --body "cicd-evaluator@${PROJECT}.iam.gserviceaccount.com"
gh variable set WIF_DEPLOYER_DEV_SA --body "cicd-deployer-dev@${PROJECT}.iam.gserviceaccount.com"
VARS
echo "done"
