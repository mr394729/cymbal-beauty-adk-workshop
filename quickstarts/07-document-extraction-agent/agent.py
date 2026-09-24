"""Quickstart 07 — document extraction agent (multimodal, structured output, generate-and-review, deterministic check).

Shelf and graphic proofing: attach a store's promotion signage proof (PDF or image) in the developer UI. The
`SaveFilesAsArtifactsPlugin` stores the upload as an artifact; a `before_model_callback` adds it to each of the
extractor's requests, and the extractor returns JSON matching `PromoProof` (`output_schema`); the critic checks the draft's form and calls `exit_loop` when it holds
(`LoopAgent`, at most two rounds). Then `compare_promo_proof` — plain code, no model — compares the extracted lines
with the week's promotion plan (promo_plan_2026W40.json; in production the promotions table) and the checker reports
the discrepancies. The model reads the document; code decides what is wrong.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent  # noqa: E402
from google.adk.agents.callback_context import CallbackContext  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.adk.plugins.save_files_as_artifacts_plugin import (  # noqa: E402
    SaveFilesAsArtifactsPlugin,
)
from google.adk.tools import ToolContext, exit_loop  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402

PLAN = Path(__file__).with_name("promo_plan_2026W40.json")


class PromoLine(BaseModel):
    line: int = Field(description="the line number printed on the proof")
    product_id: str = Field(description="as printed, like P-0101")
    product_name: str
    sign_type: str
    promo_price_usd: float = Field(ge=0, description="the printed promotional price, without the $ sign")
    start_date: str = Field(description="YYYY-MM-DD as printed")
    end_date: str = Field(description="YYYY-MM-DD as printed")


class PromoProof(BaseModel):
    store_id: str = Field(description="like S-014")
    week: str = Field(description="promotion week like 2026-W40")
    lines: list[PromoLine]
    confidence: float = Field(ge=0, le=1, description="0-1; below 0.7 goes to a person")
    needs_human_review: bool = False


EXTRACT = """The promotion signage proof the user uploaded is attached to this request. Extract it as JSON matching
the schema: the store id, the promotion week and one entry per numbered line. Copy product ids, names, sign types,
prices (numbers, no $) and dates (YYYY-MM-DD) exactly as printed; never correct a value to what you think it should
be, because the cross-check needs what is printed. Set confidence honestly and needs_human_review when any value is
hard to read. If a review is in the conversation, fix exactly what it names."""

REVIEW = """Review this extracted promotion proof: {proof?}
Rules: every line has a product id like P-0101; every price is a positive number; dates are YYYY-MM-DD and no line
ends before it starts; line numbers run 1, 2, 3 ... without gaps; the week looks like 2026-W40. If every rule holds,
call exit_loop. Otherwise do not call it; reply with a numbered list of the violations."""

CHECK = """Call compare_promo_proof once. Then report to the signage team in plain text: how many discrepancies, then
one line per discrepancy with the proof line number, product id and name, what the proof says and what the plan
says. If there are none, say the proof matches the plan. Never add a discrepancy the tool did not return."""


def compare(proof: dict, plan: dict) -> list[dict]:
    """Deterministic cross-check of extracted proof lines against the promotion plan."""
    planned = {p["product_id"]: p for p in plan["promotions"]}
    found: list[dict] = []
    if proof.get("week") != plan["week"]:
        found.append({"line": None, "product_id": None, "issue": "wrong_week", "proof": proof.get("week"), "plan": plan["week"]})
    for line in proof.get("lines", []):
        base = {"line": line["line"], "product_id": line["product_id"], "product_name": line.get("product_name")}
        p = planned.get(line["product_id"])
        if p is None:
            found.append({**base, "issue": "not_on_promotion", "proof": f"${line['promo_price_usd']:.2f}", "plan": "no promotion this week"})
            continue
        if abs(float(line["promo_price_usd"]) - p["promo_price_usd"]) > 0.005:
            found.append({**base, "issue": "price_mismatch", "proof": f"${line['promo_price_usd']:.2f}", "plan": f"${p['promo_price_usd']:.2f}"})
        for field in ("start_date", "end_date"):
            if line[field] != p[field]:
                found.append({**base, "issue": f"{field}_mismatch", "proof": line[field], "plan": p[field]})
    signed = {line["product_id"] for line in proof.get("lines", [])}
    found += [{"line": None, "product_id": pid, "product_name": p["product_name"], "issue": "missing_sign", "proof": "no sign",
               "plan": f"${p['promo_price_usd']:.2f}"} for pid, p in planned.items() if pid not in signed]
    return found


def compare_promo_proof(tool_context: ToolContext) -> dict:
    """Compare the extracted proof (state key `proof`) with this week's promotion plan; returns every discrepancy."""
    proof = tool_context.state.get("proof")
    if not isinstance(proof, dict):
        return {"status": "ERROR", "error_details": "no extracted proof in state: the extractor has not produced one"}
    found = compare(proof, json.loads(PLAN.read_text()))
    return {"status": "SUCCESS", "discrepancy_count": len(found), "checked_lines": len(proof.get("lines", [])), "rows": found}


NO_PROOF = ("No promotion proof is attached. Upload the proof PDF in this chat (the developer UI's attachment button, or "
            "the artifact the caller saved) and ask again; there is nothing to extract from text alone.")


async def require_a_proof(callback_context: CallbackContext) -> types.Content | None:
    """Skip the whole tree when the session holds no artifact.

    Without this, the extractor calls load_artifacts, gets nothing, and calls it again for as long as the runner lets
    it (every two seconds for ten minutes in a live run), which on Agent Runtime ended in a failed request."""
    if await callback_context.list_artifacts():
        return None
    return types.Content(role="model", parts=[types.Part(text=NO_PROOF)])


async def attach_proof(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Add the latest uploaded file to the extractor's request, on every round of the loop.

    The built-in `load_artifacts` tool attaches a file only to the model call straight after the tool runs, and asks
    the model to call it again before every answer; with a schema-bound extractor that became a loop of over a
    hundred calls in a live run. Loading the artifact in code gives each round the same bytes with no tool call."""
    names = await callback_context.list_artifacts()
    proof = await callback_context.load_artifact(names[-1])
    llm_request.contents.append(types.Content(role="user", parts=[proof]))


def make_root_agent() -> SequentialAgent:
    cfg = load_env_config()
    extractor = LlmAgent(name="extractor", model=workshop_model(cfg), instruction=EXTRACT,
                         before_model_callback=attach_proof, output_schema=PromoProof, output_key="proof")
    critic = LlmAgent(name="critic", model=workshop_model(cfg), instruction=REVIEW, tools=[exit_loop])
    checker = LlmAgent(name="checker", model=workshop_model(cfg), instruction=CHECK, tools=[compare_promo_proof],
                       include_contents="none")
    return SequentialAgent(
        name="document_extraction_agent",
        description="Extracts a promotion signage proof into structured lines and reports where it differs from the plan.",
        sub_agents=[LoopAgent(name="extract_and_review", sub_agents=[extractor, critic], max_iterations=2), checker],
        before_agent_callback=require_a_proof)


def create_app() -> App:
    return App(name="document_extraction_agent", root_agent=make_root_agent(), plugins=[SaveFilesAsArtifactsPlugin()])


app = create_app()
root_agent = app.root_agent
