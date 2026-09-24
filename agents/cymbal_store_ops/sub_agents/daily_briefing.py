"""The start-of-day plan: three signal branches in parallel, then one writer that turns them into an ActionPlan.

Exposed to the root as an AgentTool (workflow agents carry no operating mode). The tool runs the sequence in its
own session seeded with the caller's state, and the writer's `action_plan` is merged back into the manager's
session when the tool returns.

ADK docs:
  Parallel fan-out and gather: https://adk.dev/workflows/patterns/#parallel-fan-out-and-gather
  Hierarchical task decomposition: https://adk.dev/workflows/patterns/#hierarchical-task-decomposition
Workshop pages: docs/patterns/04-parallel-fan-out.md, docs/patterns/06-hierarchical-task-decomposition.md
"""
from __future__ import annotations

import json

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.events import Event, EventActions
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from agents.cymbal_store_ops.chat_reply import ChatReply, NextAction
from agents.cymbal_store_ops.config import load_env_config
from agents.cymbal_store_ops.models import thinking
from agents.cymbal_store_ops.prompts import load_prompt
from agents.cymbal_store_ops.sub_agents.briefing_facts import writer_facts
from agents.cymbal_store_ops.sub_agents.briefing_signals import BriefingSignals
from agents.cymbal_store_ops.tools import data_backend
from agents.cymbal_store_ops.tools.report_delivery import _sole_current_call
from agents.cymbal_store_ops.trace import record_model_input

TASK_TYPES = "backroom_check|replenish|cycle_count|coverage_move|investigation|coaching|planogram_fix|signage_fix"


def writer_instruction(context):
    sections = [load_prompt("plan_writer"),
                "Tables use columns followed by records in that column order; common fields apply to every record. "
                "Every source record is retained."]
    for area in ("inventory", "coverage", "shrink"):
        facts = json.loads(context.state[f"temp:briefing_{area}"])
        sections.append(f"{area.title()} signals:\n" + json.dumps(
            writer_facts(area, facts), ensure_ascii=False, separators=(",", ":")))
    sections.append(f"Store: {context.state['user:store_id']}")
    return "\n\n".join(sections)


def briefing_request_only(callback_context, llm_request):
    """Supply source facts once, through the instruction, while retaining the caller's request.

    ADK's current-turn history also contains the branch tool results. Repeating those
    here duplicates the state-injected reports. The writer has no tools of its own;
    its input is the caller's request plus those reports. Session events and their
    full tool results remain intact for tracing and evaluation.
    """
    request = callback_context.get_invocation_context().user_content
    if request is None:
        raise ValueError("The briefing writer requires the current briefing request.")
    llm_request.contents = [request.model_copy(deep=True)]
    record_model_input(callback_context, llm_request)


class SuggestedTask(BaseModel):
    task_type: str = Field(description=TASK_TYPES)
    product_id: str | None = None
    assignee_id: str | None = Field(default=None, description="Associate id when a specific person was recommended")
    note: str = Field(max_length=240, description="One actionable line, retaining the relevant deadline")


class PlanItem(BaseModel):
    priority: int = Field(ge=1, description="1 = do first")
    area: str = Field(description="inventory|coverage|shrink|guest|labor")
    headline: str = Field(max_length=100, description="Short action label; put quantities, deadlines and conditions in evidence rather than this label")
    evidence: list[str] = Field(max_length=2, description="One or two short lines: why this matters and the facts or constraints needed to act; do not repeat the headline or task note")
    suggested_task: SuggestedTask | None = None


class ActionPlan(BaseModel):
    store_id: str
    as_of: str = Field(description="ISO timestamp the plan was built for")
    items: list[PlanItem] = Field(max_length=3, description="At most three decisions needing the manager's attention now")
    summary: str = Field(max_length=220, description="One sentence identifying the first decision and its urgency")


class BriefingReply(ActionPlan):
    next_actions: list[NextAction] = Field(min_length=3, max_length=5,
        description="Useful follow-up requests grounded in this plan and the caller's constraints: at least one question "
                    "that reads the evidence behind a decision, the rest proposed work. "
                    "Do not repeat completed work or invent observations. A proposed write still needs approval.")


class BriefingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str = Field(description="inventory|coverage|shrink|guest|labor")
    headline: str = Field(max_length=100, description="Short action label; quantities and constraints belong in evidence")
    evidence: list[str] = Field(min_length=1, max_length=2, description=
        "Facts needed to decide, retaining product/person names alongside locations. Identify existing task owner and deadline; "
        "keep calculated quantities and proposed timing in a separate, explicitly recommended sentence.")


