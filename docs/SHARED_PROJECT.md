# Working in a shared Google Cloud project

A room of attendees can share one Google Cloud project. Every resource an attendee creates carries a short id,
`WORKSHOP_NAMESPACE`, so two people running `uv run python data/generate.py && bash data/load.sh --env dev` or `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` in the same project never
overwrite each other. The same rules apply in a project of your own: every command that creates or reads a
workshop resource refuses to run without a namespace.

## Your namespace

```bash
uv run python scripts/namespace.py              # derive one from your gcloud sign-in and write it into .env
uv run python scripts/namespace.py --set alex      # or choose your own
```

Expected: `wrote WORKSHOP_NAMESPACE=u1a2b3c to .env (derived from your gcloud account)` (your id differs), followed
by the names of your resources. Run it again at any time to print them.

- The derived id is `u` plus the first six hex characters of the SHA-256 of your gcloud account, lower-cased
  (`gcloud config get-value account`). It is the same on every machine you sign in from, and it is not your email.
- A chosen name must be 3 to 12 lowercase letters or digits, starting with a letter.
- `uv run python scripts/namespace.py` writes the value into `.env` once, where you can see it. Nothing derives it quietly at run time:
  without it, `uv run python scripts/check_env.py --stage prereqs` prints `[FAIL] WORKSHOP_NAMESPACE set  unset` with `Fix: uv run python scripts/namespace.py`, `uv run python data/generate.py && bash data/load.sh --env dev`
  stops with `ERROR: WORKSHOP_NAMESPACE is not set` and the same fix, and the agent refuses to build.
- `uv run python scripts/namespace.py` needs `.env` to exist (`cp .env.example .env`) and an active gcloud account (`gcloud auth login`),
  or it stops and says which one is missing.
- Run `uv run python scripts/namespace.py` as its own command, then start the next command: a shell that exported the
  old value keeps it until you open a new shell or export the new one.

## What carries your namespace

| Resource | Name | Created by | Also identified by |
|---|---|---|---|
| BigQuery dataset | `cymbal_beauty_<ns>_<env>` (`<env>` is `dev`, `preprod` or `prod`) | `uv run python data/generate.py && bash data/load.sh --env <env>` | dataset labels `ns`, `env`, `data_version` |
| BigQuery jobs the agent runs | – | every tool query | job labels `ns=<ns>`, `env`, `adk_agent=cymbal_store_ops`, `data_backend=bigquery`, `tool=<tool name>` |
| Agent Runtime (formerly Agent Engine) engine | display name `cymbal-store-ops-<ns>-<env>` | `uv run python deployment/release.py && uv run python deployment/deploy.py --env <env> --release release.json` | labels `app=cymbal-store-ops`, `ns=<ns>`, `env=<env>` (plus `git-sha`, `data-version`) |
| Quickstart engines | `qs-<ns>-<quickstart>` | `uv run python deployment/deploy_quickstart.py --all` | labels `app=quickstart`, `ns=<ns>`, `quickstart=<name>`, `env=dev` |
| Store SOP data store (Vertex AI Search, `global`) | `cymbal-store-sops-<ns>` | `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` | – |
| Pub/Sub topic and pull subscription (quickstart 11) | `cymbal-store-ops-recommendations-<ns>` and `…-<ns>-pull` | `gcloud pubsub topics create` and `gcloud pubsub subscriptions create` (quickstart 11 README) | – |
| Cloud Build triggers (facilitator) | `<ns>-ci`, `<ns>-deploy-dev`, `<ns>-deploy-preprod`, `<ns>-prod-canary`, `<ns>-prod-promote-10`, `<ns>-prod-promote-100`, `<ns>-prod-rollback` | `deployment/iam/setup_cloudbuild_triggers.sh` | substitution `_NAMESPACE=<ns>` |
| Local deployment record | `deployment/deployment_info.<ns>.<env>.json` (gitignored) | `uv run python deployment/release.py && uv run python deployment/deploy.py --env <env> --release release.json` | – |

How a deploy finds your engine: `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` updates the one engine labelled `app=cymbal-store-ops`,
`ns=<ns>`, `env=dev`, and creates it when there is none. The local JSON record is a note of the last deploy, not
the source of truth, so a fresh checkout (or the pipeline) finds the same engine. If more than one engine carries
the same labels, the deploy stops and lists them. An engine labelled with another namespace is refused
(`belongs to namespace …, not <ns>`), so `AGENT_ENGINE_ID` cannot point you at someone else's engine by mistake.

The SOP data store is checked the same way: `SOP_DATA_STORE` must name `cymbal-store-sops-<your namespace>`, or the
agent refuses to build with the name it expected.

## List and remove your resources

```bash
uv run python scripts/resources.py                  # everything in the project that carries your namespace
uv run python scripts/resources.py --delete --yes         # delete all of it
```

Expected: `namespace <ns> in project <project>: N resource(s)` followed by one line per engine, dataset, data
store, Pub/Sub item and local record; with `YES=1`, one `deleted …` line each and `N deleted, 0 failed`. A delete
that fails is printed as `FAILED` with the reason, the rest are still attempted, and the command exits 1.
Nothing without your namespace is listed or touched.

## What is shared

