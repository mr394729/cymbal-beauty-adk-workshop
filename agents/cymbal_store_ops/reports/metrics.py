"""Deterministic commercial comparisons; measurements never imply causes or policy."""

from __future__ import annotations


def commercial_metrics(metrics: dict, source: dict) -> dict:
    current, previous = metrics["current"], metrics["previous"]

    def ratio(a, b):
        return a / b if b else None

    values = {}
    for name, numerator, denominator, factor in (
        ("conversion_pct", "transactions", "visitors", 100),
        ("average_basket_cents", "sales_cents", "transactions", 1),
        ("units_per_transaction", "units", "transactions", 1),
        ("average_unit_revenue_cents", "sales_cents", "units", 1),
        ("sales_per_paid_hour_cents", "sales_cents", "paid_minutes", 60),
    ):
        before = ratio(previous[numerator] * factor, previous[denominator])
        after = ratio(current[numerator] * factor, current[denominator])
        values[name] = dict(
            current=round(after, 4) if after is not None else None,
            previous=round(before, 4) if before is not None else None,
            change=round(after - before, 4) if after is not None and before is not None else None,
            change_pct=round((after / before - 1) * 100, 4)
            if after is not None and before
            else None,
        )
    categories = {}
    for row in source["category_sales"]:
        side = "current" if row["business_date"] == metrics["business_date"] else "previous"
        categories.setdefault(row["category"], {})[side] = row
    mix = []
    for category, pair in sorted(categories.items()):
        c, p = pair.get("current", {}), pair.get("previous", {})
        cs, ps = c.get("net_sales_cents", 0), p.get("net_sales_cents", 0)
        cshare = ratio(cs * 100, current["sales_cents"])
        pshare = ratio(ps * 100, previous["sales_cents"])
        mix.append(
            dict(
                category=category,
                current_units=c.get("units_sold", 0),
                previous_units=p.get("units_sold", 0),
                current_sales_cents=cs,
                previous_sales_cents=ps,
                sales_change_cents=cs - ps,
                current_sales_share_pct=round(cshare, 3) if cshare is not None else None,
                previous_sales_share_pct=round(pshare, 3) if pshare is not None else None,
                sales_share_change_pp=round(cshare - pshare, 3)
                if cshare is not None and pshare is not None
                else None,
            )
        )
    hourly = [r for r in metrics["hourly"] if r["business_date"] == metrics["business_date"]]

    def peak(measure):
        eligible = [r for r in hourly if measure != "conversion" or r["visitors"] > 0]
        if not eligible:
            return None
        def score(r):
            return r["transactions"] / r["visitors"] if measure == "conversion" else r["transactions"]
        selected = max(eligible, key=lambda r: (score(r), -r["hour"]))
        h = selected["hour"]
        return dict(
            local_hour=f"{(h - 1) % 12 + 1}:00 {'AM' if h < 12 else 'PM'}",
            transactions=selected["transactions"],
            visitors=selected["visitors"],
            conversion_pct=round(selected["transactions"] / selected["visitors"] * 100, 4)
            if selected["visitors"] else None,
            measure="transactions" if measure == "transactions" else "transactions / visitors",
            tied_local_hours=[r["hour"] for r in eligible if score(r) == score(selected)],
        )

    return dict(
        ratios=values,
        peak_transactions=peak("transactions"),
        peak_conversion=peak("conversion"),
        category_mix=mix,
        largest_product_sales_changes=source["product_changes"],
        definitions={
            "hourly_peaks": "Current business date in store-local time; highest transaction count and highest conversion ratio are distinct. Earliest hour is shown if tied; tied_local_hours uses 0–23.",
            "conversion_pct": "Transactions / visitors × 100; change is percentage points.",
            "average_basket_cents": "Recorded sales / transactions; current, previous and change are cents per transaction, not total sales dollars.",
            "units_per_transaction": "Units sold / transactions.",
            "average_unit_revenue_cents": "Recorded product sales / units; current, previous and change are cents per unit. A change does not distinguish product mix from discounts or establish a list-price change.",
            "sales_per_paid_hour_cents": "Sales / actual paid worked hours, not scheduled hours or profit.",
        },
        evidence_limits=[
            "One-day comparison; not a trend or causal proof. Describe observed relationships, not causal sales attribution to traffic, conversion, staffing or categories.",
            "Category sales, unit counts and shares are separate measures; the largest sales category is not necessarily the largest unit or growth contributor.",
            "A low review tagged stock does not identify a product, category or ongoing shortage. Verify current stock before proposing a targeted replenishment action.",
            "A recommended investigation is prospective; the recorded issue does not establish its cause, resolution or need for a specific corrective action.",
            "No target, margin, lost-sales, promotion or clienteling attribution data in this report.",
            "Recorded loss types are separate; adjustments and return anomalies are not automatically theft.",
        ],
    )
