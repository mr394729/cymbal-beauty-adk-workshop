"""The lab notebooks and quickstart walkthroughs follow the GoogleCloudPlatform/generative-ai sample style.

Every code cell shows the SDK call that does the work: no helper module, no make targets, no run flags. Notebooks
open with the licence header and keep diagrams at most 60 % wide. They are committed either with outputs cleared or
with the outputs of one complete run (every code cell executed, no errors) and a note on clearing them, so an attendee
whose own run fails can still read what each cell prints.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = sorted(ROOT.glob("notebooks/[0-9][0-9]_*.ipynb")) + sorted(ROOT.glob("quickstarts/*/walkthrough.ipynb"))
FORBIDDEN = [
    (re.compile(r"from notebooks import workshop|import workshop as w|\bw\.\w+\("), "the old notebook helper module"),
    (re.compile(r"^\s*!?\s*make\s+[a-z]", re.M), "a make target"),
    (re.compile(r"\bRUN_[A-Z_]+\s*=\s*(False|True)"), "a run flag"),
    (re.compile(r"\bmake\s+(deploy|data|eval|sops|test|web|smoke|frontend)\b"), "a make target in the text"),
]


def cells(path: Path) -> list[dict]:
    return json.loads(path.read_text())["cells"]


def test_the_notebooks_exist():
    assert len([p for p in NOTEBOOKS if p.parent.name == "notebooks"]) == 8
    assert len([p for p in NOTEBOOKS if p.name == "walkthrough.ipynb"]) == 12


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: str(p.relative_to(ROOT)))
def test_notebook_style(path: Path):
    notebook = cells(path)
    assert notebook[0]["cell_type"] == "code" and "Licensed under the Apache License" in "".join(notebook[0]["source"])
    assert notebook[1]["cell_type"] == "markdown" and "".join(notebook[1]["source"]).lstrip().startswith("# ")
    code = [cell for cell in notebook if cell["cell_type"] == "code"]
    executed = any(cell.get("outputs") or cell.get("execution_count") for cell in code)
    if executed:
        assert all(cell.get("execution_count") for cell in code), "commit the outputs of one complete run, or none"
        assert not [o for cell in code for o in cell.get("outputs", []) if o.get("output_type") == "error"], "a cell failed"
        assert "Clear Outputs" in "".join(notebook[2]["source"]), "say how to clear the saved outputs, right after the title"
    for cell in notebook:
        text = "".join(cell["source"])
        for pattern, what in FORBIDDEN:
            assert not pattern.search(text), f"{what} in: {text[:120]!r}"
        for width in re.findall(r'<img[^>]*width="(\d+)%', text):
            assert int(width) <= 60, "keep diagrams at most 60 % wide"
    headings = [line for cell in notebook if cell["cell_type"] == "markdown"
                for line in "".join(cell["source"]).splitlines() if line.startswith("## ")]
    for required in ("## Overview", "## Get started", "## Cleaning up"):
        assert required in headings, f"missing {required}"