Namespaces keep names apart. They are not an access boundary. These are shared by everyone in the project:

| Shared | Why it matters |
|---|---|
| Runtime service accounts `store-ops-<env>-runtime@<project>.iam.gserviceaccount.com`, one per environment | every attendee's engine for an environment runs as the same identity. `uv run python data/generate.py && bash data/load.sh --env dev` shares your dataset with it (dataset `READER`, `bigquery.dataEditor` on `store_tasks`) when the account exists, so that identity can read every attendee's dataset it was shared with |
| Staging bucket `gs://<project>-cymbal-store-ops-staging` | every deploy, including the quickstart deploys, uploads its package here, each into its own folder `agent_engine/<namespace>/<app>-<env>/` (the SDK's default is one `agent_engine/` folder for everybody, so two people deploying at once would overwrite each other's upload); SOP pages go to `sops/<namespace>/`. `uv run python scripts/resources.py` lists both folders and `uv run python scripts/resources.py --delete --yes` removes them |
| Gemini quota for the `global` endpoint | requests per minute are per project. The model client retries a `429` with exponential backoff a bounded number of times (six attempts, delays up to 40 seconds); after that the error reaches you unchanged. A hanging request is abandoned after 90 seconds and retried the same way. There is no switch to another model |
| The CI/CD identities (`cicd-evaluator@`, `cicd-deployer-<env>@`), the Workload Identity pool `cicd` and the custom role `cymbalModelCaller` | created once by the facilitator; the Cloud Build triggers carry the facilitator's namespace |

If a model call is slow in a busy room, it is usually the retry at work: wait for the turn to finish rather than
sending the prompt again, which adds another request to the same quota.

## Facilitator checklist

1. Sign in as a project Owner (`gcloud auth login` and `gcloud auth application-default login`), then set up your
   own checkout: `cp .env.example .env`, set `GOOGLE_CLOUD_PROJECT`, `uv sync --all-extras`, `uv run python scripts/namespace.py`.
2. Load your own data for each environment the pipeline demo uses: `uv run python data/generate.py && bash data/load.sh --env dev`, and `ENV=preprod` and
   `ENV=prod` for the promotion demo.
3. Create the identities, the staging bucket and the attendee grants:

   ```bash
   bash deployment/iam/setup_wif.sh <project> <github-owner> <repo> --namespace <your namespace> --attendee-group <group email>
   ```

   Expected: `== …` section headers, one `sa …` line per service account, the `gh variable set …` lines, and `done`.
   The script is idempotent: rerun it after loading another environment's data (it prints
   `dataset … does not exist yet: rerun this script after uv run python data/generate.py && bash data/load.sh --env <env>` for datasets it could not find).
   It enables the workshop's APIs (`aiplatform`, `bigquery`, `secretmanager`, `cloudbuild`, `artifactregistry`,
   `iamcredentials`, `sts`, `storage`, `cloudresourcemanager`, `discoveryengine`, `geminidataanalytics`,
   `cloudtrace`, `telemetry`, `logging`, `monitoring`, `pubsub`, `run`) and grants the attendee group:

   | Role | Where |
   |---|---|
   | `roles/aiplatform.user` | project |
   | `roles/bigquery.jobUser` | project |
   | `roles/bigquery.user` (creates `cymbal_beauty_<ns>_*` datasets) | project |
   | `roles/serviceusage.serviceUsageConsumer` | project |
   | `roles/pubsub.editor` | project |
   | `roles/logging.viewer` | project |
   | `roles/cloudtrace.user` | project |
   | `roles/agentregistry.viewer` | project |
   | `roles/discoveryengine.admin` (SOP data stores: Editor can import and search but cannot create or delete a data store; Admin also lets one attendee delete another's, so the namespace is a naming convention, not isolation) | project |
   | `roles/iam.serviceAccountUser` | `store-ops-dev-runtime@` only |
   | `objectAdmin` | the staging bucket |

   Attendees can deploy `dev` only; preprod and prod deploys run from the pipeline.
4. Optional, for the promotion demo: connect the repository to Cloud Build (2nd gen connection named `github` in
   `us-central1`), then create the triggers:

   ```bash
   bash deployment/iam/setup_cloudbuild_triggers.sh <project> <github-owner> <repo> <your namespace>
   ```

   Expected: one `created: <ns>-…` (or `exists: <ns>-…`) line per trigger, then the `gcloud alpha builds approve` hint.
5. Check the Gemini requests-per-minute quota for the `global` location against the size of the room
   ([COST_AND_QUOTAS.md](COST_AND_QUOTAS.md)).
6. After the workshop, ask attendees to run `uv run python scripts/resources.py --delete --yes`. To clean up a namespace someone left behind,
   pass it on the command line (a `WORKSHOP_NAMESPACE=…` prefix is overridden by your `.env`):

   ```bash
   uv run python scripts/resources.py
   uv run python scripts/resources.py --delete --yes
   ```

   Expected: the list of that namespace's resources, then one `deleted …` line each. `bq ls --project_id <project>`
   shows which `cymbal_beauty_<ns>_<env>` datasets remain.

Roles and the full principal matrix: [IAM_MATRIX.md](IAM_MATRIX.md). Setup for attendees: [SETUP.md](../SETUP.md).
