"""Backend adapters returning bounded historical report facts, never full operational tables."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.reporting_fixtures import cents
from agents.cymbal_store_ops.tools.data_backend import err, ok, parse_ts


def fake_report_data(backend, *, store_id: str, business_date: str, comparison_date: str) -> dict:
    """Match the aggregate BigQuery contract using already-loaded fixture records."""
    tz = ZoneInfo(F.FIXTURE_TIMEZONE)
    days = (comparison_date, business_date)

    def local_date(value):
        return parse_ts(value).astimezone(tz).date().isoformat()

    store = next((s for s in backend.stores if s["store_id"] == store_id), None)
    if not store:
        return err("Store not found.", code="not_found")
    if not hasattr(backend, "pos_daily_product_sales") or not hasattr(backend, "worked_shifts"):
        return err("Historical POS and worked-shift feeds are not loaded.", code="missing_source")
    traffic = [
        r for r in backend.traffic if r["store_id"] == store_id and local_date(r["ts_hour"]) in days
    ]
    pos = [
        r
        for r in backend.pos_daily_product_sales
        if r["store_id"] == store_id and str(r["business_date"]) in days
    ]
    shifts = [
        r
        for r in backend.worked_shifts
        if r["store_id"] == store_id and str(r["business_date"]) == business_date
    ]
    prior_shifts = [
        r
        for r in backend.worked_shifts
        if r["store_id"] == store_id and str(r["business_date"]) == comparison_date
    ]
    summaries, hourly = [], []
    for day in days:
        trading = [r for r in traffic if local_date(r["ts_hour"]) == day]
        sold = [r for r in pos if str(r["business_date"]) == day]
        summaries.append(
            dict(
                business_date=day,
                traffic_rows=len(trading),
                traffic_hours=len(
                    {local_date(r["ts_hour"]) + str(parse_ts(r["ts_hour"]).hour) for r in trading}
                ),
                sales_cents=sum(cents(r["sales_usd"]) for r in trading),
                transactions=sum(r["transactions"] for r in trading),
                visitors=sum(r["visitors"] for r in trading),
                pos_rows=len(sold),
                units=sum(r["units_sold"] for r in sold),
                pos_sales_cents=sum(r["net_sales_cents"] for r in sold),
                invalid_pos_rows=sum(
                    r["gross_sales_cents"] - r["discount_cents"] != r["net_sales_cents"]
                    or min(r["units_sold"], r["discount_cents"], r["net_sales_cents"]) < 0
                    for r in sold
                ),
            )
        )
        hourly.extend(
            dict(
                business_date=day,
                hour=parse_ts(r["ts_hour"]).astimezone(tz).hour,
                sales_cents=cents(r["sales_usd"]),
                transactions=r["transactions"],
                visitors=r["visitors"],
            )
            for r in sorted(trading, key=lambda r: parse_ts(r["ts_hour"]))
        )
    product_rows = defaultdict(lambda: {"units_sold": 0, "net_sales_cents": 0})
    for r in pos:
        if str(r["business_date"]) == business_date:
            product_rows[r["product_id"]]["units_sold"] += r["units_sold"]
            product_rows[r["product_id"]]["net_sales_cents"] += r["net_sales_cents"]
    top = [
        dict(
            product_id=pid,
            product_name=backend._product[pid]["name"],
            category=backend._product[pid]["category"],
            **r,
        )
        for pid, r in sorted(product_rows.items(), key=lambda p: (-p[1]["units_sold"], p[0]))[:5]
    ]
    category_sales = defaultdict(lambda: dict(units_sold=0, net_sales_cents=0))
    comparable_products = defaultdict(
        lambda: dict(
            current_units=0, previous_units=0, current_sales_cents=0, previous_sales_cents=0
        )
    )
    for row in pos:
        category = backend._product[row["product_id"]]["category"]
        group = category_sales[(str(row["business_date"]), category)]
        group["units_sold"] += row["units_sold"]
        group["net_sales_cents"] += row["net_sales_cents"]
        prefix = "current" if str(row["business_date"]) == business_date else "previous"
        comparable_products[row["product_id"]][prefix + "_units"] += row["units_sold"]
        comparable_products[row["product_id"]][prefix + "_sales_cents"] += row["net_sales_cents"]
    changes = [
        dict(
            product_id=pid,
            product_name=backend._product[pid]["name"],
            **values,
            sales_change_cents=values["current_sales_cents"] - values["previous_sales_cents"],
        )
        for pid, values in comparable_products.items()
    ]
    changes.sort(key=lambda r: (-abs(r["sales_change_cents"]), r["product_id"]))
    for row in top:
        row.update(
            {
                key: value
                for key, value in comparable_products[row["product_id"]].items()
                if key.startswith("previous_")
            }
        )
    people = {p["associate_id"]: p for p in backend.associates if p["store_id"] == store_id}
    staff = defaultdict(int)
    invalid_shifts = 0
    for r in shifts:
        staff[r["associate_id"]] += r["paid_minutes"]
        invalid_shifts += (
            int((parse_ts(r["clock_out"]) - parse_ts(r["clock_in"])).total_seconds() / 60)
            - r["unpaid_break_minutes"]
            != r["paid_minutes"]
            or min(r["paid_minutes"], r["unpaid_break_minutes"]) < 0
        )
    staff_rows = [
        dict(
            associate_id=aid,
            first_name=people[aid]["first_name"],
            role=people[aid]["role"],
            paid_minutes=minutes,
        )
        for aid, minutes in sorted(staff.items())
    ]
    losses = [
        r
        for r in backend.shrink
        if r["store_id"] == store_id and local_date(r["event_ts"]) == business_date
    ]
    feedback = [
        r
        for r in backend.feedback
        if r["store_id"] == store_id and local_date(r["submitted_at"]) == business_date
    ]
    loss_categories = defaultdict(lambda: dict(event_count=0, units=0, value_cents=0))
    for row in losses:
        group = loss_categories[row["event_type"]]
        group["event_count"] += 1
        group["units"] += row["qty"]
        group["value_cents"] += cents(row["value_usd"])
    return ok(
        [
            dict(
                store={k: store[k] for k in ("store_id", "name", "city", "opens", "closes")},
                days=summaries,
                hourly=hourly,
                top_products=top,
                category_sales=[
                    dict(business_date=day, category=category, **values)
                    for (day, category), values in sorted(category_sales.items())
                ],
                product_changes=changes[:5],
                previous_attendance_rows=len(prior_shifts),
                previous_paid_minutes=sum(r["paid_minutes"] for r in prior_shifts),
                invalid_previous_attendance_rows=sum(
                    int((parse_ts(r["clock_out"]) - parse_ts(r["clock_in"])).total_seconds() / 60)
                    - r["unpaid_break_minutes"]
                    != r["paid_minutes"]
                    or min(r["paid_minutes"], r["unpaid_break_minutes"]) < 0
                    for r in prior_shifts
                ),
                staff=staff_rows[:25],
                attendance_rows=len(shifts),
                staff_count=len(staff),
                invalid_attendance_rows=invalid_shifts,
                paid_minutes=sum(staff.values()),
                issues=dict(
                    loss_by_type=[
                        dict(event_type=k, **v) for k, v in sorted(loss_categories.items())
                    ],
                    guest_reviews=len(feedback),
                    low_guest_reviews=sum(r["rating"] <= 2 for r in feedback),
                    low_feedback_topics=[
                        dict(
                            topic=topic,
                            count=sum(
                                r["rating"] <= 2 and r.get("topic", "unspecified") == topic
                                for r in feedback
                            ),
                        )
                        for topic in sorted(
                            {r.get("topic", "unspecified") for r in feedback if r["rating"] <= 2}
                        )
                    ],
                ),
            )
        ]
    )


def bigquery_report_data(
    backend, *, store_id: str, business_date: str, comparison_date: str
) -> dict:
    """One parameterized store/date-filtered aggregate query; arrays encoded before SDK conversion."""
    # Dates are parameter values. Table names are backend-owned, not caller-supplied.
    date.fromisoformat(business_date)
    date.fromisoformat(comparison_date)
    t = backend._t
    sql = f"""
    WITH days AS (SELECT DATE(@comparison) AS business_date UNION ALL SELECT DATE(@day)),
    traffic AS (
      SELECT DATE(ts_hour, @tz) AS business_date, EXTRACT(HOUR FROM DATETIME(ts_hour, @tz)) AS hour,
             CAST(ROUND(CAST(sales_usd AS NUMERIC)*100) AS INT64) AS sales_cents, transactions, visitors
      FROM {t("store_traffic")} WHERE store_id=@store
      AND ts_hour >= TIMESTAMP(DATE(@comparison), @tz) AND ts_hour < TIMESTAMP(DATE_ADD(DATE(@day), INTERVAL 1 DAY), @tz)),
    pos AS (SELECT business_date, product_id, units_sold, gross_sales_cents, discount_cents, net_sales_cents
      FROM {t("pos_daily_product_sales")} WHERE store_id=@store AND business_date IN (DATE(@day), DATE(@comparison))),
    worked_all AS (SELECT business_date,associate_id,clock_in,clock_out,unpaid_break_minutes,paid_minutes FROM {t("worked_shifts")} WHERE store_id=@store AND business_date IN (DATE(@day),DATE(@comparison))),
    worked AS (SELECT associate_id,clock_in,clock_out,unpaid_break_minutes,paid_minutes FROM worked_all WHERE business_date=DATE(@day)),
    product_compare AS (SELECT p.product_id,p.name AS product_name,p.category,
      SUM(IF(s.business_date=DATE(@day),s.units_sold,0)) AS current_units,
      SUM(IF(s.business_date=DATE(@comparison),s.units_sold,0)) AS previous_units,
      SUM(IF(s.business_date=DATE(@day),s.net_sales_cents,0)) AS current_sales_cents,
      SUM(IF(s.business_date=DATE(@comparison),s.net_sales_cents,0)) AS previous_sales_cents
      FROM pos s JOIN {t("products")} p USING(product_id) GROUP BY 1,2,3),
    trading AS (SELECT business_date, COUNT(*) AS traffic_rows, COUNT(DISTINCT hour) AS traffic_hours,
      SUM(sales_cents) AS sales_cents, SUM(transactions) AS transactions, SUM(visitors) AS visitors FROM traffic GROUP BY 1),
    sold AS (SELECT business_date, COUNT(*) AS pos_rows, SUM(units_sold) AS units, SUM(net_sales_cents) AS pos_sales_cents,
      COUNTIF(gross_sales_cents-discount_cents!=net_sales_cents OR units_sold<0 OR discount_cents<0 OR net_sales_cents<0) AS invalid_pos_rows FROM pos GROUP BY 1),
    people AS (SELECT w.associate_id, a.first_name, a.role, SUM(w.paid_minutes) AS paid_minutes FROM worked w
      JOIN {t("associates")} a ON a.associate_id=w.associate_id AND a.store_id=@store GROUP BY 1,2,3)
    SELECT TO_JSON_STRING(STRUCT(
      (SELECT AS STRUCT store_id,name,city,opens,closes FROM {t("stores")} WHERE store_id=@store) AS store,
      ARRAY(SELECT AS STRUCT CAST(d.business_date AS STRING) AS business_date,
        COALESCE(t.traffic_rows,0) AS traffic_rows, COALESCE(t.traffic_hours,0) AS traffic_hours,
        t.sales_cents,t.transactions,t.visitors,COALESCE(s.pos_rows,0) AS pos_rows,s.units,s.pos_sales_cents,
        COALESCE(s.invalid_pos_rows,0) AS invalid_pos_rows FROM days d LEFT JOIN trading t USING(business_date)
        LEFT JOIN sold s USING(business_date) ORDER BY d.business_date) AS days,
      ARRAY(SELECT AS STRUCT CAST(business_date AS STRING) AS business_date,hour,sales_cents,transactions,visitors FROM traffic ORDER BY business_date,hour) AS hourly,
      ARRAY(SELECT AS STRUCT product_id,product_name,category,current_units AS units_sold,current_sales_cents AS net_sales_cents,previous_units,previous_sales_cents
        FROM product_compare WHERE current_units>0 ORDER BY units_sold DESC,product_id LIMIT 5) AS top_products,
      ARRAY(SELECT AS STRUCT CAST(s.business_date AS STRING) AS business_date,p.category,SUM(s.units_sold) AS units_sold,SUM(s.net_sales_cents) AS net_sales_cents
        FROM pos s JOIN {t("products")} p USING(product_id) GROUP BY 1,2 ORDER BY 1,2) AS category_sales,
      ARRAY(SELECT AS STRUCT product_id,product_name,current_units,previous_units,current_sales_cents,previous_sales_cents,current_sales_cents-previous_sales_cents AS sales_change_cents
        FROM product_compare ORDER BY ABS(current_sales_cents-previous_sales_cents) DESC,product_id LIMIT 5) AS product_changes,
      (SELECT COUNT(*) FROM worked_all WHERE business_date=DATE(@comparison)) AS previous_attendance_rows,
      (SELECT COALESCE(SUM(paid_minutes),0) FROM worked_all WHERE business_date=DATE(@comparison)) AS previous_paid_minutes,
      (SELECT COUNTIF(TIMESTAMP_DIFF(clock_out,clock_in,MINUTE)-unpaid_break_minutes!=paid_minutes OR paid_minutes<0 OR unpaid_break_minutes<0) FROM worked_all WHERE business_date=DATE(@comparison)) AS invalid_previous_attendance_rows,
      ARRAY(SELECT AS STRUCT associate_id,first_name,role,paid_minutes FROM people ORDER BY associate_id LIMIT 25) AS staff,
      (SELECT COUNT(*) FROM worked) AS attendance_rows,(SELECT COUNT(*) FROM people) AS staff_count,
      (SELECT COUNTIF(TIMESTAMP_DIFF(clock_out,clock_in,MINUTE)-unpaid_break_minutes!=paid_minutes OR paid_minutes<0 OR unpaid_break_minutes<0) FROM worked) AS invalid_attendance_rows,
      (SELECT SUM(paid_minutes) FROM worked) AS paid_minutes,
      STRUCT(ARRAY(SELECT AS STRUCT event_type,COUNT(*) AS event_count,SUM(qty) AS units,
        SUM(CAST(ROUND(CAST(value_usd AS NUMERIC)*100) AS INT64)) AS value_cents FROM {t("shrink_events")}
        WHERE store_id=@store AND event_ts>=TIMESTAMP(DATE(@day),@tz)
        AND event_ts<TIMESTAMP(DATE_ADD(DATE(@day),INTERVAL 1 DAY),@tz) GROUP BY event_type ORDER BY event_type) AS loss_by_type,
        (SELECT COUNT(*) FROM {t("guest_feedback")} WHERE store_id=@store AND DATE(submitted_at,@tz)=DATE(@day)) AS guest_reviews,
        (SELECT COUNTIF(rating<=2) FROM {t("guest_feedback")} WHERE store_id=@store AND DATE(submitted_at,@tz)=DATE(@day)) AS low_guest_reviews,
        ARRAY(SELECT AS STRUCT topic,COUNT(*) AS count FROM {t("guest_feedback")} WHERE store_id=@store AND DATE(submitted_at,@tz)=DATE(@day) AND rating<=2 GROUP BY topic ORDER BY topic) AS low_feedback_topics) AS issues
    )) AS report_json
    """
    try:
        rows = backend._query(
            sql,
            {
                "store": store_id,
                "day": business_date,
                "comparison": comparison_date,
                "tz": F.FIXTURE_TIMEZONE,
            },
            tool="get_end_of_day_report_data",
            limit=1,
        )
        return (
            ok([json.loads(rows[0]["report_json"])])
            if rows
            else err("Report sources returned no result.", code="missing_source")
        )
    except Exception as exc:  # noqa: BLE001 — backend errors are visible, never replaced with fabricated facts
        return err(
            f"Historical report sources are unavailable: {type(exc).__name__}: {exc}",
            code="source_error",
        )
