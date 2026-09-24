"""The check every cloud-facing command runs first: is the Google sign-in still valid?

A sign-in lasts hours, a workshop lasts a morning, and the two credentials expire separately: application default
credentials (Python: ADK, the evaluations, the deploy scripts) and the gcloud CLI (gcloud, bq, `uv run python data/generate.py && bash data/load.sh --env dev`). With
either one expired, eleven lab commands used to end in a stack trace — `uv run pytest tests/eval -q -k test_golden_gate_passes` as a pytest INTERNALERROR,
`uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup` as "503 ServiceUnavailable", `uv run python journeys/run.py` with one traceback per turn. Now each stops in a second or
two with the same words and the fix.

    uv run python -m agents.cymbal_store_ops.preflight [--cli]
"""
from __future__ import annotations

import subprocess
import sys

ADC_FIX = "gcloud auth application-default login"
CLI_FIX = "gcloud auth login"


def adc_problem() -> str | None:
    """None when application default credentials refresh; otherwise the first line of why not."""
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError, RefreshError
    from google.auth.transport.requests import Request

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
    except (DefaultCredentialsError, RefreshError) as e:
        return (str(e).splitlines() or ["no usable credentials"])[0][:160]
    return None


def cli_problem() -> str | None:
    """None when `gcloud auth print-access-token` works; otherwise the first line of why not."""
    try:
        proc = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return "gcloud is not installed"
    except subprocess.TimeoutExpired:
        return "gcloud did not answer in 30 s"
    if proc.returncode == 0:
        return None
    return (proc.stderr.strip().splitlines() or ["gcloud auth print-access-token failed"])[0][:160]


def require_sign_in(cli: bool = False) -> None:
    """Stop now, in words, when the sign-in this command needs has expired. `cli=True` also checks the gcloud CLI
    (for commands that shell out to gcloud or bq)."""
    problems = []
    if why := adc_problem():
        problems.append(("application default credentials (Python: ADK, evaluations, deploy scripts)", why, ADC_FIX))
    if cli and (why := cli_problem()):
        problems.append(("the gcloud CLI (gcloud, bq, uv run python data/generate.py && bash data/load.sh --env dev)", why, CLI_FIX))
    if not problems:
        return
    lines = ["Your Google sign-in has expired or is missing; nothing was run."]
    for what, why, fix in problems:
        lines += [f"  {what}: {why}", f"    Fix: {fix}"]
    lines.append("  Then rerun this command. `uv run python scripts/check_env.py --stage prereqs` checks everything at once.")
    raise SystemExit("\n".join(lines))


if __name__ == "__main__":
    require_sign_in(cli="--cli" in sys.argv[1:])
