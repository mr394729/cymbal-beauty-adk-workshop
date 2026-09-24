"""Run every quickstart's golden evalset through the ADK evaluator and write one table.

    uv run python scripts/eval_quickstarts.py [--only 01,05] [--num-runs 1] [--timeout 600] [--out build/quickstart_evals.md]

Each quickstart runs in its own process (their agent modules build an App at import time), with a wall-clock limit.
The result per quickstart is PASSED (every criterion met), FAILED (a threshold missed: the row names each failing
metric with its score and threshold, parsed from the evaluator's detailed summary lines) or ERROR (the agent could
not be built or run, or it ran past the timeout — a missing service such as the SOP data store or a mock API, reported
with the exception text; never hidden). The full evaluator output of each quickstart (per-invocation tables with
expected and actual tool calls and responses) is kept in build/quickstart_evals/<folder>.log, and the same rows as
CSV in <folder>.csv.

A quickstart whose golden needs an uploaded file keeps it in eval/artifacts/; each file there is saved as an artifact
into the session the evalset pins (`session_input.session_id`) before the case runs, the way the developer UI saves
an attachment. Exit code 1 if any quickstart is not PASSED.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QS = ROOT / "quickstarts"
EXIT_FAILED, EXIT_ERROR = 2, 3
DEFAULT_TIMEOUT_S = 600
# Inference failed for eval case `promo_proof` with error 1 validation error for Schema
INFERENCE_FAILED = re.compile(r"Inference failed for eval case `([^`]+)` with error (.+)")
# Summary: `EvalStatus.FAILED` for Metric: `tool_trajectory_avg_score`. Expected threshold: `1.0`, actual value: `0.0`.
SUMMARY = re.compile(r"Summary: `(?:EvalStatus\.)?(\w+)` for Metric: `([^`]+)`\. Expected threshold: `([^`]*)`, actual value: `([^`]*)`")


def _artifact_service(evalset_path: Path):
    """An in-memory artifact service holding eval/artifacts/* in each pinned session, or None when there are none."""
    files = sorted(p for p in (evalset_path.parent / "artifacts").glob("*") if p.is_file())
    if not files:
        return None
    import asyncio

    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.evaluation.eval_set import EvalSet
    from google.genai import types

    es = EvalSet.model_validate_json(evalset_path.read_text())
    service = InMemoryArtifactService()
    for case in es.eval_cases:
        si = case.session_input
        if not (si and si.session_id):
            raise RuntimeError(f"{evalset_path}: eval/artifacts/ exists, so case {case.eval_id} must pin session_input.session_id")
        for f in files:
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            asyncio.run(service.save_artifact(app_name=si.app_name, user_id=si.user_id, session_id=si.session_id,
                                              filename=f.name, artifact=types.Part.from_bytes(data=f.read_bytes(), mime_type=mime)))
    return service


def run_one(folder: str, num_runs: int, csv_path: str | None) -> int:
    import asyncio

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(QS))
    for key, value in {  # the values conftest.py provides for import-time construction
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_LOCATION": "global",
        "ORDERS_API_KEY": "demo-key",
    }.items():
        os.environ.setdefault(key, value)
    from google.adk.evaluation.agent_evaluator import AgentEvaluator

    evalset = next((QS / folder / "eval").glob("*.evalset.json"))
    try:
        asyncio.run(AgentEvaluator.evaluate(agent_module=f"{folder}.agent", eval_dataset_file_path_or_dir=str(evalset),
                                            num_runs=num_runs, print_detailed_results=True,
                                            artifact_service=_artifact_service(evalset), output_file=csv_path))
    except AssertionError as failure:
        print(f"RESULT FAILED {' '.join(str(failure).split())[:600]}", flush=True)
        return EXIT_FAILED
    except Exception as e:  # noqa: BLE001 — reported, never swallowed
        print(f"RESULT ERROR {type(e).__name__}: {' '.join(str(e).split())[:400]}", flush=True)
        return EXIT_ERROR
    print("RESULT PASSED", flush=True)
    return 0


def failing_metrics(stdout: str) -> str:
    """'metric score < threshold' for every summary line that did not pass, in evaluator order."""
    out = []
    for status, metric, threshold, actual in SUMMARY.findall(stdout):
        if status != "PASSED":
            value = "not evaluated" if status == "NOT_EVALUATED" else f"{_short(actual)} < {threshold}"
            out.append(f"{metric} {value}")
    return "; ".join(out)


def _short(value: str) -> str:
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return value


MOCK_ORDERS_PORT = 8010


A2A_PORT = 8002


@contextlib.contextmanager
def _a2a_store_ops_server():
    """Quickstart 12 delegates to the store operations app served over A2A on localhost (its README's first command).
    Start it when the port is free, wait for the agent card, stop it afterwards; a server that will not start is an
    ERROR with the command."""
    import socket
    import urllib.request

    def listening() -> bool:
        with socket.socket() as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", A2A_PORT)) == 0

    if listening():
        yield
        return
    adk = Path(sys.executable).with_name("adk")
    cmd = [str(adk), "api_server", "--a2a", "quickstarts/12-a2a-agent/server", "--port", str(A2A_PORT)]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    card = f"http://127.0.0.1:{A2A_PORT}/a2a/cymbal_store_ops/.well-known/agent-card.json"
    try:
        for _ in range(120):
            try:
                with urllib.request.urlopen(card, timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError(f"the store operations A2A server did not publish its card at {card}: {' '.join(cmd)}")
        yield
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=15)


@contextlib.contextmanager
def local_fixture_services(folder: str):
    """Quickstart 04 calls a local mock of the order management API (its fixture, not an external dependency): start it
    for the evaluation when nothing answers on the port, stop it afterwards. A mock that will not start is an ERROR
    with the command, never a scored "the API was down" answer."""
    if folder.startswith("12-") and not os.environ.get("STORE_OPS_A2A_URL"):
        with _a2a_store_ops_server():
            yield
        return
    if not folder.startswith("04-") or os.environ.get("ORDERS_API_URL"):
        yield
        return
    import urllib.request

    def up() -> bool:
        req = urllib.request.Request(f"http://127.0.0.1:{MOCK_ORDERS_PORT}/orders/BO-000651",
                                     headers={"X-API-Key": os.environ.get("ORDERS_API_KEY", "demo-key")})
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status == 200
        except OSError:
            return False

    if up():
        yield
        return
    cmd = [sys.executable, "-m", "uvicorn", "quickstarts._services.orders_api.app:app", "--port", str(MOCK_ORDERS_PORT)]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                            env={**os.environ, "ORDERS_API_KEY": os.environ.get("ORDERS_API_KEY", "demo-key")})
    try:
        for _ in range(40):
            if up():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(f"the mock orders API did not start: {' '.join(cmd)}")
        yield
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)


def run_child(folder: str, num_runs: int, timeout_s: int, log_dir: Path) -> tuple[str, str, int]:
    """Evaluate one quickstart in a child process group; kill the whole group (MCP servers included) on timeout."""
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{folder}.csv").unlink(missing_ok=True)   # the evaluator appends; one run per file
    proc = subprocess.Popen([sys.executable, __file__, "--one", folder, "--num-runs", str(num_runs),
                             "--csv", str(log_dir / f"{folder}.csv")], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        timed_out = True
    (log_dir / f"{folder}.log").write_text(f"exit {proc.returncode}\n--- stdout\n{stdout}\n--- stderr\n{stderr}\n")
    if timed_out:
        return "ERROR", f"timed out after {timeout_s} s", EXIT_ERROR
    line = next((ln for ln in stdout.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        tail = " ".join(stderr.strip().splitlines()[-3:])[-300:]
        return "ERROR", f"exit {proc.returncode}: {tail}", proc.returncode or EXIT_ERROR
    status, _, detail = line[len("RESULT "):].partition(" ")
    if status == "FAILED":
        inference = [f"{case}: inference failed: {msg.strip()}" for case, msg in INFERENCE_FAILED.findall(stdout + stderr)]
        detail = "; ".join(filter(None, [failing_metrics(stdout), *inference])) or detail
    return status, detail, proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated two-digit prefixes, e.g. 01,05")
    ap.add_argument("--num-runs", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="wall-clock seconds per quickstart")
    ap.add_argument("--out", default=str(ROOT / "build" / "quickstart_evals.md"))
    ap.add_argument("--one", metavar="FOLDER", help="(internal) evaluate one quickstart in this process")
    ap.add_argument("--csv", help="(internal, with --one) write the per-invocation results here")
    a = ap.parse_args()
    if a.one:
        return run_one(a.one, a.num_runs, a.csv)
    folders = sorted(p.name for p in QS.iterdir() if p.is_dir() and p.name[:2].isdigit() and (p / "eval").is_dir())
    if a.only:
        wanted = {x.strip() for x in a.only.split(",")}
        folders = [f for f in folders if f[:2] in wanted]
    out = Path(a.out).resolve()
    log_dir = out.parent / "quickstart_evals"
    rows, worst = [], 0
    for folder in folders:
        t0 = time.time()
        try:
            with local_fixture_services(folder):
                status, detail, code = run_child(folder, a.num_runs, a.timeout, log_dir)
        except RuntimeError as e:
            status, detail, code = "ERROR", str(e), EXIT_ERROR
        seconds = time.time() - t0
        rows.append((folder, status, f"{seconds:.0f} s", detail.replace("|", "/").replace("\n", " ")[:300]))
        worst = max(worst, code)
        print(f"{folder:32s} {status:7s} {seconds:5.0f} s  {detail[:160]}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    logs = log_dir.relative_to(ROOT) if log_dir.is_relative_to(ROOT) else log_dir
    md = ["# Quickstart golden evals", "",
          f"`{len(folders)}` quickstarts, `num_runs={a.num_runs}`, timeout `{a.timeout} s` each; thresholds from each "
          f"`eval/test_config.json`; full evaluator output per quickstart in `{logs}/`.", "",
          "| Quickstart | Result | Time | Detail |", "|---|---|---|---|"]
    md += [f"| {f} | {s} | {t} | {d} |" for f, s, t, d in rows]
    out.write_text("\n".join(md) + "\n")
    print(f"written: {out}")
    print(json.dumps({s: sum(1 for r in rows if r[1] == s) for s in ("PASSED", "FAILED", "ERROR")}))
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main())
