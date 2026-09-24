"""Bounded historical analytics fixtures, generated without modifying operational tables."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from agents.cymbal_store_ops import fixtures as F

REPORT_TABLE_COUNTS = {"pos_daily_product_sales": 40, "worked_shifts": 16}
REPORT_DATES = ("2026-10-01", "2026-10-02")
PRODUCTS = (
    "P-0101",
    "P-0548",
    "P-0420",
    "P-0001",
    "P-0011",
    "P-0051",
    "P-0181",
    "P-0201",
    "P-0217",
    "P-0301",
    "P-0321",
    "P-0341",
    "P-0401",
    "P-0451",
    "P-0481",
    "P-0501",
    "P-0521",
    "P-0561",
    "P-0581",
    "P-0600",
)
QUANTITIES = (26, 24, 22, 20, 18, 16, 14, 12, 11, 10, 9, 8, 8, 7, 7, 6, 5, 5, 4, 4)


def cents(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def generate_report_tables(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Two days at S-014 only; source totals reconcile to the cent. Input is never mutated."""
    tz = ZoneInfo(F.FIXTURE_TIMEZONE)
    products = {p["product_id"]: p for p in tables["products"]}
    people = [
        p
        for p in tables["associates"]
        if p["store_id"] == F.HERO_STORE_ID and p["role"] != "district_manager"
    ]
    if len(people) != 8:
        raise ValueError("Historical worked-shift fixture requires eight store employees.")
    sales, attendance = [], []
    for day in REPORT_DATES:
        revenue = sum(
            cents(r["sales_usd"])
            for r in tables["store_traffic"]
            if r["store_id"] == F.HERO_STORE_ID
            and datetime.fromisoformat(str(r["ts_hour"]).replace(" UTC", "+00:00"))
            .astimezone(tz)
            .date()
            .isoformat()
            == day
        )
        units = (
            list(QUANTITIES)
            if day == REPORT_DATES[1]
            else [max(1, round(q * 0.86)) for q in QUANTITIES]
        )
        gross = [cents(products[p]["price_usd"]) * n for p, n in zip(PRODUCTS, units, strict=True)]
        if not 0 < revenue <= sum(gross):
            raise ValueError(
                "Historical sales cannot reconcile to the proposed positive gross sales."
            )
        net = [revenue * g // sum(gross) for g in gross]
        ranking = sorted(
            range(len(gross)), key=lambda i: (-(revenue * gross[i] % sum(gross)), PRODUCTS[i])
        )
        for i in ranking[: revenue - sum(net)]:
            net[i] += 1
        sales.extend(
            dict(
                store_id=F.HERO_STORE_ID,
                business_date=day,
                product_id=p,
                units_sold=n,
                gross_sales_cents=g,
                discount_cents=g - v,
                net_sales_cents=v,
            )
            for p, n, g, v in zip(PRODUCTS, units, gross, net, strict=True)
        )
        shifts = [(9, 8), (9, 8), (10, 7.5), (12, 7), (9, 6), (13.5, 7), (14.5, 6), (13.5, 7)]
        for person, (start, paid) in zip(people, shifts, strict=True):
            clock_in = datetime.fromisoformat(day).replace(tzinfo=tz) + timedelta(hours=start)
            attendance.append(
                dict(
                    store_id=F.HERO_STORE_ID,
                    business_date=day,
                    associate_id=person["associate_id"],
                    clock_in=clock_in.isoformat(),
                    clock_out=(clock_in + timedelta(hours=paid, minutes=30)).isoformat(),
                    unpaid_break_minutes=30,
                    paid_minutes=int(paid * 60),
                )
            )
    result = {"pos_daily_product_sales": sales, "worked_shifts": attendance}
    if {k: len(v) for k, v in result.items()} != REPORT_TABLE_COUNTS:
        raise ValueError("Unexpected historical analytics fixture counts.")
    return result
