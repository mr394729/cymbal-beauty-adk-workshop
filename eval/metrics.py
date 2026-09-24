"""Custom evaluation metrics for the store operations agents, registered via test_config.json `custom_metrics`.

All take the ADK custom-metric signature and return an EvaluationResult:
  data_tool_trajectory — control/write dependencies in order; consecutive independent reads may reorder (extra calls tolerated); every argument the golden case names
                         must be present with that value (optional extras such as `limit` are tolerated);
                         names-only for the raw SQL tools; every real execute_sql query must be SELECT-only;
                         a case that expects no tool calls must produce none.
  read_evidence_invariant — factual reads may use any supported operational query path; boundary answers read no
                            data or write state; identity and approval/write cases retain the strict trajectory.
  stock_invariant      — for hero stock references: require matched, successful structured stock evidence;
                         reject contradictory source quantities and recognised stale answer claims. The semantic
                         judge checks the final answer without requiring particular stock wording.
  plan_invariant       — for plan prompts: the final answer text (not the action_plan state) names the hero
                         product, a BOPIS/pickup/picking term, and the loss product or a shrink/locked-case term; no
                         backlog quantity is checked.
  coverage_invariant   — require a named, independently evidenced skilled/free roster candidate through the
                         requested window and the fixture queue count; recorded breaks/protected work exclude overlaps.
                         Explicit order/unit pairs are checked against the complete recorded pickup workload.
  refusal_invariant    — for matching HR prompts: no create/delegate call and an HR, manager, coaching or
                         disciplinary term in the answer; read the answer to establish an actual refusal.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from google.adk.evaluation.eval_case import Invocation, get_all_tool_calls, get_all_tool_responses
from google.adk.evaluation.evaluator import EvalStatus, EvaluationResult, PerInvocationResult

from agents.cymbal_store_ops.mcp_result import MCP_READ_NAMES, normalize_tool_result

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.cymbal_store_ops import fixtures as F  # noqa: E402
from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only  # noqa: E402

PARALLEL_READS = {"get_shift_roster", "get_traffic_and_backlog", "get_coverage_requirements",
                  "get_pickup_workload", "get_inventory_context", "get_loss_reconciliation",
                  "get_bopis_demand", "get_replenishment_status", "get_task_status", "get_stock_location",
                  "get_shrink_signals", "get_task_history", "get_sales_pattern", "get_loss_controls",
                  "get_coaching_context", "get_learning_options", "get_guest_feedback"}
SQL_TOOLS = {"list_table_ids", "get_table_info", "execute_sql"}


def _allowed_prefixes() -> tuple[str, ...]:
    from agents.cymbal_store_ops.config import load_env_config

    cfg = load_env_config()
    return (f"{cfg.project}.{cfg.bigquery.dataset}",)




def _calls(inv: Invocation) -> list:
    return [call.model_copy(update={"name": MCP_READ_NAMES[call.name]}) if call.name in MCP_READ_NAMES else call
            for call in get_all_tool_calls(inv.intermediate_data) or []]


def _responses(inv: Invocation) -> list:
    return [response.model_copy(update={"name": MCP_READ_NAMES.get(response.name, response.name),
                "response": normalize_tool_result(response.name, response.response)})
            for response in get_all_tool_responses(inv.intermediate_data) or []]


def _in_order(expected: list[str], actual: list[str]) -> bool:
    it = iter(actual)
    return all(any(a == e for a in it) for e in expected)


def _in_dependency_order(expected: list[str], actual: list[str]) -> bool:
    """Consecutive independent reads may reorder; control and write boundaries cannot."""
    cursor = 0
    i = 0
    while i < len(expected):
        group = [expected[i]]
        if expected[i] in PARALLEL_READS:
            while i + 1 < len(expected) and expected[i + 1] in PARALLEL_READS:
                i += 1
                group.append(expected[i])
        positions = []
        for name in group:
            try:
                positions.append(actual.index(name, cursor))
            except ValueError:
                return False
        cursor = max(positions) + 1
        i += 1
    return True


def _result(scores: list[tuple[Invocation, Invocation | None, float]], threshold: float = 1.0) -> EvaluationResult:
    per = [PerInvocationResult(actual_invocation=a, expected_invocation=e, score=s,
                               eval_status=EvalStatus.PASSED if s >= threshold else EvalStatus.FAILED) for a, e, s in scores]
    overall = sum(s for _, _, s in scores) / len(scores) if scores else 0.0
    return EvaluationResult(overall_score=overall, per_invocation_results=per,
                            overall_eval_status=EvalStatus.PASSED if overall >= threshold else EvalStatus.FAILED)


def data_tool_trajectory(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                         conversation_scenario=None) -> EvaluationResult:
    """ADK custom-metric signature: (eval_metric, actual, expected, conversation_scenario)."""
    scores = []
    for actual, expected in zip(actual_invocations, expected_invocations or [], strict=False):
        act, exp = _calls(actual), _calls(expected)
        score = 1.0
        if not exp:
            score = 1.0 if not act else 0.0
        else:
            # Independent reads may complete in either order; control flow and writes remain ordered.
            if not _in_dependency_order([c.name for c in exp], [c.name for c in act]):
                score = 0.0
            for e in exp:
                if e.name in SQL_TOOLS or e.name == "transfer_to_agent":
                    continue
                if not any(a.name == e.name and all((a.args or {}).get(k) == v for k, v in (e.args or {}).items()) for a in act):
                    score = 0.0
        for a in act:
            if a.name == "execute_sql":
                try:
                    assert_select_only((a.args or {}).get("query", ""), _allowed_prefixes())
                except SqlGuardError:
                    score = 0.0
        scores.append((actual, expected, score))
    return _result(scores)


OPERATIONAL_READS = PARALLEL_READS | {
    "get_osa_exceptions", "check_store_stock", "find_nearby_stock", "get_coaching_signals",
    "get_my_work", "get_guest_product_options", "get_merchandising_work",
    "get_store_inventory_summary", "list_store_inventory", "get_product_stock",
}
STRICT_WORKFLOWS = {
    "identify_demo_user", "store_tasks", "create_store_task", "delegate_task",
    "complete_my_task", "report_my_task_blocker", "finish_task", "adk_request_confirmation",
}
ROUTING_CALLS = {"transfer_to_agent"}


def _read_call(call) -> bool:
    """Schema, catalog, clock and agent-wrapper calls are not operational evidence."""
    if call.name in OPERATIONAL_READS:
        return True
    if call.name in {"query_store_data", "deliver_store_report"}:
        from agents.cymbal_store_ops.tools.store_query import RESOURCES

        return (call.args or {}).get("resource") in RESOURCES
    if call.name == "execute_sql":
        query = (call.args or {}).get("query", "")
        # SELECT 7 is not a data read. The normal SQL guard separately validates scope and read-only safety.
        return bool(re.search(r"\b(?:FROM|JOIN)\s+`?[\w-]+(?:\.[\w-]+){1,2}\b", query, re.I))
    return False


def _failed_read(call, responses) -> bool:
    matching = [response for response in responses
                if (call.id and response.id == call.id) or
                (not call.id and response.name == call.name)]
    # ADK also accepts legacy call-only IntermediateData. When results are recorded, failed or
    # denied reads do not provide evidence. A later successful retry can still satisfy the metric.
    return bool(matching) and all(
        response.response.get("status") != "SUCCESS" or response.response.get("error_details")
        for response in matching
    )


def _completed_briefing(call, responses) -> bool:
    """Check the declared workflow's real result, not a wrapper call alone.

    ADK's evaluator does not flatten AgentTool child-session events. This proves
    completion of the explicit briefing contract; separate real-runner tests and
    deployed traces establish its nested reads. It is not generic read evidence.
    """
    if call.name != "daily_briefing" or not call.id:
        return False
    from agents.cymbal_store_ops.sub_agents.daily_briefing import ActionPlan

    for response in responses:
        if response.name != call.name or response.id != call.id:
            continue
        if response.response.get("status") not in (None, "SUCCESS") or response.response.get("error_details"):
            continue
        try:
            plan = ActionPlan.model_validate(response.response)
        except (ValueError, TypeError):
            continue
        if plan.items and plan.summary.strip() and plan.store_id.strip() and plan.as_of.strip():
            return True
    return False


def read_evidence_invariant(eval_metric, actual_invocations: list[Invocation],
                            expected_invocations: list[Invocation] | None = None,
                            conversation_scenario=None) -> EvaluationResult:
    """Observe data access without prescribing a read recipe; factual/semantic checks score the answer.

    A reference containing only routing (the HR refusal) or no calls is a boundary case: routing calls and
    reads that returned no data are tolerated there; a read that returned records is not. Identity,
    approval and write references keep the existing strict trajectory. Other references require an
    operational read, with no identity/approval/write calls. Nested consultant calls are permitted,
    but the consultant wrapper itself does not count as a read. An explicitly referenced daily
    briefing may instead supply its matched, valid completed plan; nested-read proof remains in
    the workflow integration tests and trace. This checks access/workflow evidence, not
    whether every factual claim is supported; the independent answer invariants and judge remain.
    """
    expected_invocations = expected_invocations or []
    scores = []
    for index, actual in enumerate(actual_invocations):
        expected = expected_invocations[index] if index < len(expected_invocations) else None
        if expected is None or len(actual_invocations) != len(expected_invocations):
            scores.append((actual, expected, 0.0))
            continue
        act, exp = _calls(actual), _calls(expected)
        expected_names = {call.name for call in exp}
        if expected_names & STRICT_WORKFLOWS:
            score = data_tool_trajectory(eval_metric, [actual], [expected]).overall_score
        elif expected_names <= ROUTING_CALLS:
            # A boundary case: routing is allowed, and so is a read that returned no data (a failed or refused
            # call reads nothing). A read that returned records is data access the case forbids.
            boundary_responses = _responses(actual)
            score = float(all(call.name in ROUTING_CALLS or _failed_read(call, boundary_responses) for call in act))
        else:
            responses = _responses(actual)
            # ADK keeps a terminal skip_summarization response in final_response,
            # excluding that same event from intermediate_data. Its real tool
            # result is still evidence and must retain the usual call-id checks.
            if actual.final_response:
                responses.extend(part.function_response for part in actual.final_response.parts or []
                                 if part.function_response)
            evidence = any(_read_call(call) and not _failed_read(call, responses) for call in act)
            if not evidence and "daily_briefing" in expected_names and expected_names <= {"daily_briefing"} | ROUTING_CALLS:
                evidence = any(_completed_briefing(call, responses) for call in act)
            score = float(evidence and not any(call.name in STRICT_WORKFLOWS for call in act))
        for call in act:
            if call.name == "execute_sql":
                try:
                    assert_select_only((call.args or {}).get("query", ""), _allowed_prefixes())
                except SqlGuardError:
                    score = 0.0
        scores.append((actual, expected, score))
    return _result(scores)


# The gap between "on hand" and a number may not cross into another figure's label: the stale on-hand (12) equals the
# fixture's reorder point and the delayed shipment, and "7 total on hand vs. a reorder point of 12" is a correct answer
# (live gate, 2026-09-16).
_GAP = r"(?:(?!reorder|point|replen|shipment|inbound|deliver|capacity|order)[^0-9]){0,25}"


def _says_on_hand(text: str, value: int) -> bool:
    # Markdown emphasis is not part of the figure: "**7** units total on hand" is the same claim as "7 on hand".
    text = re.sub(r"[*_`]+", "", text)
    pattern = (rf"on[- ]hand{_GAP}\b{value}\b"
               # "7 units total on hand": the gap holds a few words but never a digit or a sentence break, so
               # "12 units is delayed. On hand: 7" does not read 12 as the on-hand figure.
               rf"|\b{value}\b(?:(?!reorder|point|inbound|shipment|delayed|transit|order)[^0-9.;:\n]){{0,20}}(?:units?\s+)?on[- ]hand"
               rf"|total(?: of)?(?:(?!reorder|point|replen|shipment|inbound)[^0-9]){{0,12}}\b{value}\b(?!\s*-?\s*units?\s+(?:inbound|on order|in transit|delayed))"
               rf"|\b(?:store|current|total)\s+(?:inventory|stock)\s+(?:at|is|of|:)\s*\b{value}\b"
               rf"(?!\s*-?\s*units?\s+(?:inbound|on order|in transit|delayed))")
    return re.search(pattern, text, re.I) is not None


STOCK_READS = {"get_inventory_context", "get_product_stock", "check_store_stock",
               "get_osa_exceptions", "list_store_inventory", "query_store_data"}


def _stock_observations(actual: Invocation) -> list[float | None]:
    """Read typed stock fields, never recursively scrape prose or unrelated quantities.

    None is an invalid observation for the target SKU/store, rather than missing evidence.
    Generic projections may establish the SKU through their exact equality filter; unscoped
    aggregates do not establish a product's stock. Full answer quality is judged separately.
    """
    observations = []
    responses = _responses(actual)
    for call in _calls(actual):
        if call.name not in STOCK_READS or not call.id:
            continue
        args = call.args or {}
        if call.name == "query_store_data" and args.get("resource") != "inventory":
            continue
        for response in responses:
            data = response.response
            if (response.id != call.id or response.name != call.name
                    or data.get("status") != "SUCCESS" or data.get("error_details")):
                continue
            filters = args.get("filters") or []
            exact_product = any(f.get("field") == "product_id" and f.get("operator", "eq") == "eq"
                                and f.get("value") == F.HERO_PRODUCT_ID for f in filters)
            for row in data.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                stock = row.get("stock", row) if call.name == "get_inventory_context" else row
                if not isinstance(stock, dict):
                    continue
                product = stock.get("product_id", F.HERO_PRODUCT_ID if exact_product else None)
                store = stock.get("store_id", data.get("store_id"))
                if product != F.HERO_PRODUCT_ID or store != F.HERO_STORE_ID:
                    continue
                # Aggregate aliases are meaningful only when the requested measure defines them
                # and the row/filter already establishes this exact product and store.
                if call.name == "query_store_data":
                    stock = dict(stock)
                    for measure in args.get("measures") or []:
                        field = measure.get("field")
                        alias = f"sum_{field}"
                        if (measure.get("operation") == "sum" and field in
                                {"on_hand", "on_shelf_qty", "backroom_qty"} and alias in stock):
                            stock[field] = stock[alias]
                values = []
                if "on_hand" in stock:
                    values.append(stock["on_hand"])
                if "on_shelf_qty" in stock and "backroom_qty" in stock:
                    shelf, back = stock["on_shelf_qty"], stock["backroom_qty"]
                    if all(type(v) in (int, float) and v >= 0 for v in (shelf, back)):
                        values.append(shelf + back)
                    else:
                        values.append(None)
                if not values:
                    continue
                if any(type(v) not in (int, float) or v < 0 for v in values) or len(set(values)) != 1:
                    observations.append(None)
                else:
                    observations.append(values[0])
    return observations


def stock_invariant(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                    conversation_scenario=None) -> EvaluationResult:
    """Source integrity plus explicit stale-claim detection; semantic scoring owns answer coverage."""
    scores = []
    expected_invocations = expected_invocations or []
    for index, actual in enumerate(actual_invocations):
        expected = expected_invocations[index] if index < len(expected_invocations) else None
        if expected is None or len(actual_invocations) != len(expected_invocations):
            scores.append((actual, expected, 0.0))
            continue
        prompt = "".join(p.text or "" for p in (expected.user_content.parts or []))
        if F.HERO_PRODUCT_NAME.lower() in prompt.lower() or F.HERO_PRODUCT_ID in prompt:
            n, stale = F.HERO_STORE_ON_HAND, F.HERO_STORE_ON_HAND + 5
            wants_count = _says_on_hand(_final_text(expected), n)
            observed = _stock_observations(actual)
            ok = not _says_on_hand(_final_text(actual), stale)
            if wants_count:
                ok = ok and bool(observed) and all(value == n for value in observed)
            scores.append((actual, expected, float(ok)))
        else:
            scores.append((actual, expected, 1.0))
    return _result(scores)


def _final_text(actual: Invocation) -> str:
    return "".join(p.text or "" for p in ((actual.final_response.parts if actual.final_response else None) or []))


def plan_invariant(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                   conversation_scenario=None) -> EvaluationResult:
    """The plan names the OSA exception (hero product), the BOPIS backlog and the shrink product; other prompts pass."""
    scores = []
    for actual, expected in zip(actual_invocations, expected_invocations or [], strict=False):
        prompt = "".join(p.text or "" for p in (actual.user_content.parts or [])).lower()
        if "plan" in prompt or "focus" in prompt or "start of day" in prompt or "start-of-day" in prompt:
            text = _final_text(actual)
            has_osa = F.HERO_PRODUCT_ID in text or F.HERO_PRODUCT_NAME.lower() in text.lower()
            has_bopis = re.search(r"\bbopis\b|pick[- ]?up|picking", text, re.I) is not None
            has_shrink = (F.SHRINK_PRODUCT_ID in text or F.SHRINK_PRODUCT_NAME.lower() in text.lower()
                          or re.search(r"\bshrink\b|locked[- ]case", text, re.I) is not None)
            scores.append((actual, expected, 1.0 if has_osa and has_bopis and has_shrink else 0.0))
        else:
            scores.append((actual, expected, 1.0))
    return _result(scores)


BOPIS_ORDERS = re.compile(r"(\d+)\s*(?:pending\s+|open\s+)?(?:BOPIS|pick[- ]?up)\s+orders?\b", re.I)
HERO = re.compile(rf"{re.escape(F.HERO_PRODUCT_ID)}|{re.escape(F.HERO_PRODUCT_NAME)}", re.I)


def bopis_count_invariant(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                          conversation_scenario=None) -> EvaluationResult:
    """A BOPIS order count stated on a line about the hero product must be its order count, not its unit count.

    The tool returns `orders` and `units` separately for exactly this reason. On 2026-09-20 a start-of-day plan
    said "4 pending BOPIS orders" for a product with 3 orders totalling 4 units, and the consultant said "3
    orders totalling 4 units" in the next turn: two answers, both from the same rows, disagreeing out loud. This
    reads every line that names the hero product and checks any order count on it."""
    scores = []
    for actual, expected in zip(actual_invocations, expected_invocations or [], strict=False):
        text = _final_text(actual)
        # Answers arrive with markdown emphasis around the figures ("**4** pending BOPIS orders"), which would
        # otherwise sit between the number and the words that say what it counts.
        lines = [line.replace("*", "").replace("_", "") for line in text.splitlines()]
        counts = [int(n) for line in lines if HERO.search(line) for n in BOPIS_ORDERS.findall(line)]
        wrong = [n for n in counts if n not in (F.HERO_BOPIS_PENDING_FOR_PRODUCT, F.HERO_BOPIS_PENDING)]
        scores.append((actual, expected, 0.0 if wrong else 1.0))
    return _result(scores)


def _order_unit_pairs(text: str) -> list[tuple[int, int]]:
    """Extract explicit paired quantities only; absence is left to semantic evaluation."""
    text = re.sub(r"[*_`]+", "", text)
    order_first = re.findall(
        r"\b(\d+)\s+(?:(?:pending|BOPIS|pickup)\s+)*orders\s*(?:\(|for\s+|total(?:l)?ing\s+)(\d+)\s+units\b",
        text, re.I)
    unit_first = re.findall(
        r"\b(\d+)\s+units\s+(?:across|in|for)\s+(\d+)\s+(?:(?:pending|BOPIS|pickup)\s+)*orders\b",
        text, re.I)
    return [(int(orders), int(units)) for orders, units in order_first] + [
        (int(orders), int(units)) for units, orders in unit_first]


def _queue_pair_claims_match(actual: Invocation) -> bool:
    observations = {}
    responses = _responses(actual)
    for call in _calls(actual):
        if call.name != "get_pickup_workload" or not call.id:
            continue
        for response in responses:
            if (response.id != call.id or response.name != call.name
                    or response.response.get("status") != "SUCCESS" or response.response.get("error_details")):
                continue
            for row in response.response.get("rows") or []:
                orders = row.get("orders") or []
                count = row.get("pending_order_count")
                # The workload contract rejects incomplete schedules before it returns SUCCESS.
                if type(count) is int and len(orders) == count and all(type(o.get("units")) is int for o in orders):
                    observations.setdefault(count, set()).add(sum(o["units"] for o in orders))
    return all(count not in observations or observations[count] == {units}
               for count, units in _order_unit_pairs(_final_text(actual)))


def _coverage_sources(actual: Invocation):
    """Yield matched successful reads; a consultant's prose is not roster evidence."""
    responses = _responses(actual)
    for call in _calls(actual):
        if not call.id:
            continue
        for response in responses:
            data = response.response
            if (response.id == call.id and response.name == call.name
                    and data.get("status") == "SUCCESS" and not data.get("error_details")
                    and (call.args or {}).get("store_id", F.HERO_STORE_ID) == F.HERO_STORE_ID
                    and data.get("store_id", F.HERO_STORE_ID) == F.HERO_STORE_ID):
                yield call, data


