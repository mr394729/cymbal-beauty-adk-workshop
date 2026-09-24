#!/usr/bin/env bash
# Deploy the standalone chat UI to Cloud Run, pointed at the deployed engine for one environment.
#
#   deployment/deploy_frontend.sh <env> [region]        (bash deployment/deploy_frontend.sh dev)
#
# The service is reachable by anyone with the URL and gated by a password generated per deployment and kept in
# Secret Manager — the same shape as the workshop guide, so a room can open it without a gcloud command first.
# For anything carrying real data, add the Google sign-in back: the last lines this prints show how.
#
# What it does, and nothing else: builds frontend/Dockerfile, pushes it to Artifact Registry, and deploys it as a
# Cloud Run service running as store-ops-frontend@, which holds roles/aiplatform.user on the project. That role is
# wider than "may call this engine": it also allows creating, updating and deleting engines. Narrow it to the one
# engine before this leaves a sandbox. The store data itself is read by the engine's own runtime identity, never
# by this service.
#
# It refuses rather than guesses: no engine for this namespace and environment, no deploy.
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
ENV_NAME="${1:?usage: deployment/deploy_frontend.sh <env> [region]}"
REGION="${2:-us-central1}"

: "${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is not set — set it in .env}"
: "${WORKSHOP_NAMESPACE:?WORKSHOP_NAMESPACE is not set — run uv run python scripts/namespace.py}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
NS="$WORKSHOP_NAMESPACE"
SERVICE="cymbal-frontend-${NS}-${ENV_NAME}"
REPO="cymbal-store-ops"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/frontend-${NS}:${ENV_NAME}"
SA="store-ops-frontend@${PROJECT}.iam.gserviceaccount.com"
SECRET="cymbal-frontend-${NS}-${ENV_NAME}-password"

echo "engine check: the frontend is useless without one"
uv run python -c "
from deployment._common import client_for, engine_namespace_guard, get_engine, load_config, resolve_engine_name
cfg = load_config('${ENV_NAME}')
client = client_for(cfg)
name = resolve_engine_name(cfg, client)
engine_namespace_guard(get_engine(client, name), cfg)   # it exists, and it is this namespace's
print('engine:', name)
"

# List rather than describe: a describe that fails on a permission or API error is not the same as "absent",
# and creating over the top of that turns one clear error into a different, confusing one.
REPOS=$(gcloud artifacts repositories list --project "$PROJECT" --location "$REGION" --format='value(name.basename())')
if ! grep -Fxq "$REPO" <<<"$REPOS"; then
  gcloud artifacts repositories create "$REPO" --project "$PROJECT" --location "$REGION" \
    --repository-format=docker --description="Cymbal Beauty store operations containers"
fi

ACCOUNTS=$(gcloud iam service-accounts list --project "$PROJECT" --format='value(email)')
if ! grep -Fxq "$SA" <<<"$ACCOUNTS"; then
  gcloud iam service-accounts create store-ops-frontend --project "$PROJECT" \
    --display-name "Cymbal store operations frontend"
fi
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${SA}" \
  --role roles/aiplatform.user --condition=None >/dev/null

# One password per deployment, generated here and kept in Secret Manager. Each person who deploys gets their own;
# nothing is shared, nothing is committed, and the value is never printed by this script — read it back with
# `gcloud secrets versions access latest --secret=cymbal-frontend-$WORKSHOP_NAMESPACE-<env>-password` when you want to sign in.
if ! gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET" --project "$PROJECT" --replication-policy=automatic
fi
# `| grep -q` would close gcloud's pipe early and kill it with SIGPIPE, which `set -e` then turns into a failed
# deploy. Capture the list instead.
VERSIONS=$(gcloud secrets versions list "$SECRET" --project "$PROJECT" --format='value(name)' --filter='state:ENABLED')
if [ -z "$VERSIONS" ]; then
  PASSWORD=$(LC_ALL=C tr -dc 'a-hj-km-np-z2-9' </dev/urandom | head -c 18)
  printf '%s' "$PASSWORD" | gcloud secrets versions add "$SECRET" --project "$PROJECT" --data-file=-
  unset PASSWORD
  echo "created a password for this deployment: gcloud secrets versions access latest --secret=cymbal-frontend-$WORKSHOP_NAMESPACE-${ENV_NAME}-password"
fi
gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor --condition=None >/dev/null

echo "building ${IMAGE}"
gcloud builds submit --project "$PROJECT" --region "$REGION" --config cloudbuild/frontend.yaml \
  --substitutions=_IMAGE="$IMAGE" .

# Event infrastructure is optional; pass its complete configuration when enabled.
FRONTEND_ENV="GOOGLE_CLOUD_PROJECT=${PROJECT},WORKSHOP_NAMESPACE=${NS},STORE_OPS_ENV=${ENV_NAME},CYMBAL_ARTIFACT_BUCKET=${PROJECT}-cymbal-artifacts-${NS}-${ENV_NAME},AGENT_ENGINE_ID=${AGENT_ENGINE_ID:-}"
if [[ -n "${EVENTS_PROJECT:-}${EVENTS_DATABASE:-}${EVENTS_TOPIC:-}" ]]; then
  : "${EVENTS_PROJECT:?Set EVENTS_PROJECT when enabling notifications}"
  : "${EVENTS_DATABASE:?Set EVENTS_DATABASE when enabling notifications}"
  : "${EVENTS_TOPIC:?Set EVENTS_TOPIC when enabling notifications}"
  FRONTEND_ENV+=",EVENTS_PROJECT=${EVENTS_PROJECT},EVENTS_DATABASE=${EVENTS_DATABASE},EVENTS_COLLECTION=${EVENTS_COLLECTION:-event_jobs},EVENTS_TOPIC=${EVENTS_TOPIC}"
fi

echo "deploying ${SERVICE}"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
  --service-account "$SA" --allow-unauthenticated --min-instances 1 --no-cpu-throttling --max-instances 3 --memory 512Mi \
  --set-env-vars "$FRONTEND_ENV" \
  --set-secrets "FRONTEND_PASSWORD=${SECRET}:latest"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
echo "deployed: ${URL}"
echo "password:  gcloud secrets versions access latest --secret=cymbal-frontend-$WORKSHOP_NAMESPACE-${ENV_NAME}-password"
echo
echo "The URL is reachable by anyone who has it; the password is the gate, one per deployment, in Secret Manager."
echo "To require a Google sign-in as well:"
echo "  gcloud run services update ${SERVICE} --project ${PROJECT} --region ${REGION} --no-allow-unauthenticated"
echo "  gcloud run services add-iam-policy-binding ${SERVICE} --project ${PROJECT} --region ${REGION} --member user:<email> --role roles/run.invoker"
