"""Quickstart 03 — form completion agent (slot filling with validation and a confirmed submit).

An associate reports damaged, missing or suspicious units for the shrink log. The report has five slots: product,
quantity, event type (damage | unknown_loss | return_anomaly), location in the store and a short note. The agent
takes whatever the associate already said, asks only for what is missing, resolves the product against the catalog
(`find_product`), offers the event type as a choice (`get_user_choice`, a long-running tool the UI renders as
buttons) and submits only after the associate confirms (`require_confirmation=True`).

The submit validates every field and is idempotent (`temp:` state), but it writes NOTHING: it returns the record
the store operations app would log to `shrink_events`. The store comes from session state (`user:store_id`).
"""
from __future__ import annotations

import hashlib
import re
import warnings

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.tools import FunctionTool, ToolContext, get_user_choice  # noqa: E402

from agents.cymbal_store_ops.callbacks import redact  # noqa: E402
from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    identify_demo_user,
    search_products,
)

EVENT_TYPES = ["damage", "unknown_loss", "return_anomaly"]
MAX_QUANTITY = 50

INSTRUCTION = f"""You take incident reports from Cymbal Beauty store associates for the shrink log. Signed-in store:
{{user:store_id?}}. A report has five fields: product, quantity, event type, location in the store, and a short note.
- If no store is signed in, ask for the associate's demo id (for example A-1004) and call identify_demo_user.
- Use everything the associate already said; ask only for what is missing, one short question at a time.
- As soon as you know the product, call find_product; if several products match, ask which one.
- If the event type is unclear, call get_user_choice with the options {EVENT_TYPES}.
- The note says what happened, never who: no names, phone numbers or emails.
- When all five fields are known, call submit_incident_report once (the associate confirms in a dialog). Then give
  the incident id and say it was not written to the shrink log: this quickstart only shows the record.
Never invent a product id, a quantity or a location."""


def err(details: str) -> dict:
    return {"status": "ERROR", "error_details": details}


def find_product(product_name: str) -> dict:
    """Resolve a product the associate named (e.g. "Hydra Cream") to catalog rows: product_id, name, brand, category."""
    result = search_products(query_text=product_name, limit=5)
    if result.get("status") != "SUCCESS":
        return result
    if not result["rows"]:
        return err(f"no product matches {product_name!r}; ask the associate for the name on the label")
    keep = ("product_id", "name", "brand", "category", "locked_case")
    return {"status": "SUCCESS", "rows": [{k: r.get(k) for k in keep} for r in result["rows"]]}


def submit_incident_report(product_id: str, quantity: int, event_type: str, location: str, note: str,
                           tool_context: ToolContext) -> dict:
    """Submit the incident report after the associate confirms. Validates every field; safe to retry.

    Args:
        product_id: from find_product, e.g. P-0101.
        quantity: units affected (1-50).
        event_type: damage | unknown_loss | return_anomaly.
        location: where in the store, e.g. "skincare aisle" or "backroom".
        note: one sentence about what happened; no names or contact details.
    """
    store_id = tool_context.state.get("user:store_id")
    if not store_id:
        return err("no store is signed in: call identify_demo_user with the associate's demo id first")
    problems = []
    if not re.fullmatch(r"P-\d{4}", product_id or ""):
        problems.append("product_id must come from find_product (like P-0101)")
    if not 1 <= int(quantity) <= MAX_QUANTITY:
        problems.append(f"quantity must be 1-{MAX_QUANTITY}")
    if event_type not in EVENT_TYPES:
        problems.append(f"event_type must be one of {EVENT_TYPES}")
    if not location.strip():
        problems.append("location is required")
    if not note.strip() or len(note) > 200:
        problems.append("note must be one sentence (1-200 characters)")
    elif redact(note) != note:
        problems.append("remove phone numbers and emails from the note")
    if problems:
        return err("; ".join(problems))
    record = {"store_id": store_id, "product_id": product_id, "quantity": int(quantity), "event_type": event_type,
              "location": location.strip(), "note": note.strip(), "reported_by": tool_context.state.get("user:user_id", "")}
    key = "temp:incident:" + hashlib.sha256(repr(sorted(record.items())).encode()).hexdigest()[:12]
    incident_id = tool_context.state.get(key) or f"INC-{int(key[-6:], 16) % 100000:05d}"
    tool_context.state[key] = incident_id
    return {"status": "SUCCESS", "written": False, "rows": [{"incident_id": incident_id, **record}],
            "note": "not written: this quickstart returns the record the store operations app would log to shrink_events"}


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    return LlmAgent(
        name="form_completion_agent",
        model=workshop_model(cfg),
        description="Takes an associate's damage or loss report slot by slot and submits it after confirmation.",
        instruction=INSTRUCTION,
        tools=[identify_demo_user, find_product, get_user_choice,
               FunctionTool(submit_incident_report, require_confirmation=True)],
        output_key="incident_summary",
    )


def create_app() -> App:
    return App(name="form_completion_agent", root_agent=make_root_agent())


app = create_app()
root_agent = app.root_agent
