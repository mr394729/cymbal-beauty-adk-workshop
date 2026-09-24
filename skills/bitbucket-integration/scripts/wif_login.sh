#!/usr/bin/env bash
# Exchange a Bitbucket Pipelines step identity token for short-lived Google Cloud credentials through Workload
# Identity Federation, then prove the identity before anything else runs. Copy to ci/wif_login.sh in your repository
# and call it with `source` (it exports GOOGLE_APPLICATION_CREDENTIALS for the rest of the step):
#
#   - source ci/wif_login.sh
#
# Needs repository variables GCP_PROJECT_ID, GCP_PROJECT_NUMBER and WIF_SERVICE_ACCOUNT, `oidc: true` on the step,
# and gcloud on the PATH. No key is stored anywhere; when the exchange fails the step fails, in words.
set -euo pipefail

fail() { echo "wif_login: $1" >&2; echo "Fix: $2" >&2; exit 1; }

[[ -n "${BITBUCKET_STEP_OIDC_TOKEN:-}" ]] || fail "this step has no identity token" "add 'oidc: true' to the step in bitbucket-pipelines.yml"
for name in GCP_PROJECT_ID GCP_PROJECT_NUMBER WIF_SERVICE_ACCOUNT; do
  [[ -n "${!name:-}" ]] || fail "repository variable $name is not set" "Repository settings > Pipelines > Repository variables"
done
command -v gcloud >/dev/null || fail "gcloud is not installed in this image" "install the Google Cloud SDK in the step, or use an image that has it"

WIF_POOL="${WIF_POOL:-cicd}"; WIF_PROVIDER="${WIF_PROVIDER:-bitbucket-oidc}"
WORK="$(mktemp -d)"; TOKEN_FILE="$WORK/oidc_token"; CRED_FILE="$WORK/gcp_credentials.json"
( umask 077; printf '%s' "$BITBUCKET_STEP_OIDC_TOKEN" > "$TOKEN_FILE" )

gcloud iam workload-identity-pools create-cred-config \
  "projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/providers/$WIF_PROVIDER" \
  --service-account "$WIF_SERVICE_ACCOUNT" --credential-source-file "$TOKEN_FILE" --output-file "$CRED_FILE" >/dev/null

export GOOGLE_APPLICATION_CREDENTIALS="$CRED_FILE" GOOGLE_CLOUD_PROJECT="$GCP_PROJECT_ID" CLOUDSDK_CORE_PROJECT="$GCP_PROJECT_ID"
gcloud auth login --cred-file "$CRED_FILE" --quiet >/dev/null 2>&1 \
  || fail "Google Cloud refused the step's token" "compare the provider's issuer, audience and repositoryUuid condition with the repository's OpenID Connect settings page"

# The proof: mint a token as the service account. A wrong principalSet binding fails here, not three steps later.
gcloud auth print-access-token >/dev/null 2>&1 \
  || fail "the token was accepted but $WIF_SERVICE_ACCOUNT cannot be impersonated" "bind roles/iam.workloadIdentityUser on it to the principalSet for this repository's UUID (braces included)"
echo "wif_login: signed in to $GCP_PROJECT_ID as $WIF_SERVICE_ACCOUNT through $WIF_POOL/$WIF_PROVIDER"