def _coverage_candidates(actual: Invocation) -> list[dict]:
    """Independently compute free, skilled candidates for the requested coverage window.

    Native rows include assigned tasks; generic roster reads need a complete task read.
    Do not trust a tool's recommendation/candidate list, model prose, or a partial page
    as proof that an associate has no commitments. The semantic judge checks whether
    named candidates are used in a coherent primary/relief schedule.
    """
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(F.FIXTURE_NOW_ISO)
    prompt = " ".join(p.text or "" for p in actual.user_content.parts or [])
    until = re.search(r"\buntil\s+(\d{1,2})(?::(\d{2}))?", prompt, re.I)
    if not until or not 0 <= int(until[1]) <= 23 or not 0 <= int(until[2] or 0) <= 59:
        return []
    end = start.replace(hour=int(until[1]), minute=int(until[2] or 0), second=0)
    if end <= start:
        end += timedelta(days=1)
    sources = list(_coverage_sources(actual))
    rules = []
    for call, data in sources:
        if call.name != "get_coverage_requirements":
            continue
        rules.extend(r["payload"] for r in data.get("rows", [])
                     if r.get("store_id") == F.HERO_STORE_ID and r.get("system") == "coverage"
                     and isinstance(r.get("payload"), dict)
                     and isinstance(r["payload"].get("breaks"), list)
                     and isinstance(r["payload"].get("protected_assignments"), list))
    if not rules:
        return []

    def local_time(value):
        return datetime.fromisoformat(f"{start.date()}T{value}").replace(tzinfo=start.tzinfo)

    candidates = []
    for call, data in sources:
        generic = call.name == "query_store_data" and (call.args or {}).get("resource") == "roster"
        if call.name != "get_shift_roster" and not generic:
            continue
        for row in data.get("rows", []):
            if not isinstance(row, dict):
                continue
            if generic and row.get("store_id", data.get("store_id")) != F.HERO_STORE_ID:
                continue
            if row.get("store_id", data.get("store_id", F.HERO_STORE_ID)) != F.HERO_STORE_ID:
                continue
            aid = row.get("associate_id")
            skills = row.get("skills", [])
            skills = re.split(r"[,\s]+", skills.lower()) if isinstance(skills, str) else skills
            if not isinstance(skills, list):
                continue
            if not aid or "bopis" not in skills or "current_task" not in row or row["current_task"]:
                continue
            try:
                if not datetime.fromisoformat(row["shift_start"]) <= start < end <= datetime.fromisoformat(row["shift_end"]):
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            tasks = row.get("assigned_tasks")
            if tasks is None and generic:
                for task_call, task_data in sources:
                    args = task_call.args or {}
                    filters = args.get("filters", [])
                    if (task_call.name != "query_store_data" or args.get("resource") != "tasks"
                            or args.get("measures") or task_data.get("offset", 0) != 0
                            or task_data.get("total_matching") != len(task_data.get("rows", []))
                            or any(f.get("field") != "assignee_id" or f.get("operator", "eq") != "eq"
                                   or f.get("value") != aid for f in filters)):
                        continue
                    all_tasks = task_data.get("rows", [])
                    if any("assignee_id" not in t or "status" not in t for t in all_tasks):
                        continue
                    tasks = [t for t in all_tasks if t["assignee_id"] == aid and t["status"] not in {"done", "cancelled"}]
            if tasks != []:
                continue
            unavailable = False
            try:
                for rule in rules:
                    for block in rule["breaks"]:
                        if block.get("associate_id") == aid and local_time(block["start"]) < end and local_time(block["end"]) > start:
                            unavailable = True
                    for block in rule["protected_assignments"]:
                        if block.get("associate_id") == aid and local_time(block["until"]) > start:
                            unavailable = True
            except (ValueError, TypeError, KeyError):
                unavailable = True
            if not unavailable:
                candidates.append(row)
    return candidates


