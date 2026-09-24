"""Prompt loader: renders {{PLACEHOLDERS}} from config only (no network at import), leaves ADK's {state?} templates untouched."""
from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def store_time() -> str:
    """The workshop's fixed current time, written out, so an agent does not spend a model call asking the clock."""
    from datetime import datetime

    from agents.cymbal_store_ops import fixtures as F

    now = datetime.fromisoformat(F.FIXTURE_NOW_ISO)
    return f"{now:%A %-d %B %Y, %-I:%M %p} ({F.FIXTURE_TIMEZONE}, {now.isoformat()})"


def load_prompt(name: str) -> str:
    from agents.cymbal_store_ops.config import load_env_config

    text = (PROMPT_DIR / f"{name}.md").read_text()
    if "{{" not in text:
        return text
    cfg = load_env_config()
    project_id, dataset_id = cfg.project, cfg.bigquery.dataset
    values = {"DIALECT": cfg.dialect, "PROJECT_ID": project_id, "DATASET_ID": dataset_id,
              "TABLE_PREFIX": f"{project_id}.{dataset_id}", "ENV": cfg.env, "STORE_TIME": store_time()}
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text
