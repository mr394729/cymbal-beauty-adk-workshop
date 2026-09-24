---
name: gcloud-cli
description: Driving the Google Cloud command line (gcloud, bq, gcloud storage, and REST with a gcloud token where gcloud has no command) from a coding agent in this repo, safely and without prompts. Read before you change (list, describe, dry run), explicit --project and --region on every command, output shaped with --format, --filter and jq instead of scraped tables, namespace-scoped changes in a shared project, exit codes, long-running operations, and a per-service cookbook for BigQuery, Agent Runtime, Cloud Run, Cloud Build, Secret Manager, Logging, Storage and IAM. Use when you are about to run, write or review a gcloud or bq command, need a value out of Google Cloud for a script, need to find or delete the resources you created, or a command hangs on a prompt or returns a table you cannot parse. For 401/403 diagnosis, roles and federation use gcp-integration.
metadata:
  workshop: cymbal-beauty-adk-workshop
  version: "1.0"
  verified: "2026-09-17"
allowed-tools: Bash Read
---

# Google Cloud command line for a coding agent

`gcloud` and `bq` were written for a person at a terminal: they prompt, they print tables sized to the window,
and they act on whatever project the machine was last pointed at. An agent has to remove all three habits.
Every recipe here was run against a live project on the verified date (Google Cloud SDK 584); the project is
shared by a room, so the rules about namespaces are not optional.

## When to use

- Before running any `gcloud`, `bq` or `gcloud storage` command, and when writing one into a script or a doc.
- To get one value out of Google Cloud (a URL, a revision, a label, a byte count) into a variable.
- To list what you created, or to delete it, in a project other people are using.
- When a command waits for input, prints a table you cannot parse, or "works on my machine" only.

`gcp-integration` is the companion skill: it explains *why* a call was denied (ADC, quota project, roles,
impersonation, federation). This one is about driving the tools.

## The five rules

1. **Read, then show, then change.** `list` or `describe` the target first and show the user what you found.
   Show a changing command and wait for a yes unless the user already asked for exactly that change. Commands
   that read are free to run; commands that create, update, delete, grant or deploy are not.
2. **Name the project and the location on every command.** `--project "$P"` (for `bq`: `--project_id="$P"`),
   plus `--region` or `--location`. Never `gcloud config set project`: it changes every other terminal on the
   machine. For a whole script, `export CLOUDSDK_CORE_PROJECT="$P"` does the same without touching the config.
3. **Never parse a table.** Ask for the field: `--format="value(status.url)"`, or `--format=json` into `jq`.
   Select rows with `--filter` (it works on the structured result, before any formatting), not with `grep`.
4. **Only touch what carries your namespace.** Every workshop resource has `WORKSHOP_NAMESPACE` in its name and
   an `ns=<namespace>` label. A resource without your namespace is someone else's: list it if you must, never
   change or delete it. `uv run python scripts/resources.py` lists yours; `uv run python scripts/resources.py --delete --yes` removes them.
5. **No prompts, and check the exit code.** `--quiet` answers every prompt with its default (for a delete,
   that is "yes": rule 1 applies first). A failed `describe` exits 1, which is how you test for "does not exist".

## Facts that override older docs

- `gcloud` has **no command group for Agent Runtime engines** (`gcloud ai` lists endpoints, models, custom jobs,
  not reasoning engines). List them over REST with a gcloud token (recipe below) or with `uv run python scripts/resources.py`;
  change them only with `deployment/deploy.py` and `deployment/traffic.py`.
- `gcloud auth login` (used by `gcloud` and `bq`) and `gcloud auth application-default login` (used by Python)
  are separate credentials and expire separately. Test both before a long job:
  `gcloud auth print-access-token >/dev/null && gcloud auth application-default print-access-token >/dev/null`.
  In this repo `uv run python -m agents.cymbal_store_ops.preflight --cli` does that and prints the fix.
- Three locations, on purpose: Gemini calls use `global`; Agent Runtime, Cloud Run, Cloud Build and the staging
  bucket are in `us-central1`; BigQuery datasets are multi-region `US`. `--region` is not optional.
