#!/usr/bin/env bash
# Load the Cymbal Beauty store-operations dataset into BigQuery.
#
#   data/load.sh [--project PROJECT] [--namespace NS] [--env dev|preprod|prod] [--location US] [--tables a,b]
#
# BigQuery layout (one dataset per namespace and environment, so a shared project never collides):
#   <project>.cymbal_beauty_<ns>_<env>   products, reviews, stores, store_inventory, associates, store_tasks,
#                                   bopis_orders, store_traffic, shrink_events, guest_feedback,
#                                   coaching_signals, replenishment
#
# Tables load in parallel, at most MAX_PARALLEL_LOADS at a time. Every load's exit code is collected, and a failed
# load stops the script, naming each failed table, before anything is verified or shared.
# `store_tasks` is the only table the agent writes to; `bash data/load.sh --env dev --tables store_tasks` reloads just that one.
# When the environment's runtime service account exists (created by deployment/iam/setup_wif.sh), the dataset is
# shared with it read-only and `store_tasks` read-write, so a deployed engine can use your data.
# Every step is loud: a missing tool, project, file, a failed load or a row-count mismatch exits non-zero.
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

# bq and gcloud use the CLI sign-in; when it has expired, say so before twelve loads fail one by one.
gcloud auth print-access-token >/dev/null 2>&1 || { echo "The gcloud CLI sign-in has expired or is missing; nothing was loaded." >&2; echo "  Fix: gcloud auth login" >&2; exit 3; }
TABLES=""
MAX_PARALLEL_LOADS=6

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
NS="${WORKSHOP_NAMESPACE:-}"
ENV_NAME="${STORE_OPS_ENV:-dev}"
LOCATION="${BQ_LOCATION:-US}"
BACKEND="bigquery"
ALL_TABLES="products reviews stores store_inventory associates store_tasks bopis_orders store_traffic shrink_events guest_feedback coaching_signals replenishment operations_context"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)  PROJECT="$2"; shift 2 ;;
    --namespace) NS="$2"; shift 2 ;;
    --env)      ENV_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --backend)  BACKEND="$2"; shift 2 ;;
    --tables)   TABLES="$2"; shift 2 ;;
    -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$BACKEND" != "bigquery" ]]; then
  echo "ERROR: --backend must be bigquery (got '$BACKEND'); the workshop data lives in BigQuery" >&2; exit 2
fi
[[ -n "$PROJECT" ]] || { echo "ERROR: GOOGLE_CLOUD_PROJECT is not set (or pass --project)" >&2; exit 2; }
[[ -n "$NS" ]] || { echo "ERROR: WORKSHOP_NAMESPACE is not set: run \`uv run python scripts/namespace.py\` (or pass --namespace)" >&2; exit 2; }
[[ "$NS" =~ ^[a-z][a-z0-9]{2,11}$ ]] || { echo "ERROR: WORKSHOP_NAMESPACE=$NS must be 3-12 lowercase letters or digits" >&2; exit 2; }
command -v bq >/dev/null || { echo "ERROR: bq CLI not found — install the Google Cloud SDK" >&2; exit 2; }
[[ -f "$HERE/out/products.ndjson" ]] || { echo "ERROR: data/out is empty — run: python data/generate.py" >&2; exit 2; }

