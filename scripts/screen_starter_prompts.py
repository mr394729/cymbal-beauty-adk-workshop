"""Screen every tablet starter prompt through a Model Armor template and fail loudly on a false positive.

    uv run python scripts/screen_starter_prompts.py --project P --template store-ops-guard-demo [--location us-central1]

A starter prompt is one the app offers a person to click, so a template that blocks one would refuse a question the
workshop itself suggests. Run this after changing the template's filters or the starter pools, and before a demo.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.cymbal_store_ops.governance import model_armor  # noqa: E402


def starter_prompts() -> list[str]:
    text = (ROOT / "frontend" / "scenarios.yaml").read_text()
    return sorted({line.strip() for line in re.findall(r"^\s*say: (.+)$", text, flags=re.M)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--template", required=True, help="template id in the project, e.g. store-ops-guard-<namespace>")
    parser.add_argument("--location", default="us-central1")
    args = parser.parse_args()
    prompts = starter_prompts()
    blocked = []
    for prompt in prompts:
        result = model_armor.screen_prompt(args.project, args.location, args.template, prompt)
        if result["match"]:
            blocked.append((prompt, [name for name, item in result["filters"].items() if item["match"]]))
    print(f"{len(prompts)} starter prompts screened through {args.template}: {len(blocked)} blocked")
    for prompt, filters in blocked:
        print(f"  {filters} {prompt}")
    if blocked:
        print("A blocked starter prompt would be refused in the app: loosen the filter that caught it, or change the prompt.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
