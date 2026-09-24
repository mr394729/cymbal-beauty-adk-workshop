# Repository automation

[workflows/ci.yml](workflows/ci.yml) runs lint, unit/catalog checks and the authenticated evaluation job. Repository variables select the project, namespace and federated identities. [Cloud Build](../cloudbuild/README.md) owns deployment and promotion; GitHub Actions source checks are a separate pipeline.
