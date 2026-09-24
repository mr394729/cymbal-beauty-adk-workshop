"""Catalog-level checks for quickstarts/ plus each quickstart's own unit suite (no cloud, no model).

Every quickstart is a self-contained folder; its tests live next to it (quickstarts/<nn>-<name>/tests)
so the folder stays copyable. This file runs each of those suites in its own process and checks the
conventions the catalog README promises.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QUICKSTARTS = ROOT / "quickstarts"
FOLDERS = sorted(p for p in QUICKSTARTS.iterdir() if re.fullmatch(r"\d{2}-[a-z0-9-]+", p.name))
README_SECTIONS = ["Overview", "Architecture", "What the agent does", "Prerequisites", "Run the agent", "Test the agent",
                   "Clean up", "Learn more"]
LINK_ALLOWLIST = ("https://adk.dev/", "https://docs.cloud.google.com/", "https://cloud.google.com/",
                  "https://google.github.io/adk-docs", "https://github.com/google/adk-samples",
                  "https://github.com/mr394729",  # the author link in each README
                  "https://open-meteo.com/")  # the public weather API quickstart 04 calls


def test_catalog_has_the_twelve_shipped_quickstarts():
    """The shipped set is 01-12; a quickstart an attendee adds (13-...) is allowed and must pass the layout tests."""
    prefixes = [p.name[:2] for p in FOLDERS]
    assert prefixes[:12] == [f"{i:02d}" for i in range(1, 13)], prefixes
    assert prefixes == sorted(prefixes) and len(set(prefixes)) == len(prefixes), "numbered, no duplicates"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_layout(folder: Path):
    assert (folder / "__init__.py").read_text().strip().startswith("from . import agent")
    assert (folder / "agent.py").exists() and (folder / "README.md").exists()
    assert (folder / "tests" / "test_unit.py").exists()
    evalsets = list((folder / "eval").glob("*.evalset.json"))
    assert evalsets and (folder / "eval" / "test_config.json").exists()
    agent_lines = [ln for ln in (folder / "agent.py").read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert len(agent_lines) <= 160, f"{folder.name}/agent.py has {len(agent_lines)} code lines (keep it copyable)"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_readme_template_and_links(folder: Path):
    text = (folder / "README.md").read_text()
    h2 = [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]
    assert h2 == README_SECTIONS, f"{folder.name}: sections {h2}"
    markdown_image = re.search(r"!\[[^\]]+\]\(\.\./\.\./docs/diagrams/q\d{2}\.png\)", text)
    html_image = re.search(r'<img[^>]*src="\.\./\.\./docs/diagrams/q\d{2}\.png"[^>]*alt="[^"]+"', text)
    assert markdown_image or html_image, "diagram reference with alt text"
    for url in re.findall(r"\((https?://[^)\s]+)\)", text):
        assert url.startswith(LINK_ALLOWLIST), f"{folder.name}: {url} is not in the verified link allowlist"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_no_customer_name_in_code(folder: Path):
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".sh", ".md", ".txt"} and path.name != "README.md":
            assert "ulta" not in path.read_text(errors="ignore").lower(), f"{path} mentions the customer; only README 'Extend it' may"
    readme = (folder / "README.md").read_text()
    body, _, extend = readme.partition("## Extend the example")
    assert "ulta" not in body.lower(), f"{folder.name}: 'Ulta' outside the Extend section"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_evalset_is_current_schema(folder: Path):
    from google.adk.evaluation.eval_config import EvalConfig
    from google.adk.evaluation.eval_set import EvalSet
    for path in (folder / "eval").glob("*.evalset.json"):
        es = EvalSet.model_validate_json(path.read_text())
        assert es.eval_cases and all(c.conversation for c in es.eval_cases)
    EvalConfig.model_validate(json.loads((folder / "eval" / "test_config.json").read_text()))


def test_evalsets_match_generator():
    proc = subprocess.run([sys.executable, str(QUICKSTARTS / "_scripts" / "make_evalsets.py"), "--check"],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_quickstart_unit_suite(folder: Path):
    """Each quickstart's own tests, run the way an attendee would run them from a copied folder."""
    with tempfile.TemporaryDirectory(prefix="quickstart-no-adc-") as directory:
        # A developer's local ADC must not conceal an import-time cloud dependency.
        env = {**os.environ, "GOOGLE_APPLICATION_CREDENTIALS": str(Path(directory) / "absent-adc.json")}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(folder / "tests"), "-q", "-p", "no:cacheprovider",
             "--import-mode=importlib", "-o", "addopts=", "-W", "ignore::UserWarning"],
            capture_output=True, text=True, cwd=ROOT, env=env)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
