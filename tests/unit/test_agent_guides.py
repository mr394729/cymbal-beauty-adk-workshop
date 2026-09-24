"""AGENTS.md, CLAUDE.md and GEMINI.md are the same file, so every coding agent reads the same instructions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_three_agent_guides_are_identical():
    agents = (ROOT / "AGENTS.md").read_text()
    assert (ROOT / "CLAUDE.md").read_text() == agents, "copy AGENTS.md to CLAUDE.md"
    assert (ROOT / "GEMINI.md").read_text() == agents, "copy AGENTS.md to GEMINI.md"
