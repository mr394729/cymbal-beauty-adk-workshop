# gcloud and bq cookbook for this repo

Every **read** command below was run against a live workshop project on 2026-09-17 (Google Cloud SDK 584) and the
output shape shown is what it printed. **Change** commands are the ones this repo's scripts run; each names the
script so you run that instead of retyping it. Set the variables once:

```bash
set -a; . ./.env; set +a; P=$GOOGLE_CLOUD_PROJECT; NS=$WORKSHOP_NAMESPACE
```

## BigQuery (`bq`)

| Intent | Command | Notes |
|---|---|---|
| my datasets | `bq ls --project_id="$P" --format=json --max_results=200 \| jq -r --arg ns "_${NS}_" '.[] \| select(.datasetReference.datasetId \| contains($ns)) \| .datasetReference.datasetId'` | `bq ls` returns 50 rows unless you pass `--max_results` |
| tables in a dataset | `bq ls --project_id="$P" --format=json --max_results=100 "cymbal_beauty_${NS}_dev" \| jq -r '.[].tableReference.tableId'` | twelve tables after `data/load.sh` |
| a table's columns | `bq show --schema --format=json "$P:cymbal_beauty_${NS}_dev.store_tasks" \| jq -r '.[].name'` | the agent's one writable table |
| dataset labels and location | `bq show --format=json "$P:cymbal_beauty_${NS}_dev" \| jq -c '{location, labels}'` | `{"location":"US","labels":{"data_version":…,"env":"dev","ns":…}}` |
| what will this query cost | `bq query --project_id="$P" --use_legacy_sql=false --dry_run "$SQL"` | validates names and prints the bytes; free |
| run it, bounded and labelled | `bq query --project_id="$P" --use_legacy_sql=false --maximum_bytes_billed=100000000 --label "ns:$NS" --format=json "$SQL"` | a query over the cap fails instead of billing |
| recent jobs and whose they were | `bq ls -j --project_id="$P" --max_results=20 --format=json \| jq -r '.[] \| [.jobReference.jobId, .state, (.configuration.labels.ns // "-")] \| @tsv'` | the agent's own queries carry `ns` too |
| **change:** create and load | `bash data/load.sh --env dev` | `bq mk`, `bq load --replace`, then a row-count assertion per table |
| **change:** reload one table | `bash data/load.sh --env dev --tables store_tasks` | resets the fixtures used by confirmed task actions |
| **change:** drop | `bash data/teardown.sh --env dev --yes` | deletes `cymbal_beauty_<namespace>_dev` only and refuses to run without `--yes`; `bq rm -r -f` is immediate and has no undo |

Numbers arrive as strings in `--format=json` (`"on_hand":"7"`); use `jq`'s `tonumber` before comparing.

## Agent Runtime engines (REST; gcloud has no command group)

```bash
TOKEN_HEADER="Authorization: Bearer $(gcloud auth print-access-token)"
BASE="https://us-central1-aiplatform.googleapis.com/v1/projects/$P/locations/us-central1"
curl -s -H "$TOKEN_HEADER" "$BASE/reasoningEngines?pageSize=100" \
  | jq -r --arg ns "$NS" '.reasoningEngines[]? | select(.labels.ns==$ns) | [(.name|split("/")|last), .displayName, .updateTime] | @tsv'
```

| Intent | Use |
|---|---|
| list mine with everything else I created | `uv run python scripts/resources.py` |
| create or update | `uv run python deployment/deploy.py --env dev` (finds the engine by its labels, never by a saved id) |
| revisions and traffic | `uv run python deployment/traffic.py list --env prod` |
| probe | `uv run python deployment/smoke.py --env dev` |
| delete | `uv run python scripts/resources.py --delete --yes` (only your namespace; waits until each delete is confirmed) |

## Cloud Run

| Intent | Command |
|---|---|
| services in the region | `gcloud run services list --project "$P" --region us-central1 --format="table(metadata.name,status.url,metadata.labels.ns)"` |
| one URL | `gcloud run services describe "$SERVICE" --project "$P" --region us-central1 --format="value(status.url)"` |
| serving revision | `… --format="value(status.latestReadyRevisionName)"` |
| runtime identity | `gcloud run services list --project "$P" --region us-central1 --format=json \| jq -r --arg s "$SERVICE" '.[] \| select(.metadata.name==$s) \| .spec.template.spec.serviceAccountName'` |
| recent log lines | `gcloud run services logs read "$SERVICE" --project "$P" --region us-central1 --limit 50` |
| **change:** deploy the agent once (notebook 05) | `uv run adk deploy cloud_run …` as written in `notebooks/05_deploy_and_promote.ipynb`; delete it after the comparison |
| **change:** delete | describe first, confirm the `ns` label, then `gcloud run services delete "$SERVICE" --project "$P" --region us-central1 --quiet` |

Without `--region` the list covers every region in the project (42 services across three regions on the day this
was checked): correct, slow, and mostly other people's.

## Cloud Build

