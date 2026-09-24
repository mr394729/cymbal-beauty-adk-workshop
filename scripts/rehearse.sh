#!/usr/bin/env bash
# Rehearse the attendee path end to end, in module order, with timings.
#
#   bash scripts/rehearse.sh [--deploy] [--sops]
#   bash scripts/rehearse.sh
#
# Every step is a command an attendee or the facilitator runs on the day, taken from the module READMEs.
# Steps marked "fail" are expected to fail: the evaluation gate refusing to score over lab writes, and the
# two injected faults. A step that does not do what it says is reported as UNEXPECTED and the run exits 1.
#
# Writes build/rehearsal.log (full output) and build/rehearsal.summary.md (one row per step), and prints
# the summary at the end. Nothing outside WORKSHOP_NAMESPACE is created, changed or deleted.
#
# Cost and time: the offline path is roughly 25 minutes of model calls; --deploy adds about 25 minutes
# (two deploys, a smoke run and the remote goldens); --sops adds about 10 minutes the first time.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_DEPLOY=0
WITH_SOPS=0
for arg in "$@"; do
  case "$arg" in
    --deploy) WITH_DEPLOY=1 ;;
    --sops)   WITH_SOPS=1 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (expected --deploy, --sops)" >&2; exit 2 ;;
  esac
done

cd "$ROOT" || exit 2
mkdir -p build
LOG="$ROOT/build/rehearsal.log"
SUMMARY="$ROOT/build/rehearsal.summary.md"
: > "$LOG"

die() { echo "$1" >&2; echo "  Fix: $2" >&2; exit 3; }

# --- preconditions: the same ones uv run python scripts/check_env.py --stage prereqs checks, but loud and first, so a two-hour rehearsal
# --- does not stop 20 minutes in on an expired credential.
[[ -f .env ]] || die ".env is missing" "cp .env.example .env and set GOOGLE_CLOUD_PROJECT"
set -a; . ./.env; set +a
[[ -n "${GOOGLE_CLOUD_PROJECT:-}" ]] || die "GOOGLE_CLOUD_PROJECT is not set" "edit .env"
[[ -n "${WORKSHOP_NAMESPACE:-}" ]] || die "WORKSHOP_NAMESPACE is not set" "uv run python scripts/namespace.py"
gcloud auth print-access-token >/dev/null 2>&1 || die "the gcloud CLI sign-in has expired" "gcloud auth login"
gcloud auth application-default print-access-token >/dev/null 2>&1 \
  || die "application default credentials have expired" "gcloud auth application-default login"

STARTED=$(date +%s)
ROWS=()
FAILURES=0

# step <expect: ok|fail> <critical: crit|cont> <label> <command...>
step() {
  local expect="$1" critical="$2" label="$3"; shift 3
  local t0 rc dt verdict shown
  shown="${*//$'\n'/ }"                    # one line per row, whatever the command looked like
  t0=$(date +%s)
  printf '\n===== %s :: %s\n' "$label" "$shown" | tee -a "$LOG"
  "$@" >> "$LOG" 2>&1; rc=$?
  dt=$(( $(date +%s) - t0 ))
  verdict="ok"
  if [[ "$expect" == ok && $rc -ne 0 ]] || [[ "$expect" == fail && $rc -eq 0 ]]; then verdict="UNEXPECTED"; fi
  printf '%-10s %-46s rc=%-3s %5ss\n' "$verdict" "$label" "$rc" "$dt" | tee -a "$LOG"
  ROWS+=("| $verdict | $label | \`${shown:0:110}\` | $expect | $rc | ${dt}s |")
  if [[ "$verdict" != ok ]]; then
    FAILURES=$((FAILURES + 1))
    if [[ "$critical" == crit ]]; then
      write_summary "stopped after $label: the steps below it depend on it"
      echo "stopped at $label; full output in $LOG" >&2
      exit 1
    fi
  fi
}

write_summary() {
  local note="${1:-}"
  {
    echo "# Rehearsal $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo
    echo "project \`$GOOGLE_CLOUD_PROJECT\` · namespace \`$WORKSHOP_NAMESPACE\` ·"
    echo "deploy steps: $([[ $WITH_DEPLOY == 1 ]] && echo yes || echo no) ·" \
         "retrieval steps: $([[ $WITH_SOPS == 1 ]] && echo yes || echo no)"
    echo
    echo "| Verdict | Step | Command | Expected | rc | Time |"
    echo "|---|---|---|---|---|---|"
    printf '%s\n' ${ROWS[@]+"${ROWS[@]}"}
    echo
    echo "$FAILURES unexpected result(s); total $(( ($(date +%s) - STARTED) / 60 )) min. Full output: \`build/rehearsal.log\`."
    [[ -n "$note" ]] && { echo; echo "$note"; }
  } > "$SUMMARY"
}

