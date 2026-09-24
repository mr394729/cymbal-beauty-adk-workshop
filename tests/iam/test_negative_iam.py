"""Negative IAM checks, run live via impersonation (marker: live). They prove what an identity can NOT do."""
import os

import google.auth
import pytest
from google.auth import impersonated_credentials

pytestmark = pytest.mark.live
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
NS = os.environ.get("WORKSHOP_NAMESPACE", "")


def _creds(sa: str):
    src, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return impersonated_credentials.Credentials(source_credentials=src, target_principal=f"{sa}@{PROJECT}.iam.gserviceaccount.com",
                                                target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=300)


def test_runtime_sa_cannot_write_products():
    from google.api_core.exceptions import Forbidden
    from google.cloud import bigquery
    client = bigquery.Client(project=PROJECT, credentials=_creds("store-ops-dev-runtime"))
    with pytest.raises(Forbidden):
        client.query(f"UPDATE `{PROJECT}.cymbal_beauty_{NS}_dev.products` SET price_usd = 1 WHERE FALSE").result()


def test_evaluator_cannot_deploy():
    from google.api_core.exceptions import Forbidden, PermissionDenied
    from google.cloud import aiplatform_v1beta1 as aip
    client = aip.ReasoningEngineServiceClient(credentials=_creds("cicd-evaluator"), client_options={"api_endpoint": "us-central1-aiplatform.googleapis.com"})
    with pytest.raises((Forbidden, PermissionDenied)):
        client.create_reasoning_engine(parent=f"projects/{PROJECT}/locations/us-central1",
                                       reasoning_engine=aip.ReasoningEngine(display_name="should-not-exist"))


def test_dev_deployer_cannot_read_prod_secret():
    from google.api_core.exceptions import NotFound, PermissionDenied
    from google.cloud import secretmanager
    client = secretmanager.SecretManagerServiceClient(credentials=_creds("cicd-deployer-dev"))
    with pytest.raises((PermissionDenied, NotFound)):
        client.access_secret_version(name=f"projects/{PROJECT}/secrets/store-ops-prod-partner-api-key/versions/latest")
