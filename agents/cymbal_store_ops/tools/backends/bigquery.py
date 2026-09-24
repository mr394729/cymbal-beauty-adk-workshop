"""BigQuery backend: parameterised domain queries plus the native ADK BigQuery toolset for NL2SQL.

Governance is deterministic: read-only toolset (WriteMode.BLOCKED), byte caps, job labels on every
job (attributable in INFORMATION_SCHEMA.JOBS), and the only DML is the two `store_tasks` writes, each a
single statement whose `num_dml_affected_rows` decides the outcome.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import google.auth
from google.cloud import bigquery

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.config import EnvConfig
from agents.cymbal_store_ops.tools.data_backend import (
    NOW,
    Row,
    bq_ts,
    err,
    fold,
    lookback,
    ok,
    parse_ts,
    window,
)
from agents.cymbal_store_ops.tools.sql_guard import SqlGuardError, assert_select_only

BQ_SCOPES = ["https://www.googleapis.com/auth/bigquery", "https://www.googleapis.com/auth/cloud-platform"]
LOCAL_TZ_NAME = F.FIXTURE_TIMEZONE

# A name as a person types it: lower-case, accents removed (NFD, then the combining marks dropped). Matches fold().
def folded(column: str) -> str:
    return rf"REGEXP_REPLACE(NORMALIZE(LOWER({column}), NFD), r'\pM', '')"


PRODUCT_COLS = "p.name AS product_name, p.category, p.locked_case, p.price_usd"
INVENTORY_COLS = """s.store_id, s.name AS store_name, s.city, s.state, i.product_id, p.name AS product_name,
                    p.category, p.locked_case, p.price_usd, i.on_hand, i.on_shelf_qty, i.backroom_qty,
                    i.reorder_point, i.shelf_capacity, i.bopis_eligible, i.updated_at"""


def _jsonable(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return json.loads(json.dumps(v, default=str))


def _iso(value):
    """A timestamp column as ISO text (the model reads it; the function response is serialised as JSON)."""
    return value.isoformat() if hasattr(value, "isoformat") else value


class BigQueryBackend:
    name = "bigquery"

    def __init__(self, cfg: EnvConfig) -> None:
        self.cfg = cfg
        self.credentials, _ = google.auth.default(scopes=BQ_SCOPES)
        self.client = bigquery.Client(project=cfg.project, credentials=self.credentials, location=cfg.bigquery.location)
        self.main = f"{cfg.project}.{cfg.bigquery.dataset}"
        self.labels = {**cfg.bigquery.job_labels, "data_backend": "bigquery"}
        self.limit = cfg.data.max_query_result_rows

    # ---- plumbing --------------------------------------------------------------------------
    @staticmethod
    def _params(params: dict[str, Any] | None) -> list[bigquery.ScalarQueryParameter]:
        qp = []
        for k, v in (params or {}).items():
            t = "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"
            qp.append(bigquery.ScalarQueryParameter(k, t, v))
        return qp

    def _job_config(self, tool: str, params: dict[str, Any] | None) -> bigquery.QueryJobConfig:
        return bigquery.QueryJobConfig(
            query_parameters=self._params(params),
            labels={**self.labels, "tool": tool},
            maximum_bytes_billed=self.cfg.data.maximum_bytes_billed,
        )

    def _query(self, sql: str, params: dict[str, Any] | None = None, *, tool: str, limit: int | None = None) -> list[Row]:
        # jobs.query returns short read results in its initial response, avoiding
        # jobs.insert plus polling RPCs. The SDK still waits/pages when needed.
        rows = self.client.query_and_wait(
            sql, job_config=self._job_config(tool, params),
            api_timeout=self.cfg.data.statement_timeout_s,
            wait_timeout=self.cfg.data.statement_timeout_s, max_results=limit,
        )
        return [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]

    def _dml(self, sql: str, params: dict[str, Any], *, tool: str) -> int:
        """Run one DML statement; return the number of affected rows (raises on failure, nothing partial)."""
        job = self.client.query(sql, job_config=self._job_config(tool, params), timeout=self.cfg.data.statement_timeout_s)
        job.result(timeout=self.cfg.data.statement_timeout_s)
        return int(job.num_dml_affected_rows or 0)

    def _t(self, table: str) -> str:
        return f"`{self.main}.{table}`"

    def get_end_of_day_report_data(self, *, store_id: str, business_date: str, comparison_date: str) -> dict:
        from agents.cymbal_store_ops.tools.backends.reporting import bigquery_report_data
        return bigquery_report_data(self, store_id=store_id, business_date=business_date, comparison_date=comparison_date)

    def describe(self) -> dict:
        return {"dialect": "BigQuery Standard SQL", "project_id": self.cfg.project,
                "dataset_id": self.cfg.bigquery.dataset, "table_prefix": self.main}

    def healthcheck(self) -> dict:
        try:
            n = self._query(f"SELECT COUNT(*) AS n FROM {self._t('products')}", tool="healthcheck")[0]["n"]
            return ok([{"products": n}]) if n > 0 else err(f"{self.main}.products is empty — run `uv run python data/generate.py && bash data/load.sh --env dev`")
        except Exception as e:  # noqa: BLE001
            return err(f"BigQuery healthcheck failed for {self.main}: {e}")

    # ---- catalog and identity --------------------------------------------------------------
    def search_products(self, *, query_text, category, max_price, fragrance_free, skin_type, limit) -> dict:
        where, params = ["TRUE"], {}
        if query_text:
            where.append(f"({folded('name')} LIKE @q OR LOWER(subcategory) LIKE @q OR LOWER(key_ingredients) LIKE @q OR {folded('brand')} LIKE @q OR LOWER(description) LIKE @q)")
            params["q"] = f"%{fold(query_text)}%"
        if category:
            where.append("category = @category")
            params["category"] = category
        if max_price is not None:
            where.append("price_usd <= @max_price")
            params["max_price"] = float(max_price)
        if fragrance_free is not None:
            where.append("is_fragrance_free = @ff")
            params["ff"] = bool(fragrance_free)
        if skin_type:
            where.append("LOWER(skin_types) LIKE @skin")
            params["skin"] = f"%{skin_type.lower()}%"
        # COUNT(*) OVER () carries the number of catalog products that match, whatever the page size, so a caller
        # can say "three of the seventy" instead of reporting the page as the total.
        sql = f"""SELECT product_id, brand, name, category, subcategory, price_usd, is_fragrance_free, locked_case,
                         skin_types, key_ingredients, rating_avg, rating_count, COUNT(*) OVER () AS total_matching
                  FROM {self._t('products')} WHERE {' AND '.join(where)}
                  ORDER BY rating_avg DESC NULLS LAST, price_usd ASC LIMIT @lim"""
        params["lim"] = int(limit)
        try:
            rows = self._query(sql, params, tool="search_products")
        except Exception as e:  # noqa: BLE001
            return err(f"search_products failed: {e}")
        total = int(rows[0]["total_matching"]) if rows else 0
        for row in rows:
            row.pop("total_matching", None)
        return ok(rows, limit=limit, total_matching=total)

    def get_product_details(self, product_id: str) -> dict:
        sql = f"""WITH review_sample AS (
                      SELECT product_id, COUNT(*) AS available_review_count,
                             ARRAY_AGG(STRUCT(review_id, rating, title, body, skin_type, created_at)
                                       ORDER BY created_at DESC, review_id ASC LIMIT 3) AS top_reviews
                      FROM {self._t('reviews')} WHERE product_id = @pid GROUP BY product_id
                  )
                  SELECT p.*, IFNULL(r.top_reviews, []) AS top_reviews,
                         IFNULL(r.available_review_count, 0) AS available_review_count,
                         'latest 3, not a representative sample' AS review_sample_basis
                  FROM {self._t('products')} p LEFT JOIN review_sample r USING (product_id)
                  WHERE p.product_id = @pid"""
        try:
            rows = self._query(sql, {"pid": product_id}, tool="get_product_details")
        except Exception as e:  # noqa: BLE001
            return err(f"get_product_details failed: {e}")
        return ok(rows) if rows else err(f"product {product_id} not found")

    def list_stores(self, *, city: str | None) -> dict:
        sql = f"""SELECT store_id, name, city, state, opens, closes FROM {self._t('stores')}
                  WHERE @city = '' OR LOWER(city) = @city ORDER BY store_id"""
        try:
            return ok(self._query(sql, {"city": (city or "").lower()}, tool="list_stores"))
        except Exception as e:  # noqa: BLE001
            return err(f"list_stores failed: {e}")

    def list_associates(self, *, store_id: str) -> dict:
        sql = f"""SELECT associate_id, first_name, role, store_id FROM {self._t('associates')}
                  WHERE store_id = @sid ORDER BY associate_id"""
        try:
            return ok(self._query(sql, {"sid": store_id}, tool="list_associates"))
        except Exception as e:  # noqa: BLE001
            return err(f"list_associates failed: {e}")

    def get_associate(self, associate_id: str) -> dict:
        sql = f"""SELECT a.*, s.name AS store_name FROM {self._t('associates')} a JOIN {self._t('stores')} s USING (store_id)
                  WHERE a.associate_id = @aid"""
        try:
            rows = self._query(sql, {"aid": associate_id}, tool="get_associate")
        except Exception as e:  # noqa: BLE001
            return err(f"get_associate failed: {e}")
        return ok(rows) if rows else err(f"associate {associate_id} not found", code="not_found")

    # ---- inventory excellence ----------------------------------------------------------------
    def get_store_inventory_summary(self, *, store_id: str, category: str = "") -> dict:
        from agents.cymbal_store_ops.tools.inventory_summary import summary_result
        sql = f"""SELECT p.category, COUNT(*) AS inventory_row_count,
                         COUNT(DISTINCT i.product_id) AS sku_count,
                         COUNT(DISTINCT IF(i.on_hand > 0, i.product_id, NULL)) AS stocked_sku_count,
                         SUM(i.on_hand) AS on_hand_units, SUM(i.on_shelf_qty) AS on_shelf_units,
                         SUM(i.backroom_qty) AS backroom_units,
                         COUNT(DISTINCT IF(i.on_shelf_qty = 0 AND i.on_hand > 0, i.product_id, NULL)) AS empty_shelf_sku_count,
                         COUNT(DISTINCT IF(i.on_hand = 0, i.product_id, NULL)) AS out_of_stock_sku_count,
                         COUNT(DISTINCT IF(i.on_hand < i.reorder_point, i.product_id, NULL)) AS low_stock_sku_count
                  FROM {self._t('store_inventory')} i JOIN {self._t('products')} p USING (product_id)
                  WHERE i.store_id = @sid GROUP BY p.category ORDER BY p.category"""
        try:
            rows = self._query(sql, {"sid": store_id}, tool="get_store_inventory_summary")
        except Exception as e:  # noqa: BLE001
            return err(f"get_store_inventory_summary failed: {e}")
        # All categories are a small aggregate, so unknown categories remain distinguishable
        # from a known category with no matching availability. No product rows reach the model.
        return summary_result(rows, store_id=store_id, category=category)

    def list_store_inventory(self, *, store_id: str, category: str = "", query_text: str = "",
                             availability: str = "all", limit: int = 25, offset: int = 0) -> dict:
        from agents.cymbal_store_ops.tools.inventory_summary import page_result, validate_page
        if error := validate_page(availability, limit, offset):
            return error
        category, query_text = category.strip().casefold(), query_text.strip()
        predicates = {"all": "TRUE", "in_stock": "on_hand > 0", "out_of_stock": "on_hand = 0",
                      "empty_shelf": "on_shelf_qty = 0 AND on_hand > 0", "low_stock": "on_hand < reorder_point"}
        sql = f"""WITH store_stock AS (
                      SELECT i.product_id, p.name AS product_name, p.category, p.brand, p.price_usd,
                             i.on_hand, i.on_shelf_qty, i.backroom_qty, i.reorder_point
                      FROM {self._t('store_inventory')} i JOIN {self._t('products')} p USING (product_id)
                      WHERE i.store_id = @sid),
                  matching AS (
                      SELECT product_id, product_name, category, brand, price_usd,
                             on_hand, on_shelf_qty, backroom_qty, reorder_point
                      FROM store_stock
                      WHERE (@category = '' OR category = @category)
                        AND (@query = '' OR STRPOS({folded('product_name')}, @query) > 0
                             OR STRPOS({folded('brand')}, @query) > 0 OR STRPOS(LOWER(product_id), @query) > 0)
                        AND ({predicates[availability]}))
                  SELECT ARRAY(SELECT AS STRUCT product_id, product_name, category, brand, price_usd,
                               on_hand, on_shelf_qty, backroom_qty, reorder_point
                               FROM matching ORDER BY product_id LIMIT @lim OFFSET @offset) AS page_rows,
                         (SELECT COUNT(*) FROM matching) AS total_matching,
                         ARRAY(SELECT DISTINCT category FROM store_stock ORDER BY category) AS available_categories"""
        try:
            result = self._query(sql, {"sid": store_id, "category": category, "query": fold(query_text),
                                       "lim": limit, "offset": offset}, tool="list_store_inventory")[0]
        except Exception as e:  # noqa: BLE001
            return err(f"list_store_inventory failed: {e}")
        return page_result(result["page_rows"], store_id=store_id, category=category, query_text=query_text,
                           availability=availability, limit=limit, offset=offset,
                           total_matching=int(result["total_matching"]),
                           available_categories=result["available_categories"])

    def get_osa_exceptions(self, *, store_id: str, limit: int) -> dict:
        sql = f"""SELECT {INVENTORY_COLS},
                         IF(i.on_shelf_qty = 0 AND i.on_hand > 0, 'shelf_empty', 'below_reorder_point') AS exception_type,
                         i.reorder_point - i.on_hand AS shortfall
                  FROM {self._t('store_inventory')} i
                  JOIN {self._t('stores')} s USING (store_id)
                  JOIN {self._t('products')} p USING (product_id)
                  WHERE i.store_id = @sid AND ((i.on_shelf_qty = 0 AND i.on_hand > 0) OR i.on_hand < i.reorder_point)
                  ORDER BY exception_type != 'shelf_empty', shortfall DESC, i.backroom_qty DESC, i.product_id
                  LIMIT @lim"""
        try:
            return ok(self._query(sql, {"sid": store_id, "lim": int(limit)}, tool="get_osa_exceptions"), limit=limit)
        except Exception as e:  # noqa: BLE001
            return err(f"get_osa_exceptions failed: {e}")

    def check_store_stock(self, *, product_name: str, store_id: str) -> dict:
        sql = f"""SELECT {INVENTORY_COLS}
                  FROM {self._t('store_inventory')} i
                  JOIN {self._t('stores')} s USING (store_id)
                  JOIN {self._t('products')} p USING (product_id)
                  WHERE i.store_id = @sid AND ({folded('p.name')} LIKE @pname OR LOWER(p.product_id) = @pid)
                  ORDER BY i.on_hand DESC LIMIT 5"""
        try:
            rows = self._query(sql, {"sid": store_id, "pname": f"%{fold(product_name)}%", "pid": product_name.lower()}, tool="check_store_stock")
        except Exception as e:  # noqa: BLE001
            return err(f"check_store_stock failed: {e}")
        if not rows:
            return err(f"no product matches {product_name!r} at store {store_id}")
        return ok(rows)

    def find_nearby_stock(self, *, product_name: str, store_id: str, limit: int) -> dict:
        sql = f"""SELECT {INVENTORY_COLS}
                  FROM {self._t('store_inventory')} i
                  JOIN {self._t('stores')} s USING (store_id)
                  JOIN {self._t('products')} p USING (product_id)
                  WHERE s.state = (SELECT state FROM {self._t('stores')} WHERE store_id = @sid)
                    AND s.store_id != @sid AND i.on_hand > 0
                    AND ({folded('p.name')} LIKE @pname OR LOWER(p.product_id) = @pid)
                  ORDER BY i.on_hand DESC, s.store_id LIMIT @lim"""
        try:
            rows = self._query(sql, {"sid": store_id, "pname": f"%{fold(product_name)}%", "pid": product_name.lower(), "lim": int(limit)},
                               tool="find_nearby_stock")
        except Exception as e:  # noqa: BLE001
            return err(f"find_nearby_stock failed: {e}")
        return ok(rows, limit=limit)

    def get_bopis_demand(self, *, store_id: str, product_id: str | None, hours: int) -> dict:
        _, until = window(hours=hours)
        sql = f"""SELECT o.order_id, o.store_id, o.product_id, {PRODUCT_COLS}, o.qty, o.promised_at, o.status,
                         COUNT(*) OVER () AS pending_count
                  FROM {self._t('bopis_orders')} o JOIN {self._t('products')} p USING (product_id)
                  WHERE o.store_id = @sid AND o.status = 'pending' AND o.promised_at <= TIMESTAMP(@until)
                    AND (@pid = '' OR o.product_id = @pid)
                  ORDER BY o.promised_at, o.order_id LIMIT @lim"""
        try:
            rows = self._query(sql, {"sid": store_id, "until": bq_ts(until), "pid": product_id or "", "lim": self.limit}, tool="get_bopis_demand")
        except Exception as e:  # noqa: BLE001
            return err(f"get_bopis_demand failed: {e}")
        pending = int(rows[0].pop("pending_count")) if rows else 0
        for r in rows[1:]:
            r.pop("pending_count", None)
        return ok(rows, limit=self.limit, pending_count=pending, window_end=until.isoformat())

    def get_replenishment_status(self, *, store_id: str, product_id: str | None) -> dict:
        sql = f"""SELECT r.store_id, r.product_id, {PRODUCT_COLS}, r.expected_at, r.qty, r.status
                  FROM {self._t('replenishment')} r JOIN {self._t('products')} p USING (product_id)
                  WHERE r.store_id = @sid AND (@pid = '' OR r.product_id = @pid)
                  ORDER BY r.expected_at, r.product_id LIMIT @lim"""
        try:
            return ok(self._query(sql, {"sid": store_id, "pid": product_id or "", "lim": self.limit}, tool="get_replenishment_status"), limit=self.limit)
        except Exception as e:  # noqa: BLE001
            return err(f"get_replenishment_status failed: {e}")

    def _tasks(self, where: str, params: dict[str, Any], *, order: str, tool: str) -> list[Row]:
        sql = f"""SELECT t.*, p.name AS product_name
                  FROM {self._t('store_tasks')} t LEFT JOIN {self._t('products')} p USING (product_id)
                  WHERE {where} ORDER BY {order} LIMIT @lim"""
        return self._query(sql, {**params, "lim": self.limit}, tool=tool)

    def get_task_status(self, *, store_id: str, product_id: str | None, status: str | None) -> dict:
        try:
            rows = self._tasks("t.store_id = @sid AND (@pid = '' OR t.product_id = @pid) AND (@st = '' OR t.status = @st)",
                               {"sid": store_id, "pid": product_id or "", "st": status or ""}, order="t.due_at, t.task_id", tool="get_task_status")
        except Exception as e:  # noqa: BLE001
            return err(f"get_task_status failed: {e}")
        return ok(rows, limit=self.limit)

    # ---- associate orchestration -------------------------------------------------------------
    def get_shift_roster(self, *, store_id: str, at_iso: str) -> dict:
        at = parse_ts(at_iso)
        sql = f"""WITH assignments AS (
                      SELECT store_id, assignee_id,
                             ARRAY_AGG(STRUCT(task_id, task_type, note, due_at) ORDER BY due_at, task_id) AS assigned_tasks
                      FROM {self._t('store_tasks')}
                      WHERE store_id = @sid AND status = 'open'
                      GROUP BY store_id, assignee_id)
                  SELECT a.associate_id, a.first_name, a.role, a.skills, a.shift_start, a.shift_end, a.current_task,
                         IFNULL(t.assigned_tasks, []) AS assigned_tasks
                  FROM {self._t('associates')} a
                  LEFT JOIN assignments t ON t.store_id = a.store_id AND t.assignee_id = a.associate_id
                  WHERE a.store_id = @sid AND a.shift_start <= TIMESTAMP(@at) AND a.shift_end > TIMESTAMP(@at)
                  ORDER BY a.shift_end, a.associate_id"""
        try:
            return ok(self._query(sql, {"sid": store_id, "at": bq_ts(at)}, tool="get_shift_roster"))
        except Exception as e:  # noqa: BLE001
            return err(f"get_shift_roster failed: {e}")

    def get_traffic_and_backlog(self, *, store_id: str, hours: int) -> dict:
        start, until = window(hours=hours)
        traffic = f"""SELECT ts_hour, visitors, transactions, sales_usd FROM {self._t('store_traffic')}
                      WHERE store_id = @sid AND ts_hour >= TIMESTAMP(@start) AND ts_hour < TIMESTAMP(@until) ORDER BY ts_hour"""
        backlog = f"""SELECT COUNT(*) AS n, MIN(promised_at) AS earliest, MAX(promised_at) AS latest FROM {self._t('bopis_orders')}
                      WHERE store_id = @sid AND status = 'pending' AND promised_at <= TIMESTAMP(@until)"""
        params = {"sid": store_id, "start": bq_ts(start), "until": bq_ts(until)}
        try:
            rows = self._query(traffic, params, tool="get_traffic_and_backlog")
            summary = self._query(backlog, {"sid": store_id, "until": bq_ts(until)}, tool="get_traffic_and_backlog")[0]
        except Exception as e:  # noqa: BLE001
            return err(f"get_traffic_and_backlog failed: {e}")
        return ok(rows, pending_bopis=int(summary["n"]), earliest_promise=_iso(summary["earliest"]), latest_promise=_iso(summary["latest"]),
                  window_start=start.isoformat(), window_end=until.isoformat())

    # ---- loss prevention ---------------------------------------------------------------------
    def get_shrink_signals(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        since, until = lookback(days)
        sql = f"""SELECT e.product_id, {PRODUCT_COLS}, e.event_type, COUNT(*) AS events, SUM(e.qty) AS qty,
                         ROUND(SUM(e.value_usd), 2) AS value_usd, MIN(e.event_ts) AS first_event_ts, MAX(e.event_ts) AS last_event_ts
                  FROM {self._t('shrink_events')} e JOIN {self._t('products')} p USING (product_id)
                  WHERE e.store_id = @sid AND e.event_ts BETWEEN TIMESTAMP(@since) AND TIMESTAMP(@until)
                    AND (@pid = '' OR e.product_id = @pid)
                  GROUP BY ALL ORDER BY value_usd DESC, e.product_id, e.event_type LIMIT @lim"""
        params = {"sid": store_id, "since": bq_ts(since), "until": bq_ts(until), "pid": product_id or "", "lim": self.limit}
        try:
            rows = self._query(sql, params, tool="get_shrink_signals")
        except Exception as e:  # noqa: BLE001
            return err(f"get_shrink_signals failed: {e}")
        return ok(rows, limit=self.limit, complete=len(rows) < self.limit, window_start=since.isoformat(), window_end=until.isoformat())

    def get_sales_pattern(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        start, until = window(days=days)
        sql = f"""SELECT FORMAT_DATE('%F', DATE(ts_hour, '{LOCAL_TZ_NAME}')) AS day, SUM(visitors) AS visitors,
                         SUM(transactions) AS transactions, ROUND(SUM(sales_usd), 2) AS sales_usd
                  FROM {self._t('store_traffic')}
                  WHERE store_id = @sid AND ts_hour >= TIMESTAMP(@start) AND ts_hour < TIMESTAMP(@until)
                  GROUP BY day ORDER BY day"""
        try:
            rows = self._query(sql, {"sid": store_id, "start": bq_ts(start), "until": bq_ts(until)}, tool="get_sales_pattern")
        except Exception as e:  # noqa: BLE001
            return err(f"get_sales_pattern failed: {e}")
        return ok(rows, product_id=product_id, granularity="store-level daily totals")

    def get_task_history(self, *, store_id: str, product_id: str | None, days: int) -> dict:
        since, _ = lookback(days)
        try:
            rows = self._tasks("t.store_id = @sid AND (@pid = '' OR t.product_id = @pid) AND t.created_at >= TIMESTAMP(@since)",
                               {"sid": store_id, "pid": product_id or "", "since": bq_ts(since)},
                               order="t.created_at DESC, t.task_id DESC", tool="get_task_history")
        except Exception as e:  # noqa: BLE001
            return err(f"get_task_history failed: {e}")
        return ok(rows, limit=self.limit)

    # ---- daily briefing and associate development --------------------------------------------
    def get_guest_feedback(self, *, store_id: str, days: int) -> dict:
        since, _ = lookback(days)
        sql = f"""SELECT feedback_id, store_id, submitted_at, rating, topic, comment FROM {self._t('guest_feedback')}
                  WHERE store_id = @sid AND submitted_at >= TIMESTAMP(@since) ORDER BY submitted_at DESC, feedback_id DESC LIMIT @lim"""
        try:
            return ok(self._query(sql, {"sid": store_id, "since": bq_ts(since), "lim": self.limit}, tool="get_guest_feedback"), limit=self.limit)
        except Exception as e:  # noqa: BLE001
            return err(f"get_guest_feedback failed: {e}")

    def get_coaching_signals(self, *, associate_id: str, period: str | None) -> dict:
        who = self.get_associate(associate_id)
        if who.get("status") != "SUCCESS":
            return who
        a = who["rows"][0]
        sql = f"""SELECT c.associate_id, c.period, c.metric, c.value, a.first_name, a.role, a.store_id
                  FROM {self._t('coaching_signals')} c JOIN {self._t('associates')} a USING (associate_id)
                  WHERE c.associate_id = @aid AND (@period = '' OR c.period = @period) ORDER BY c.period, c.metric"""
        try:
            rows = self._query(sql, {"aid": associate_id, "period": period or ""}, tool="get_coaching_signals")
        except Exception as e:  # noqa: BLE001
            return err(f"get_coaching_signals failed: {e}")
        return ok(rows, associate={k: a[k] for k in ("associate_id", "first_name", "role", "store_id", "skills")})

    # ---- the only writes ---------------------------------------------------------------------
    def get_assigned_tasks(self, *, store_id, associate_id) -> dict:
        return ok(self._tasks("t.store_id=@s AND t.assignee_id=@a", {"s": store_id, "a": associate_id},
                              order="t.due_at", tool="get_assigned_tasks"))

    def complete_assigned_task(self, *, store_id, associate_id, task_id, completion_note) -> dict:
        count = self._dml(f"UPDATE {self._t('store_tasks')} SET status='done', "
                          "note=CONCAT(note, ' | Completion: ', @note) "
                          "WHERE store_id=@s AND assignee_id=@a AND task_id=@id AND status='open'",
                          {"s": store_id, "a": associate_id, "id": task_id, "note": completion_note}, tool="complete_my_task")
        result = self._tasks("t.store_id=@s AND t.assignee_id=@a AND t.task_id=@id",
                             {"s": store_id, "a": associate_id, "id": task_id}, order="t.due_at", tool="complete_my_task")
        if not result or result[0]["status"] != "done":
            return err("Task assignment or status changed; refresh your work.", code="conflict")
        return ok(result, already_completed=count == 0)

    def report_assigned_task_blocker(self, *, store_id, associate_id, task_id, blocker) -> dict:
        marker = " | Blocker: " + blocker + " |"
        params = {"s": store_id, "a": associate_id, "id": task_id, "marker": marker}
        count = self._dml(f"UPDATE {self._t('store_tasks')} SET note=CONCAT(note, @marker) "
                          "WHERE store_id=@s AND assignee_id=@a AND task_id=@id AND status='open' "
                          "AND STRPOS(note, @marker)=0", params, tool="report_my_task_blocker")
        result = self._tasks("t.store_id=@s AND t.assignee_id=@a AND t.task_id=@id",
                             {"s": store_id, "a": associate_id, "id": task_id}, order="t.due_at", tool="report_my_task_blocker")
        if not result or result[0]["status"] != "open" or marker not in result[0]["note"]:
            return err("Task assignment or status changed; refresh your work.", code="conflict")
        return ok(result, already_reported=count == 0)

    def get_operations_context(self, *, store_id, system, subject_id) -> dict:
        import json
        rows = self._query(f"SELECT * FROM {self._t('operations_context')} "
                           "WHERE store_id=@s AND system=@system AND subject_id=@subject",
                           {"s": store_id, "system": system, "subject": subject_id}, tool="get_operations_context")
        return ok([{**r, "payload": json.loads(r["payload"])} for r in rows])

    def create_store_task(self, *, store_id, task_type, product_id, assignee_id, note, task_key, due_at=None) -> dict:
        """One INSERT guarded by NOT EXISTS on the task key: a retry inserts nothing and reads the original row."""
        if task_type not in F.TASK_TYPES:
            return err(f"task_type {task_type!r} is not one of {F.TASK_TYPES}")
        params = {"tid": f"T-{task_key[:8].upper()}", "sid": store_id, "tt": task_type, "pid": product_id or "",
                  "aid": assignee_id or "", "note": note, "k": task_key, "now": bq_ts(NOW),
                  "due": bq_ts(parse_ts(due_at)) if due_at else bq_ts(NOW + timedelta(hours=4))}
        sql = f"""INSERT INTO {self._t('store_tasks')}
                    (task_id, store_id, task_type, product_id, assignee_id, status, source, created_at, due_at, note, task_key, delegation_key)
                  SELECT @tid, @sid, @tt, NULLIF(@pid, ''), NULLIF(@aid, ''), 'open', 'agent', TIMESTAMP(@now),
                         TIMESTAMP(@due), @note, @k, NULL
                  FROM UNNEST([1]) AS _one
                  WHERE NOT EXISTS (SELECT 1 FROM {self._t('store_tasks')} WHERE task_key = @k)
                    AND (@pid = '' OR EXISTS (SELECT 1 FROM {self._t('products')} WHERE product_id = @pid))
                    AND (@aid = '' OR EXISTS (SELECT 1 FROM {self._t('associates')} WHERE associate_id = @aid AND store_id = @sid))"""
        try:
            inserted = self._dml(sql, params, tool="create_store_task")
            rows = self._tasks("t.task_key = @k", {"k": task_key}, order="t.task_id", tool="create_store_task")
        except Exception as e:  # noqa: BLE001
            return err(f"create_store_task failed: {e}")
        if rows:
            return ok(rows, already_created=inserted == 0)
        if product_id:
            return err(f"product {product_id} not found (or {assignee_id or 'no assignee'} is not an associate at {store_id})", code="not_found")
        return err(f"{assignee_id} is not an associate at {store_id}", code="not_found")

    def delegate_task(self, *, store_id, task_id, assignee_id, task_key) -> dict:
        """Read the task; a repeat of the same delegation returns it unchanged, otherwise one UPDATE that only
        touches an open task at this store and only for an associate of this store."""
        where, ids = "t.task_id = @tid AND t.store_id = @sid", {"tid": task_id, "sid": store_id}
        try:
            rows = self._tasks(where, ids, order="t.task_id", tool="delegate_task")
        except Exception as e:  # noqa: BLE001
            return err(f"delegate_task failed: {e}")
        if not rows:
            return err(f"task {task_id} not found at {store_id}", code="not_found")
        row = rows[0]
        if row.get("delegation_key") == task_key and row.get("assignee_id") == assignee_id:
            return ok(rows, already_delegated=True)
        if row["status"] != "open":
            return err(f"task {task_id} is {row['status']}; only open tasks can be delegated", code="conflict")
        sql = f"""UPDATE {self._t('store_tasks')} SET assignee_id = @aid, delegation_key = @k
                  WHERE task_id = @tid AND store_id = @sid AND status = 'open'
                    AND EXISTS (SELECT 1 FROM {self._t('associates')} WHERE associate_id = @aid AND store_id = @sid)"""
        try:
            updated = self._dml(sql, {**ids, "aid": assignee_id, "k": task_key}, tool="delegate_task")
            if updated == 1:
                return ok(self._tasks(where, ids, order="t.task_id", tool="delegate_task"), already_delegated=False)
            rows = self._tasks(where, ids, order="t.task_id", tool="delegate_task")
        except Exception as e:  # noqa: BLE001
            return err(f"delegate_task failed: {e}")
        if rows and rows[0]["status"] != "open":
            return err(f"task {task_id} is {rows[0]['status']}; only open tasks can be delegated", code="conflict")
        return err(f"{assignee_id} is not an associate at {store_id}", code="not_found")

    # ---- raw SQL extension -----------------------------------------------------------------
    def list_table_ids(self) -> dict:
        return ok([{"table_id": t.table_id} for t in self.client.list_tables(self.cfg.bigquery.dataset)])

    def get_table_info(self, table_id: str) -> dict:
        try:
            t = self.client.get_table(f"{self.main}.{table_id}")
        except Exception as e:  # noqa: BLE001
            return err(f"table {table_id} not found: {e}")
        return ok([t.to_api_repr()])

    def execute_sql(self, query: str) -> dict:
        try:
            q = assert_select_only(query, (self.main,))
            return ok(self._query(q, tool="execute_sql", limit=self.limit), limit=self.limit)
        except SqlGuardError as e:
            return err(f"Read-only mode only supports SELECT statements: {e}")
        except Exception as e:  # noqa: BLE001
            return err(f"execute_sql failed: {e}")

    def sql_tools(self) -> list:
        """The native ADK BigQuery toolset, read-only, capped and labelled (module 3's NL2SQL extension)."""
        from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
        from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode

        return [BigQueryToolset(
            tool_filter=["list_table_ids", "get_table_info", "execute_sql"],
            credentials_config=BigQueryCredentialsConfig(credentials=self.credentials),
            bigquery_tool_config=BigQueryToolConfig(
                write_mode=WriteMode.BLOCKED,
                max_query_result_rows=self.limit,
                maximum_bytes_billed=self.cfg.data.maximum_bytes_billed,
                compute_project_id=self.cfg.project,
                location=self.cfg.bigquery.location,
                application_name="cymbal_store_ops",
                job_labels=self.labels,
            ),
        )]
