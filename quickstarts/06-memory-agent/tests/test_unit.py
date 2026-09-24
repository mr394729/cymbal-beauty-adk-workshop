"""The manager's preferences land in user-scoped state; memory and huddle tools are wired."""
from __future__ import annotations


class FakeToolContext:
    def __init__(self) -> None:
        self.state: dict = {}


def test_remember_preferences_writes_user_state(quickstart):
    ctx = FakeToolContext()
    result = quickstart.remember_preferences(ctx, huddle_time="08:45", focus_areas=["bopis", "shrink", "bopis"])
    assert result["status"] == "SUCCESS"
    assert ctx.state == {"user:huddle_time": "08:45", "user:focus_areas": "bopis, shrink"}
    quickstart.remember_preferences(ctx, focus_areas=["on_shelf"])      # a partial update keeps the huddle time
    assert ctx.state == {"user:huddle_time": "08:45", "user:focus_areas": "on_shelf"}


def test_remember_preferences_validates(quickstart):
    ctx = FakeToolContext()
    assert quickstart.remember_preferences(ctx)["status"] == "ERROR"
    assert quickstart.remember_preferences(ctx, huddle_time="8.45am")["status"] == "ERROR"
    assert quickstart.remember_preferences(ctx, focus_areas=["payroll"])["status"] == "ERROR"
    assert ctx.state == {}


def test_memory_and_huddle_tools_present(quickstart):
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in quickstart.root_agent.tools]
    assert names == ["preload_memory", "load_memory", "identify_demo_user", "remember_preferences",
                     "get_traffic_and_backlog", "get_osa_exceptions", "get_shrink_signals"]
    assert quickstart.root_agent.after_agent_callback is quickstart.save_session_to_memory
