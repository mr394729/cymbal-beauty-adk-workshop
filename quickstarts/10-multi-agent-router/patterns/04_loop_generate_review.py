"""Pattern 4: LoopAgent. huddle_writer drafts the manager's shift-huddle note; huddle_critic checks a rubric and
calls exit_loop when it holds, otherwise lists the violations for the next pass (at most three passes).

The writer does not see the rubric, so the critic is the only thing enforcing it: the same split as a guardrail
check or an eval metric, kept outside the prompt that produces the text.

ADK docs:
  Iterative refinement: https://adk.dev/workflows/patterns/#iterative-refinement
Workshop pages: docs/patterns/05-iterative-refinement.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _run import MANAGER_STATE, run  # noqa: E402
from google.adk.agents import LlmAgent, LoopAgent  # noqa: E402
from google.adk.tools import exit_loop  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402
from agents.cymbal_store_ops.tools.domain_tools import (  # noqa: E402
    get_shift_roster,
    get_traffic_and_backlog,
)

cfg = load_env_config()
writer = LlmAgent(
    name="huddle_writer", model=workshop_model(cfg), tools=[get_traffic_and_backlog, get_shift_roster], output_key="huddle_draft",
    instruction="Write the note {user:first_name?} reads to the team at the 09:00 shift huddle: the pending BOPIS orders, "
                "the traffic peak and who covers BOPIS picking. On the first pass call get_traffic_and_backlog for 4 hours "
                "and get_shift_roster with focus bopis. If a review is in the conversation, rewrite the note fixing exactly "
                "what the latest review names. Reply with the note only.")
critic = LlmAgent(
    name="huddle_critic", model=workshop_model(cfg), tools=[exit_loop], output_key="huddle_review",
    instruction="Review this shift-huddle note:\n{huddle_draft}\n\nRubric: (1) it names at least one count from the tools; "
                "(2) every associate id in it (A-####) appears in a tool result earlier in the conversation; (3) it is under "
                "60 words; (4) no HR or disciplinary language (write-up, warning, discipline, performance review). "
                "If all four hold, call exit_loop. Otherwise do not call it; reply with one line per failed criterion: "
                "the number, what is wrong and the fix (for example '3. 84 words: cut to under 60').")
huddle = LoopAgent(name="huddle_note", sub_agents=[writer, critic], max_iterations=3)

if __name__ == "__main__":
    print("== 04 loop generate / review")
    run(huddle, "Draft my 09:00 huddle note.", MANAGER_STATE, show=("huddle_draft",))