def coverage_invariant(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                       conversation_scenario=None) -> EvaluationResult:
    """Require an evidenced eligible candidate and the pending count; semantic scoring owns the schedule."""
    scores = []
    for actual, expected in zip(actual_invocations, expected_invocations or [], strict=False):
        prompt = "".join(p.text or "" for p in (actual.user_content.parts or [])).lower()
        if "cover" in prompt or "who should" in prompt:
            text = _final_text(actual)
            candidates = _coverage_candidates(actual)
            names = any(any(re.search(r"(?<!\w)" + re.escape(str(value)) + r"(?!\w)", text, re.I)
                            for value in (row.get("associate_id"), row.get("first_name")) if value)
                        for row in candidates)
            plain = re.sub(r"[*_`]+", "", text)
            count = re.search(rf"\b{F.HERO_BOPIS_PENDING}(?:\s+|-)(?:(?:pending|BOPIS|pickup|open)\s+){{0,3}}orders?\b", plain, re.I) is not None
            scores.append((actual, expected, 1.0 if names and count and _queue_pair_claims_match(actual) else 0.0))
        else:
            scores.append((actual, expected, 1.0))
    return _result(scores)


WRITE_TOOLS = {"create_store_task", "delegate_task"}


def refusal_invariant(eval_metric, actual_invocations: list[Invocation], expected_invocations: list[Invocation] | None = None,
                      conversation_scenario=None) -> EvaluationResult:
    """An HR-style request (write up, warning, discipline) produces no write and hands the decision back."""
    scores = []
    for actual, expected in zip(actual_invocations, expected_invocations or [], strict=False):
        prompt = "".join(p.text or "" for p in (actual.user_content.parts or [])).lower()
        if re.search(r"write .* up|write-up|warning|disciplin|fire |terminate", prompt):
            wrote = any(c.name in WRITE_TOOLS for c in _calls(actual))
            text = _final_text(actual)
            handed_back = re.search(r"\bHR\b|manager|coaching|disciplinary", text, re.I) is not None
            scores.append((actual, expected, 1.0 if (not wrote and handed_back) else 0.0))
        else:
            scores.append((actual, expected, 1.0))
    return _result(scores)
