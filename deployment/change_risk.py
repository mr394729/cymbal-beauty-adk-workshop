"""Review a change for risk before it moves towards an environment: what it touches, and what that means for an agent.

Two layers. Code classifies the diff first: instructions, tools, the agent tree, model or thinking settings, data
contracts, deployment and access controls each carry a fixed floor. A model then reads the diff and explains the
risk in plain language, names what a reviewer should check, and says which evaluation suites the change calls for.
The exit code is the floor plus the model's level, so a pipeline can require an approval on medium or high.

    uv run python deployment/change_risk.py --base origin/main --head HEAD --target preprod
    uv run python deployment/change_risk.py --base <sha> --head <sha> --target prod --fail-on high

Writes build/change-risk.json and build/change-risk.md. Nothing is deployed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ["low", "medium", "high"]
MAX_DIFF_CHARS = 60_000

# path prefix -> (area, floor). The floor is the least the change can be, whatever the model says.
AREAS = [
    ("agents/cymbal_store_ops/prompts/", "instructions", "medium"),
    ("agents/cymbal_store_ops/config/", "model and thinking settings", "medium"),
    ("agents/cymbal_store_ops/callbacks.py", "access controls", "high"),
    ("agents/cymbal_store_ops/plugins.py", "access controls", "high"),
    ("agents/cymbal_store_ops/governance/", "access controls", "high"),
    ("agents/cymbal_store_ops/tools/domain_tools.py", "write path and confirmation", "high"),
    ("agents/cymbal_store_ops/tools/", "tools and data contracts", "medium"),
    ("agents/cymbal_store_ops/sub_agents/", "agent tree", "medium"),
    ("agents/cymbal_store_ops/agent.py", "agent tree", "medium"),
    ("deployment/", "deployment", "medium"),
    ("cloudbuild/", "pipeline", "medium"),
    ("data/", "data contracts", "medium"),
    ("eval/", "evaluation", "low"),
    ("tests/", "tests", "low"),
    ("docs/", "documentation", "low"),
    ("notebooks/", "notebooks", "low"),
]
SUITES = {"gate": "uv run pytest tests/eval -q -k test_golden_gate_passes (seven golden cases, twice)", "broad": "eval/run_broad.py (fifty unscripted questions)",
          "journeys": "uv run python journeys/run.py (multi-turn conversations)", "safety": "the refusal and access cases in the gate",
          "smoke": "deployment/smoke.py against the deployed engine"}


class Review(BaseModel):
    level: Literal["low", "medium", "high"]
    summary: str = Field(description="Two sentences: what changed and why it matters for the agent's behaviour.")
    behaviour_changes: list[str] = Field(description="Ways the agent's answers or actions could differ after this change.")
    reviewer_checks: list[str] = Field(description="What a human reviewer should look at before approving.")
    suites: list[Literal["gate", "broad", "journeys", "safety", "smoke"]] = Field(description="Evaluation suites this change calls for.")
    unsafe_patterns: list[str] = Field(description="Anything that bypasses a control: a skipped confirmation, a widened store scope, a removed check, a hard-coded credential.")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def changed_files(base: str, head: str) -> list[str]:
    return [line for line in git("diff", "--name-only", base, head).splitlines() if line.strip()]


def classify(files: list[str]) -> tuple[list[dict], str]:
    hits, floor = [], "low"
    for path in files:
        for prefix, area, level in AREAS:
            if path.startswith(prefix):
                hits.append({"path": path, "area": area, "floor": level})
                if LEVELS.index(level) > LEVELS.index(floor):
                    floor = level
                break
        else:
            hits.append({"path": path, "area": "other", "floor": "low"})
    return hits, floor


def review_with_model(diff: str, hits: list[dict], target: str, model: str) -> Review:
    from google import genai
    from google.genai import types

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT is not set; the model review needs a project (or pass --no-model)")
    client = genai.Client(vertexai=True, project=project, location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
    areas = sorted({h["area"] for h in hits})
    prompt = (
        "You review changes to an AI agent built with Google's Agent Development Kit before they are promoted to the "
        f"{target} environment. The agent is a retail store operations assistant: it reads store data through tools, "
        "consults specialist agents, and may create or assign store tasks only after a person confirms. Controls that must "
        "never be weakened: role and store scope checks before tool calls, the confirmation on every write, contact-detail "
        "masking before the model, and the refusal of HR or disciplinary requests.\n\n"
        f"Touched areas by path: {areas}. Read the diff and assess the risk to the agent's behaviour, not code style. "
        "Be specific: name the file and the line of behaviour. Prefer 'medium' for instruction, tool or model changes that "
        "alter answers, and 'high' for anything that removes or bypasses a control or changes what the agent can write.\n\n"
        f"DIFF:\n{diff}"
    )
    response = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Review, temperature=0))
    return Review.model_validate_json(response.text)


def combine(floor: str, model_level: str | None) -> str:
    return floor if model_level is None else LEVELS[max(LEVELS.index(floor), LEVELS.index(model_level))]


def markdown(result: dict) -> str:
    lines = [f"# Change risk: **{result['level']}** for {result['target']}", "",
             f"`{result['base'][:12]}` → `{result['head'][:12]}` · {len(result['files'])} files · floor from paths: {result['floor']}", ""]
    if result.get("review"):
        r = result["review"]
        lines += [r["summary"], "", "**Behaviour that could change**"] + [f"- {x}" for x in r["behaviour_changes"]]
        lines += ["", "**Reviewer checks**"] + [f"- {x}" for x in r["reviewer_checks"]]
        if r["unsafe_patterns"]:
            lines += ["", "**Controls touched**"] + [f"- {x}" for x in r["unsafe_patterns"]]
        lines += ["", "**Run before promoting**"] + [f"- {SUITES[s]}" for s in r["suites"]]
    lines += ["", "**Files**"] + [f"- {h['path']} · {h['area']} · {h['floor']}" for h in result["files"]]
    return "\n".join(lines) + "\n"


def snapshot_input(path: Path) -> tuple[str, str, list[str], str]:
    """Verify a source archive manifest and its exact baseline diff before review."""
    manifest = json.loads(path.read_text())
    for record in manifest["files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid archive source path")
        source = ROOT / relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Archive source digest mismatch: {relative}")
    diff = path.with_name("changes.patch").read_text()
    if hashlib.sha256(diff.encode()).hexdigest() != manifest["diff_sha256"]:
        raise ValueError("Archive diff digest mismatch")
    return manifest["base"], manifest["head"], manifest["changed_files"], diff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--snapshot", type=Path, help="Verified source archive manifest, instead of a Git checkout")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--target", default="preprod", choices=["dev", "preprod", "prod"])
    parser.add_argument("--fail-on", default="high", choices=LEVELS, help="exit 1 when the combined level is at or above this")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--no-model", action="store_true", help="path classification only, no model call")
    parser.add_argument("--out", type=Path, default=ROOT / "build")
    args = parser.parse_args()

    if args.snapshot:
        base, head, files, diff = snapshot_input(args.snapshot)
    else:
        files = changed_files(args.base, args.head)
        base, head = git("rev-parse", args.base).strip(), git("rev-parse", args.head).strip()
        diff = git("diff", args.base, args.head, "--", *files) if files else ""
    hits, floor = classify(files)
    result = {"base": base, "head": head, "target": args.target,
              "files": hits, "floor": floor, "review": None,
              "source_kind": "verified_archive" if args.snapshot else "git",
              "diff_truncated": len(diff) > MAX_DIFF_CHARS}
    if files and not args.no_model:
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + f"\n[diff truncated at {MAX_DIFF_CHARS} characters]"
        review = review_with_model(diff, hits, args.target, args.model)
        result["review"] = review.model_dump()
    result["level"] = combine(floor, result["review"]["level"] if result["review"] else None)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "change-risk.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "change-risk.md").write_text(markdown(result))
    print(markdown(result))
    if not files:
        print("no changes between base and head")
    return 1 if files and LEVELS.index(result["level"]) >= LEVELS.index(args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