# --- module 0: setup and the coding agent -------------------------------------------------------
step ok   crit "module 0: prereqs"                   uv run python scripts/check_env.py --stage prereqs
step ok   cont "module 0: skills installed"          bash scripts/install_skills.sh --agent antigravity
step ok   cont "module 0: unit tests (agent prompt)" uv run pytest tests/unit -q

# --- store agent: the data the labs read -----------------------------------------------------------
step ok   crit "store agent: data"                      uv run python data/generate.py && bash data/load.sh --env dev
step ok   crit "store agent: ready"                     uv run python scripts/check_env.py --stage ready
step ok   cont "store agent: reference prompts"             uv run python scripts/smoke_local.py --session fresh

# --- module 1: the pattern scripts --------------------------------------------------------------
step ok   cont "module 1: patterns"                  uv run python quickstarts/10-multi-agent-router/patterns/01_coordinator_vs_single_turn.py

# --- module 3: data access, evidence, retrieval -------------------------------------------------
step ok   cont "data contract probe"            uv run python scripts/probe_data_contract.py
step ok   cont "module 3: query evidence"            uv run python scripts/evidence.py --hours 1
# --- module 4: the evaluation gate --------------------------------------------------------------
# A confirmed task action wrote a task, so the gate must refuse to score before the fixtures are reloaded.
step fail cont "module 4: gate refuses lab writes"   uv run pytest tests/eval -q -k test_golden_gate_passes
step ok   crit "module 4: reset fixtures"            bash data/load.sh --env dev --tables store_tasks

# The SOP extension is module 3 on the day, but its `uv run python scripts/check_env.py --stage ready` verification also checks the fixture rows, which
# A confirmed task write fails until the reset above (pass 4, 2026-09-17: "store_tasks rows 401 (expected 400)"). The
# module README tells attendees the same: reset first, or read the three SOP rows.
if [[ $WITH_SOPS == 1 ]]; then
  step ok cont "module 3: SOP data store"            uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup
  step ok cont "module 3: ready with SOPs"           uv run python scripts/check_env.py --stage ready
fi
step ok   crit "module 4: build evalsets"            uv run python eval/build_eval_set.py
step ok   cont "module 4: gate"                      uv run pytest tests/eval -q -k test_golden_gate_passes
step fail cont "module 4: fault stale_stock"         STORE_OPS_FAULT=stale_stock uv run pytest tests/eval -q -k test_golden_gate_passes
step fail cont "module 4: fault stale_backlog"       STORE_OPS_FAULT=stale_backlog uv run pytest tests/eval -q -k test_golden_gate_passes
step ok   cont "module 4: fault meta-tests"          uv run pytest tests/eval -q -k test_fault_switch_breaks_the_gate
step ok   cont "module 4: model comparison"          uv run python eval/compare_models.py --models gemini-3.8-flash,gemini-2.5-pro

# --- module 5 and 6: the deployed engine --------------------------------------------------------
if [[ $WITH_DEPLOY == 1 ]]; then
  step ok crit "module 5: deploy dev"                uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json
  step ok cont "module 5: redeploy, same engine"     uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json
  step ok cont "module 5: exactly one engine"        uv run python -c "
from deployment._common import client_for, find_engines_by_labels, load_config
cfg = load_config('dev')
found = find_engines_by_labels(client_for(cfg), cfg)
print(found)
raise SystemExit(0 if len(found) == 1 else 1)"
  step ok cont "module 5: traffic list"              uv run python deployment/traffic.py list --env dev
  step ok cont "module 6: smoke dev"                 uv run python deployment/smoke.py --env dev
  step ok cont "module 4/6: remote goldens"          uv run python deployment/remote_eval.py --env dev
  step ok cont "module 6: registry entry"            gcloud agent-registry agents list \
    --project="$GOOGLE_CLOUD_PROJECT" --location=us-central1 \
    --filter="displayName=cymbal-store-ops-${WORKSHOP_NAMESPACE}-dev" \
    --format='table(displayName,createTime.date())'
fi

# --- what the room leaves behind ----------------------------------------------------------------
step ok   cont "resources in this namespace"         uv run python scripts/resources.py

write_summary
cat "$SUMMARY"
[[ $FAILURES -eq 0 ]] || exit 1