wanted() { [[ -z "${TABLES:-}" ]] || [[ ",$TABLES," == *",$1,"* ]]; }
for t in ${TABLES//,/ }; do
  [[ " $ALL_TABLES " == *" $t "* ]] || { echo "ERROR: unknown table '$t' (known: $ALL_TABLES)" >&2; exit 2; }
done

MAIN="cymbal_beauty_${NS}_${ENV_NAME}"
DATA_VERSION="$(head -1 "$HERE/out/DATA_VERSION" | tr '.' '-')"

if bq --project_id="$PROJECT" ls -d 2>/dev/null | awk '{print $1}' | grep -qx "$MAIN"; then
  echo "dataset exists: $PROJECT:$MAIN"
else
  bq --project_id="$PROJECT" mk --dataset --location="$LOCATION" \
    --description "Cymbal Beauty workshop data (synthetic, $ENV_NAME)" \
    --label "data_version:$DATA_VERSION" --label "env:$ENV_NAME" --label "ns:$NS" "$PROJECT:$MAIN"
fi

load_table() {
  bq --project_id="$PROJECT" load --quiet --replace --source_format=NEWLINE_DELIMITED_JSON \
    "$PROJECT:$MAIN.$1" "$HERE/out/$1.ndjson" "$HERE/schemas/$1.json"
}

# Bounded parallel loads, portable to the bash 3.2 that macOS ships (no `wait -n`, no associative arrays): start
# jobs until MAX_PARALLEL_LOADS run, then wait for the oldest before starting the next. Each job writes its own log,
# printed only when it fails, so the output never interleaves.
LOG_DIR="$(mktemp -d)"
trap 'rm -rf "$LOG_DIR"' EXIT
RUNNING=""      # "pid:table pid:table ...", oldest first
N_RUNNING=0
LOADED=""
FAILED=""
reap_oldest() {
  local job="${RUNNING%% *}" rc=0
  RUNNING="${RUNNING#"$job"}"; RUNNING="${RUNNING# }"; N_RUNNING=$((N_RUNNING - 1))
  wait "${job%%:*}" || rc=$?
  local table="${job#*:}"
  if [[ $rc -eq 0 ]]; then
    echo "  loaded  $MAIN.$table"; LOADED="$LOADED $table"
  else
    echo "  FAILED  $MAIN.$table (bq load exit $rc):" >&2
    sed 's/^/          /' "$LOG_DIR/$table.log" >&2
    FAILED="$FAILED $table"
  fi
}

START=$SECONDS
echo "loading into $PROJECT:$MAIN, $MAX_PARALLEL_LOADS tables at a time"
for t in $ALL_TABLES; do
  wanted "$t" || continue
  [[ $N_RUNNING -lt $MAX_PARALLEL_LOADS ]] || reap_oldest
  load_table "$t" >"$LOG_DIR/$t.log" 2>&1 &
  RUNNING="${RUNNING:+$RUNNING }$!:$t"; N_RUNNING=$((N_RUNNING + 1))
done
while [[ $N_RUNNING -gt 0 ]]; do reap_oldest; done

if [[ -n "$FAILED" ]]; then
  FAILED_CSV="$(echo $FAILED | tr ' ' ',')"
  echo "ERROR: these tables failed to load into $PROJECT:$MAIN:$FAILED" >&2
  echo "       Fix the cause printed above (permissions, quota, schema), then reload only them:" >&2
  echo "       bash data/load.sh --project $PROJECT --namespace $NS --env $ENV_NAME --tables $FAILED_CSV" >&2
  exit 1
fi
echo "loaded $(echo $LOADED | wc -w | tr -d ' ') table(s) in $((SECONDS - START)) s"

# Row-count assertion against the generator's manifest, for every table just loaded: one query for all of them.
echo "verifying row counts"
python3 - "$PROJECT" "$MAIN" "$HERE" $LOADED <<'PY'
import json, subprocess, sys
project, main, here, *tables = sys.argv[1:]
sys.path.insert(0, here)
import fixtures as F
q = " UNION ALL ".join(f"SELECT '{t}' AS t, COUNT(*) AS n FROM `{project}.{main}.{t}`" for t in tables)
out = subprocess.run(["bq", f"--project_id={project}", "query", "--quiet", "--use_legacy_sql=false", "--format=json", q],
                     capture_output=True, text=True)
if out.returncode != 0:
    sys.exit(f"ERROR: the row-count query failed: {(out.stderr or out.stdout).strip()}")
counts = {r["t"]: int(r["n"]) for r in json.loads(out.stdout)}
bad = 0
for table in tables:
    expected, n = F.EXPECTED_ROW_COUNTS[table], counts[table]
    status = "OK " if n == expected else "BAD"
    if n != expected: bad += 1
    print(f"  {status} {main}.{table:16s} {n:6d} (expected {expected})")
sys.exit(1 if bad else 0)
PY

# Share the dataset with this environment's runtime identity, if the facilitator created it.
RUNTIME_SA="store-ops-${ENV_NAME}-runtime@${PROJECT}.iam.gserviceaccount.com"
if SA_ERR=$(gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT" 2>&1 >/dev/null); then
  f=$(mktemp)
  bq --project_id="$PROJECT" show --format=prettyjson "$PROJECT:$MAIN" > "$f"
  python3 - "$f" "$RUNTIME_SA" <<'PY2'
import json, sys
path, sa = sys.argv[1:]
d = json.load(open(path)); entry = {"role": "READER", "userByEmail": sa}
if not any(a.get("userByEmail") == sa for a in d["access"]):
    d["access"].append(entry)
json.dump({"access": d["access"]}, open(path, "w"))
PY2
  bq --project_id="$PROJECT" update --source "$f" "$PROJECT:$MAIN" >/dev/null && rm -f "$f"
  bq --project_id="$PROJECT" add-iam-policy-binding --member "serviceAccount:$RUNTIME_SA" \
    --role roles/bigquery.dataEditor "$PROJECT:$MAIN.store_tasks" >/dev/null
  echo "shared with $RUNTIME_SA: dataset READER, store_tasks dataEditor"
else
  echo "NOTE: not shared with a deployed engine: $RUNTIME_SA is not visible ($(echo "$SA_ERR" | tail -1 | cut -c1-120))."
  echo "      Local labs do not need it. Before \`uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json\`, the facilitator runs deployment/iam/setup_wif.sh (docs/SHARED_PROJECT.md)."
fi
echo "done: $PROJECT dataset $MAIN at DATA_VERSION $DATA_VERSION"
