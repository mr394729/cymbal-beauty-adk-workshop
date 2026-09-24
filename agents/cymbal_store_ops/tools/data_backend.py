"""Backend-neutral data contract for the store-operations agents.

The agent never learns how the data is fetched: the backend returns fixed envelopes, row shapes
and error codes. BigQuery is the workshop backend; `FakeBackend` serves the unit tests. A backend that
fails its healthcheck stops the process at startup — there is no fallback.

Every read takes `store_id` explicitly (the domain-tool layer supplies it from session state) and every
time window is anchored at the workshop's frozen clock (`fixtures.FIXTURE_NOW_ISO`), so BigQuery and the
fake answer identically. The only writes are the two `store_tasks` operations, both idempotent on a key.

Envelopes (mirroring ADK's BigQuery toolset):
    {"status": "SUCCESS", "rows": [...], "result_is_likely_truncated": true?}
    {"status": "ERROR", "error_details": "human-readable reason", "code": "conflict"|"not_found"?}
"""
from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Protocol, runtime_checkable

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.config import EnvConfig, load_env_config

Row = dict[str, Any]

NOW = datetime.fromisoformat(F.FIXTURE_NOW_ISO)
LOCAL_TZ = NOW.tzinfo
TODAY_LOCAL = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


# Timestamp fields in rows and envelopes. The tables store UTC; the model and the manager read store-local time, so
# every envelope carries them as ISO-8601 with the store's offset (2026-10-03T09:00-05:00), never a mix of zones.
TIMESTAMP_KEYS = frozenset({
    "shift_start", "shift_end", "promised_at", "submitted_at", "expected_at", "created_at", "due_at", "updated_at",
    "event_ts", "first_event_ts", "last_event_ts", "ts_hour", "window_start", "window_end", "now",
})


def local_time(value: Any) -> Any:
    """A timestamp as store-local ISO-8601 to the minute; anything unparseable is returned unchanged."""
    if value is None or value == "":
        return value
    try:
        return parse_ts(value).astimezone(LOCAL_TZ).isoformat(timespec="minutes")
    except (TypeError, ValueError):
        return value


def _localize(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _localize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_localize(v) for v in value]
    return local_time(value) if key in TIMESTAMP_KEYS else value


def fold(text: str) -> str:
    """Lower-case and accent-free, for matching what a person typed against a name: a manager on a handheld types
    "Lumiere", the catalog says "Lumière", and the lookup must still find it (persona journeys, pass 5)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", text or "") if not unicodedata.combining(ch)).lower()


def ok(rows: list[Row], *, limit: int | None = None, **extra: Any) -> dict:
    env: dict = {"status": "SUCCESS", "rows": _localize(rows)}
    if limit is not None and len(rows) >= limit:
        env["result_is_likely_truncated"] = True
    env.update(_localize(extra))
    return env


def err(reason: str, **extra: Any) -> dict:
    return {"status": "ERROR", "error_details": reason, **extra}


def parse_ts(value: Any) -> datetime:
    """Timestamps come back as `2026-10-03 14:00:00 UTC` from the generator and as ISO-8601 from BigQuery."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith(" UTC"):
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def bq_ts(value: datetime) -> str:
    """A timestamp literal every backend accepts as a STRING parameter (`TIMESTAMP(@x)` in SQL)."""
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S+00")


def window(hours: int = 0, days: int = 0) -> tuple[datetime, datetime]:
    """[now, now + hours) for forward windows; [today - (days-1), tomorrow) for daily look-backs."""
    if hours:
        start = NOW.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=hours)
    return TODAY_LOCAL - timedelta(days=days - 1), TODAY_LOCAL + timedelta(days=1)


def lookback(days: int) -> tuple[datetime, datetime]:
    """[now - days, now] for event history."""
    return NOW - timedelta(days=days), NOW