- `bq` flags come in two positions: global flags before the verb (`bq --project_id=$P query …` also accepts them
  after it), command flags after. Standard SQL needs `--use_legacy_sql=false` every time.
- `gsutil` still works; new commands use `gcloud storage` (`ls`, `cp`, `rm`, `buckets describe`).
- A projection that slices a string yields a list of characters: `id.slice(0:8)` prints `['1', 'f', …]`.
  Join it: `id.slice(0:8).join('')`.

## Repo map

| Path | Purpose |
|---|---|
| `.env` (`GOOGLE_CLOUD_PROJECT`, `WORKSHOP_NAMESPACE`, `AGENT_ENGINE_LOCATION`, `BQ_LOCATION`) | the values every recipe reads: `set -a; . ./.env; set +a; P=$GOOGLE_CLOUD_PROJECT NS=$WORKSHOP_NAMESPACE` |
| `scripts/resources.py` (`uv run python scripts/resources.py`, `uv run python scripts/resources.py --delete --yes`) | every resource that carries your namespace, listed or deleted, with the delete confirmed by polling |
| `agents/cymbal_store_ops/preflight.py` | stops with a `Fix:` line when either sign-in has expired, before anything runs |
| `scripts/check_env.py --stage prereqs\|ready` | tools, sign-ins, project, APIs, location, model, datasets, fixtures |
| `data/load.sh`, `data/teardown.sh` | the only scripts that create or drop the datasets |
| `deployment/deploy.py`, `deployment/traffic.py`, `deployment/smoke.py` | the only way engines are created, shifted or probed |
| `references/cookbook.md` (this skill) | read and change commands per service, each one run on the verified date |

## Recipes

### Start of a session: who am I, where am I pointed, do both tokens work

```bash
set -a; . ./.env; set +a; P=$GOOGLE_CLOUD_PROJECT; NS=$WORKSHOP_NAMESPACE
gcloud config list --format="value(core.account,core.project)"
gcloud auth print-access-token >/dev/null && gcloud auth application-default print-access-token >/dev/null && echo "both sign-ins work"
gcloud services list --enabled --project "$P" \
  --filter="config.name:(aiplatform.googleapis.com OR bigquery.googleapis.com)" --format="value(config.name)"
```

If the project printed is not `$P`, do not "fix" the config; pass `--project "$P"`.

### One value into a variable

```bash
URL=$(gcloud run services describe "$SERVICE" --project "$P" --region us-central1 --format="value(status.url)")
REV=$(gcloud run services describe "$SERVICE" --project "$P" --region us-central1 --format="value(status.latestReadyRevisionName)")
SA=$(gcloud run services list --project "$P" --region us-central1 --format=json \
     | jq -r --arg s "$SERVICE" '.[] | select(.metadata.name==$s) | .spec.template.spec.serviceAccountName')
```

`value(a,b)` prints tab-separated fields with no header. `table(name, status.url:label=URL)` is for a person.

### Does it exist? (exit code, not text)

```bash
if gcloud run services describe "$SERVICE" --project "$P" --region us-central1 --format="value(metadata.name)" >/dev/null 2>&1
then echo exists; else echo "absent (or no permission to see it: check with gcp-integration)"; fi
```

### BigQuery: dry run first, cap the bytes, label the job

```bash
SQL="SELECT product_id, on_hand, on_shelf_qty FROM \`$P.cymbal_beauty_${NS}_dev.store_inventory\` WHERE store_id='S-014' AND product_id='P-0101'"
bq query --project_id="$P" --use_legacy_sql=false --dry_run "$SQL"
bq query --project_id="$P" --use_legacy_sql=false --maximum_bytes_billed=100000000 --label "ns:$NS" --format=json "$SQL"
```

```text
Query successfully validated. Assuming the tables are not modified, running this query will process 552000 bytes of data.
[{"on_hand":"7","on_shelf_qty":"0","product_id":"P-0101"}]
```

The dry run costs nothing and catches a wrong name before anything runs
(`Unrecognized name: on_hand_qty; Did you mean on_hand?`). JSON output quotes every number: convert in `jq`
(`tonumber`) before comparing.

### My datasets, by namespace and by label

