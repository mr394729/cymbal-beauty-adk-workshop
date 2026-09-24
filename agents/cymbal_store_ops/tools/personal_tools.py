"""Identity-scoped personal work and dated coaching context."""
from __future__ import annotations

from datetime import date

from google.adk.tools import ToolContext

from agents.cymbal_store_ops.tools import domain_tools as domain
from agents.cymbal_store_ops.tools.data_backend import err, ok


def resolve_coaching_person(associate_id, tool_context):
    state = domain._state(tool_context)
    uid, sid, role = (state.get(k) for k in ("user:user_id", "user:store_id", "user:role"))
    if not uid or not sid:
        return None, err("Sign in to view development information.")
    if role == "associate":
        result = domain.make_backend().get_associate(uid)
        if result.get("status") != "SUCCESS":
            return None, result
        person = result["rows"][0]
        if person["store_id"] != sid or (associate_id and associate_id.casefold() not in {uid.casefold(), person["first_name"].casefold()}):
            return None, err("You can view your own development information.", code="forbidden")
        return person, None
    if role in {"store_manager", "district_manager"}:
        if not associate_id:
            return None, err("Which associate would you like to support?")
        return domain._resolve_associate(sid, associate_id)
    return None, err("This role cannot view development information.", code="forbidden")


def get_my_work(tool_context: ToolContext) -> dict:
    """The signed-in associate's shift and current assigned tasks. Identity comes only from the session."""
    person, error = resolve_coaching_person("", tool_context)
    if error:
        return error
    result = domain.make_backend().get_assigned_tasks(store_id=person["store_id"], associate_id=person["associate_id"])
    if result.get("status") == "SUCCESS":
        result.update(associate=person, scope="self")
    return result


def get_coaching_context(associate_id: str = "", tool_context: ToolContext | None = None) -> dict:
    """Dated picking activity and defined measurements; associates can read only themselves.

    Use observed delays to identify process support. Categories may overlap and do not establish causation.
    A legacy weekly index has no documented unit; never interpret it as a speed or percentage.
    """
    person, error = resolve_coaching_person(associate_id, tool_context)
    if error:
        return error
    backend = domain.make_backend()
    result = backend.get_coaching_signals(associate_id=person["associate_id"], period=None)
    if result.get("status") != "SUCCESS":
        return result
    activity = backend.get_operations_context(store_id=person["store_id"], system="picking_activity", subject_id=person["associate_id"])
    if activity.get("status") != "SUCCESS":
        return activity
    for row in result.get("rows", []):
        year, week = row["period"].split("-W")
        start, end = date.fromisocalendar(int(year), int(week), 1), date.fromisocalendar(int(year), int(week), 7)
        row["period_label"] = f"{start.strftime('%B %d')}–{end.strftime('%B %d, %Y')}"
        if row["metric"] == "bopis_pick_rate":
            row["interpretation"] = "Legacy index with unspecified unit; use dated picking activity."
    result["shift_activity"] = activity["rows"]
    return result


def complete_my_task(task_id: str, completion_note: str, tool_context: ToolContext | None = None) -> dict:
    """Mark an open task assigned to the signed-in associate done, after confirmation.

    The associate must provide what they completed. This records task completion, not an inventory movement
    or pickup readiness. It never completes another person's task or changes stock/order records.
    """
    person, error = resolve_coaching_person("", tool_context)
    if error:
        return error
    if not completion_note.strip():
        return err("Describe the completed work.")
    tasks = domain.make_backend().get_assigned_tasks(store_id=person["store_id"], associate_id=person["associate_id"])
    if tasks.get("status") != "SUCCESS":
        return tasks
    task = next((t for t in tasks["rows"] if t["task_id"] == task_id), None)
    if task is None:
        return err("That task is not assigned to you.", code="forbidden")
    if task["status"] == "done":
        return ok([task], already_completed=True)
    if task["status"] != "open":
        return err("Only an open task can be completed.", code="conflict")
    if exhausted := domain._write_budget_exhausted(tool_context):
        return exhausted
    pending = domain._needs_confirmation(tool_context, f"Mark {task_id} complete: {completion_note}",
                                         {"task_id": task_id, "completion_note": completion_note})
    if pending:
        return pending
    domain._count_write(tool_context)
    return domain.make_backend().complete_assigned_task(store_id=person["store_id"], associate_id=person["associate_id"],
                                                        task_id=task_id, completion_note=completion_note)


def report_my_task_blocker(task_id: str, blocker: str, tool_context: ToolContext | None = None) -> dict:
    """Record a blocker on the signed-in associate's own open task after confirmation.

    Keeps the task open and records the issue for the manager's worklist. Does not change inventory,
    reassign work or notify a person. Retrying the same report does not append it twice.
    """
    person, error = resolve_coaching_person("", tool_context)
    if error:
        return error
    if not blocker.strip():
        return err("Describe what is preventing completion.")
    tasks = domain.make_backend().get_assigned_tasks(store_id=person["store_id"], associate_id=person["associate_id"])
    if tasks.get("status") != "SUCCESS":
        return tasks
    task = next((t for t in tasks["rows"] if t["task_id"] == task_id), None)
    if not task:
        return err("That task is not assigned to you.", code="forbidden")
    if task["status"] != "open":
        return err("Only an open task can receive a blocker report.", code="conflict")
    if exhausted := domain._write_budget_exhausted(tool_context):
        return exhausted
    blocker = blocker.strip()
    pending = domain._needs_confirmation(tool_context, f"Report an issue on {task_id}: {blocker}",
                                         {"task_id": task_id, "blocker": blocker})
    if pending:
        return pending
    domain._count_write(tool_context)
    return domain.make_backend().report_assigned_task_blocker(store_id=person["store_id"],
        associate_id=person["associate_id"], task_id=task_id, blocker=blocker)