class BriefingDraft(BaseModel):
    """Only decisions and follow-ups need model synthesis; metadata comes from code."""
    model_config = ConfigDict(extra="forbid")
    items: list[BriefingDecision] = Field(min_length=1, max_length=3, description="Decisions in priority order")
    next_actions: list[NextAction] = Field(min_length=3, max_length=5,
        description="Useful source-grounded follow-up requests: at least one question that reads the evidence behind "
                    "a decision, the rest proposed work; proposed work still requires approval")


class BriefingFinalize(BaseAgent):
    """Attach trusted metadata after schema validation, with no additional model call."""
    async def _run_async_impl(self, ctx):
        value = ctx.session.state["temp:briefing_draft"]
        draft = (BriefingDraft.model_validate_json(value) if isinstance(value, str)
                 else BriefingDraft.model_validate(value))
        # All workshop source reads share this configured observation clock.
        # Wall-clock generation time would misrepresent the source snapshot.
        plan = BriefingReply(store_id=ctx.session.state["user:store_id"],
            as_of=data_backend.NOW.isoformat(), summary=draft.items[0].headline,
            items=[PlanItem(priority=index, **item.model_dump())
                   for index, item in enumerate(draft.items, 1)], next_actions=draft.next_actions)
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text=plan.model_dump_json())]),
            actions=EventActions(state_delta={"action_plan": plan.model_dump()}))


def render_briefing(plan: BriefingReply) -> ChatReply:
    """Format the writer's own wording once; do not make or reinterpret decisions."""
    paragraphs = []
    for index, item in enumerate(plan.items, 1):
        paragraphs.append(f"{index}. **{item.headline}** — " + " ".join(item.evidence))
    return ChatReply(answer="\n\n".join(paragraphs), next_actions=plan.next_actions)


class BriefingTool(AgentTool):
    async def run_async(self, *, args, tool_context):
        result = await super().run_async(args=args, tool_context=tool_context)
        # Validate this invocation's returned content, never an earlier plan in state.
        plan = (BriefingReply.model_validate_json(result) if isinstance(result, str)
                else BriefingReply.model_validate(result))
        result = {**plan.model_dump(), "status": "SUCCESS", "reply_completed": False}
        inv = tool_context.get_invocation_context()
        if inv.agent.name == "store_manager_agent" and _sole_current_call(tool_context, self.name):
            result["reply_completed"] = True
            result["final_reply"] = {**render_briefing(plan).model_dump(),
                                     "invocation_id": inv.invocation_id,
                                     "call_id": tool_context.function_call_id}
            tool_context.actions.skip_summarization = True
        return result


def make_daily_briefing(model) -> SequentialAgent:
    """Factory: fresh instances every call (an agent has exactly one parent).

    `model` is passed explicitly: the workflow sits behind an AgentTool, so it has no parent to inherit the
    root's pinned-`global` Gemini client from. Without it the branches would fall back to a default model in the
    runtime's regional location, which is the 404 the setup guide warns about."""
    signals = ParallelAgent(
        name="signals",
        description="Inventory, coverage and shrink signals gathered in parallel.",
        sub_agents=[
            BriefingSignals(name="briefing_inventory", area="inventory", output_key="temp:briefing_inventory"),
            BriefingSignals(name="briefing_coverage", area="coverage", output_key="temp:briefing_coverage"),
            BriefingSignals(name="briefing_shrink", area="shrink", output_key="temp:briefing_shrink"),
        ],
    )
    plan_writer = LlmAgent(
        name="plan_writer",
        model=model,
        description="Turns the three signal reports into a prioritized ActionPlan.",
        instruction=writer_instruction,
        output_schema=BriefingDraft,
        output_key="temp:briefing_draft",
        before_model_callback=briefing_request_only,
        # plan_writer_thinking_level in config/envs/<env>.yaml (or PLAN_WRITER_THINKING_LEVEL) sets the writer's level
        # alone; unset, the writer deliberates at the environment's thinking_level like every other agent.
        # eval/benchmark_writer.py compares the settings.
        generate_content_config=thinking(level=load_env_config().plan_writer_thinking_level),
    )
    return SequentialAgent(
        name="daily_briefing",
        description="Produces a store-wide opening plan across inventory, team coverage and loss prevention. "
                    "Reads all three domains and runs model synthesis to return three prioritized decisions "
                    "with evidence, optional task proposals and follow-up suggestions. A sole successful call "
                    "displays the finished briefing directly. Include the caller's relevant constraints in the request; "
                    "mixed tool calls retain coordinator synthesis.",
        sub_agents=[signals, plan_writer, BriefingFinalize(name="briefing_finalize")],
    )


def make_daily_briefing_tool(model) -> AgentTool:
    return BriefingTool(make_daily_briefing(model))
