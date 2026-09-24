# Cost and quota worksheet

Everything is synthetic and small, but model calls, judge samples and engine instances add up with a room full
of attendees. Numbers below are planning estimates; check the pricing pages for current rates.

## Per attendee, during the workshop

| Item | Volume | Notes |
|---|---|---|
| Gemini calls (labs 1–2) | ~40 turns × ~3 model calls | `gemini-3.8-flash`, short prompts; the context cache trims re-sent prefixes |
| Eval gate | 6 cases × 2 runs × (1 agent run + 3 judge samples) ≈ 50 calls | judge = `gemini-3.8-flash`; `EVAL_NUM_RUNS=1` halves it |
| BigQuery | ~150 queries × < 1 MB scanned | `maximum_bytes_billed` = 100 MB per query caps runaway cost |
| Agent Runtime (dev engine) | `min_instances: 1` | one instance stays warm and is billed while it runs; delete the engine after the workshop (`uv run python deployment/teardown.py --env dev --yes && bash data/teardown.sh --env dev --yes`); sessions and memory billed per use |

## Measured, not estimated (persona journeys, local runner, gemini-3.8-flash on global)

`uv run python journeys/run.py` (14 journeys, 76 turns) reported 1.33 M tokens: about 17.5 k per turn on average, 5–15 k for a
question answered by one consultant, 23–46 k for a `store_tasks` turn (a task agent carries the conversation's
history into every call). Latency per turn: p50 21 s, p95 86 s; the start-of-day briefing ≈ 60 s (three branches in
parallel, then the plan writer), a consultant call ≈ 20 s, a follow-up that needs no tool ≈ 2 s.

Scale it with the use-case sheet: one six-turn shift-start loop (plan, drill in, cover, approve, review) costs
≈ 105 k tokens; 1,500 stores once a day ≈ 160 M tokens a day before context caching. The App's context cache
(`ContextCacheConfig`, 1,800 s TTL) now considers prefixes after a request reaches 16,384 prompt tokens.
Shorter requests skip cache creation; repeated large prefixes may be cached per agent. Cache creation has
a five-second timeout and one attempt. The historical numbers above predate this threshold change. Re-measure after a model or prompt change: `uv run python journeys/run.py` prints the totals in
`build/journeys/summary.md`.

## Facilitator

| Item | Notes |
|---|---|
| Three engines (dev, preprod, prod) | prod `min_instances: 1`; delete preprod/prod after the workshop (`uv run python deployment/teardown.py --env … --yes && bash data/teardown.sh --env … --yes`) |
| Cloud Build | a full promotion run is a few minutes of build time |
| Traces and logs | telemetry on for the demo engines only |

## Quotas to check the day before

- Gemini requests per minute in the `global` location for the sandbox project (attendees × concurrent turns).
- Agent Runtime: engines per project and revisions per engine (prune zero-traffic revisions).
- BigQuery concurrent queries (interactive) — well within defaults for this dataset.
- Cloud Build concurrent builds (if Cloud Build gates are used live).

## Limits already in the code

`maximum_bytes_billed`, `max_query_result_rows` (50), `statement_timeout_s` (60), `min_instances` per env, judge
`num_samples` (3), `EVAL_NUM_RUNS` (2).

## Services created by quickstart setup scripts

| Quickstart | Service | Created by | Removed by | Idle cost |
|---|---|---|---|---|
| 02 | Vertex AI Search data store `cymbal-store-sops-<namespace>` (six small documents), also used by `policy_lookup` | `uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` | `... sop_data_store.py teardown` | index storage for six documents; each `policy_lookup` call is a billed search query |
| 06 | Memory Bank on the dev engine (`--memory_service_uri=agentengine://<id>`) | the engine | `uv run python deployment/teardown.py --env dev --yes && bash data/teardown.sh --env dev --yes` | per stored memory, negligible for a workshop |
| 11 | Pub/Sub topic `cymbal-store-ops-recommendations-<namespace>` and its pull subscription | `setup.sh` | `teardown.sh` | none |
| 04 | none (a local FastAPI mock on port 8010) | – | – | none |

## Teardown

`uv run python deployment/teardown.py --env <env> --yes && bash data/teardown.sh --env <env> --yes` deletes the engine and its revisions and the two datasets;
`deployment/iam/setup_wif.sh` resources (service accounts, WIF pool, bucket) are left in place and cost nothing idle.