```bash
bq ls --project_id="$P" --format=json --max_results=200 \
  | jq -r --arg ns "_${NS}_" '.[] | select(.datasetReference.datasetId | contains($ns)) | .datasetReference.datasetId'
bq show --format=json "$P:cymbal_beauty_${NS}_dev" | jq -c '{location, labels}'
```

```text
cymbal_beauty_u1a2b3c_dev
{"location":"US","labels":{"data_version":"2026-09-18-1","env":"dev","ns":"u1a2b3c"}}
```

### Agent Runtime engines (REST, because gcloud has no command)

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://us-central1-aiplatform.googleapis.com/v1/projects/$P/locations/us-central1/reasoningEngines?pageSize=100" \
  | jq -r --arg ns "$NS" '.reasoningEngines[]? | select(.labels.ns==$ns) | [(.name|split("/")|last), .displayName] | @tsv'
```

Drop the `select(...)` to see the whole room's engines. Read-only: create, update, traffic and delete go through
`deployment/*.py`, which stamp the labels the rest of the repo relies on.

### Logs without the console

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND severity>=ERROR' \
  --project "$P" --freshness 1d --limit 20 --format="value(timestamp,resource.labels.reasoning_engine_id,textPayload)"
gcloud run services logs read "$SERVICE" --project "$P" --region us-central1 --limit 50
```

Always pass `--freshness` and `--limit`; without them the read scans a day and returns everything.

### Deleting something (the careful path)

```bash
gcloud run services describe "$SERVICE" --project "$P" --region us-central1 --format="value(metadata.name,metadata.labels.ns)"
# show that line to the user; continue only if the ns label is yours and they said yes
gcloud run services delete "$SERVICE" --project "$P" --region us-central1 --quiet
gcloud run services describe "$SERVICE" --project "$P" --region us-central1 >/dev/null 2>&1 || echo "gone"
```

For workshop resources prefer `uv run python scripts/resources.py --delete --yes`: it deletes only what carries your namespace and waits
until each delete is confirmed. `bq rm -r -f` on a dataset is immediate and has no undo.

## Gotchas

- A command that "hangs" is waiting on a prompt you cannot see. Add `--quiet`, or for `bq` the `-f` flag on `rm`.
- `--filter` has gcloud's own syntax (`name~regex`, `labels.ns=x`, `a:(x OR y)`), not SQL and not jq.
- `gcloud run services list` without `--region` lists every region; `gcloud builds list` without it lists only
  the global builds, which are a different set from this repo's `us-central1` builds. Say which you mean.
- `bq ls` stops at 50 rows by default; pass `--max_results`. `bq ls -j` lists jobs, not datasets.
- `gcloud config configurations create NAME --no-activate` makes a second profile without switching the
  machine to it; select it per command with `--configuration NAME`.
- Table output can carry colour codes even in a pipe (a secret version's `enabled` arrives wrapped in escape
  sequences). `--format=json` and `value()` never do.
- A long-running operation returns before the work is done when you pass `--async`; without it gcloud waits.
  After a delete, prove it with a `describe` that fails, not with the delete's own message.
- Never paste `gcloud auth print-access-token` output into a file, a log or a chat; use it inline as above.

## References

- [references/cookbook.md](references/cookbook.md), read and change commands per service, with the output each one printed
- gcloud reference: https://docs.cloud.google.com/sdk/gcloud/reference
- Formats, projections and filters: https://docs.cloud.google.com/sdk/gcloud/reference/topic/formats , https://docs.cloud.google.com/sdk/gcloud/reference/topic/projections , https://docs.cloud.google.com/sdk/gcloud/reference/topic/filters
- Scripting gcloud: https://docs.cloud.google.com/sdk/docs/scripting-gcloud
- Configurations and properties: https://docs.cloud.google.com/sdk/docs/configurations , https://docs.cloud.google.com/sdk/docs/properties
- bq command-line tool: https://docs.cloud.google.com/bigquery/docs/reference/bq-cli-reference , dry runs: https://docs.cloud.google.com/bigquery/docs/running-queries
- gcloud storage: https://docs.cloud.google.com/sdk/gcloud/reference/storage
- Logging query language: https://docs.cloud.google.com/logging/docs/view/logging-query-language
- Google's own skills: https://github.com/google/skills