| Intent | Command |
|---|---|
| recent builds | `gcloud builds list --project "$P" --region us-central1 --limit 5 --format="table(id.slice(0:8).join(''):label=BUILD,status,createTime.date('%m-%d %H:%M'):label=CREATED)"` |
| one build's log | `gcloud builds log "$BUILD_ID" --project "$P" --region us-central1` |
| triggers | `gcloud builds triggers list --project "$P" --region us-central1 --format="value(name)"` (empty until `deployment/iam/setup_cloudbuild_triggers.sh` has run) |
| **change:** run a trigger | `gcloud builds triggers run "$TRIGGER" --project "$P" --region us-central1 --branch main` |
| builds waiting for approval | `gcloud builds list --project "$P" --region us-central1 --filter='approval.state=PENDING' --format="value(id)"` (warns "filter keys were not present" when no build has an approval) |
| **change:** approve a waiting build | `gcloud alpha builds approve "$BUILD_ID" --project "$P" --location us-central1` (needs `roles/cloudbuild.approver`). The GA track has no `approve` ("Invalid choice"); `beta` has it without a location flag, so it cannot reach a regional build |

`id.slice(0:8)` alone prints a list of characters; `.join('')` makes it a string again.

## Secret Manager

| Intent | Command |
|---|---|
| secrets by name pattern | `gcloud secrets list --project "$P" --filter="name~store-ops-" --format="value(name.basename())"` |
| versions and state | `gcloud secrets versions list "$SECRET" --project "$P" --format="value(name,state)"` |
| use a value without showing it | `VALUE=$(gcloud secrets versions access latest --secret "$SECRET" --project "$P")` and never `echo` it |
| **change:** first version | `printf '%s' "$VALUE" \| gcloud secrets create "$SECRET" --data-file=- --project "$P"` |
| **change:** new version | `printf '%s' "$VALUE" \| gcloud secrets versions add "$SECRET" --data-file=- --project "$P"` |

`printf '%s'`, not `echo`: `echo` adds a newline that becomes part of the secret.

## Logging

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND severity>=ERROR' \
  --project "$P" --freshness 1d --limit 20 --format="value(timestamp,resource.labels.reasoning_engine_id,textPayload)"
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="'"$SERVICE"'" AND httpRequest.status>=300' \
  --project "$P" --freshness 2h --limit 20 --format="table(timestamp.date('%H:%M:%S'),httpRequest.status,httpRequest.requestUrl.scope(app))"
```

An empty result with exit 0 means "nothing matched", not "no access". Always bound the read with `--freshness`
and `--limit`.

## Storage

| Intent | Command |
|---|---|
| buckets | `gcloud storage ls --project "$P"` |
| a bucket's location | `gcloud storage buckets describe "gs://${P}-cymbal-store-ops-staging" --format="value(location)"` → `US-CENTRAL1` |
| my SOP uploads | `gcloud storage ls "gs://${P}-cymbal-store-ops-staging/sops/${NS}/"` |

The staging bucket is shared by the room: `agent_engine/` holds whichever deploy ran last (the deploy script
rewrites it every time), `sops/<namespace>/` is yours. Never `rm` anything outside your own prefix.

## IAM and services (read)

| Intent | Command |
|---|---|
| roles I hold on the project | `gcloud projects get-iam-policy "$P" --flatten="bindings[].members" --filter="bindings.members:user:$(gcloud config get-value account 2>/dev/null)" --format="value(bindings.role)"` |
| is an API on | `gcloud services list --enabled --project "$P" --filter="config.name:aiplatform.googleapis.com" --format="value(config.name)"` (empty = off) |
| accounts signed in to the CLI | `gcloud auth list --format="value(account,status)"` (`*` marks the active one) |

Granting roles, impersonation and federation are in the `gcp-integration` skill and `docs/IAM_MATRIX.md`.

## Vertex AI Search data stores (REST)

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "X-Goog-User-Project: $P" \
  "https://discoveryengine.googleapis.com/v1/projects/$P/locations/global/collections/default_collection/dataStores?pageSize=50" \
  | jq -r --arg ns "$NS" '.dataStores[]? | select(.name | contains($ns)) | [(.name|split("/")|last), .displayName] | @tsv'
```

The `X-Goog-User-Project` header is required with user credentials, or the call fails with a quota-project 403.
Create and delete go through `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` and `uv run python scripts/resources.py --delete --yes`.

## Patterns worth copying

```bash
# wait for something to disappear (a delete is done when describe fails, not when delete returns)
until ! gcloud run services describe "$SERVICE" --project "$P" --region us-central1 >/dev/null 2>&1; do sleep 5; done

# act on each of MY resources only
gcloud run services list --project "$P" --region us-central1 --filter="metadata.labels.ns=$NS" --format="value(metadata.name)" \
  | while read -r name; do echo "would touch $name"; done

# a second profile without switching the machine
gcloud config configurations create workshop --no-activate
gcloud --configuration workshop config set project "$P"
gcloud --configuration workshop run services list --region us-central1
```