@runtime_checkable
class DataBackend(Protocol):
    name: str

    def describe(self) -> dict: ...
    def healthcheck(self) -> dict: ...
    def get_end_of_day_report_data(self, *, store_id: str, business_date: str, comparison_date: str) -> dict: ...
    # --- catalog and identity ---
    def search_products(self, *, query_text: str | None, category: str | None, max_price: float | None,
                        fragrance_free: bool | None, skin_type: str | None, limit: int) -> dict: ...
    def get_product_details(self, product_id: str) -> dict: ...
    def list_stores(self, *, city: str | None) -> dict: ...
    def get_associate(self, associate_id: str) -> dict: ...
    def list_associates(self, *, store_id: str) -> dict: ...
    # --- inventory excellence (sheet row 3) ---
    def get_store_inventory_summary(self, *, store_id: str, category: str = "") -> dict: ...
    def list_store_inventory(self, *, store_id: str, category: str = "", query_text: str = "",
                             availability: str = "all", limit: int = 25, offset: int = 0) -> dict: ...
    def get_osa_exceptions(self, *, store_id: str, limit: int) -> dict: ...
    def check_store_stock(self, *, product_name: str, store_id: str) -> dict: ...
    def find_nearby_stock(self, *, product_name: str, store_id: str, limit: int) -> dict: ...
    def get_bopis_demand(self, *, store_id: str, product_id: str | None, hours: int) -> dict: ...
    def get_replenishment_status(self, *, store_id: str, product_id: str | None) -> dict: ...
    def get_task_status(self, *, store_id: str, product_id: str | None, status: str | None) -> dict: ...
    # --- associate orchestration (sheet row 2) ---
    def get_shift_roster(self, *, store_id: str, at_iso: str) -> dict: ...
    def get_traffic_and_backlog(self, *, store_id: str, hours: int) -> dict: ...
    # --- loss prevention (sheet row 4) ---
    def get_shrink_signals(self, *, store_id: str, product_id: str | None, days: int) -> dict: ...
    def get_sales_pattern(self, *, store_id: str, product_id: str | None, days: int) -> dict: ...
    def get_task_history(self, *, store_id: str, product_id: str | None, days: int) -> dict: ...
    # --- daily briefing and associate development (sheet rows 1 and 5) ---
    def get_guest_feedback(self, *, store_id: str, days: int) -> dict: ...
    def get_coaching_signals(self, *, associate_id: str, period: str | None) -> dict: ...
    def get_assigned_tasks(self, *, store_id: str, associate_id: str) -> dict: ...
    def complete_assigned_task(self, *, store_id: str, associate_id: str, task_id: str, completion_note: str) -> dict: ...
    def report_assigned_task_blocker(self, *, store_id: str, associate_id: str, task_id: str, blocker: str) -> dict: ...
    def get_operations_context(self, *, store_id: str, system: str, subject_id: str) -> dict: ...
    # --- the only writes: approve or delegate a task ---
    def create_store_task(self, *, store_id: str, task_type: str, product_id: str | None, assignee_id: str | None,
                          note: str, task_key: str, due_at: str | None = None) -> dict: ...
    def delegate_task(self, *, store_id: str, task_id: str, assignee_id: str, task_key: str) -> dict: ...
    # --- raw SQL (module 3 extension: the governed NL2SQL tools) ---
    def list_table_ids(self) -> dict: ...
    def get_table_info(self, table_id: str) -> dict: ...
    def execute_sql(self, query: str) -> dict: ...
    def sql_tools(self) -> list: ...


def prewarm(cfg: EnvConfig | None = None) -> dict:
    """Build the backend and take the BigQuery round trip now, so no person waits for it inside an answer.

    `make_backend` is cached and runs a healthcheck, so whoever calls it first pays for the client, the dataset
    lookup and the first query. Left alone that is the first turn of a demo: measured 2026-09-20, turn one took
    30-55 seconds against 12-19 for the same work later in the session. A server that is about to take traffic
    calls this at startup instead; it raises exactly as `make_backend` does, so a broken dataset still stops the
    process rather than surfacing inside someone's first question."""
    backend = make_backend(cfg)
    return backend.healthcheck()


@cache
def make_backend(cfg: EnvConfig | None = None) -> DataBackend:
    cfg = cfg or load_env_config()
    from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend
    backend: DataBackend = BigQueryBackend(cfg)
    health = backend.healthcheck()
    if health.get("status") != "SUCCESS":
        raise RuntimeError(f"BigQuery backend failed its healthcheck: {health.get('error_details')}")
    return backend
