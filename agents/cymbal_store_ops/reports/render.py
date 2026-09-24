"""Packaged HTML → A4 PDF. Binary content never enters an LLM response or state."""

from __future__ import annotations

import asyncio
from datetime import date
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATE_VERSION = "end-of-day-v2"
MAX_PDF_BYTES = 2 * 1024 * 1024
_render_lock = asyncio.Semaphore(1)


def render_html(metrics: dict, prose: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
    )
    env.filters["money"] = lambda n: "—" if n is None else f"${n / 100:,.2f}"
    env.filters["longdate"] = lambda s: date.fromisoformat(s).strftime("%A, %B %-d, %Y")
    env.filters["shortdate"] = lambda s: date.fromisoformat(s).strftime("%b %-d")

    def change(current, previous):
        return (
            "—"
            if current is None or previous in (None, 0)
            else f"{(current / previous - 1) * 100:+.1f}%"
        )

    env.filters["change"] = change
    hourly = {
        day: {r["hour"]: r["sales_cents"] for r in metrics["hourly"] if r["business_date"] == day}
        for day in (metrics["comparison_date"], metrics["business_date"])
    }
    maximum = max((r["sales_cents"] for r in metrics["hourly"]), default=0) or 1
    bars = [
        {
            "label": f"{h if h <= 12 else h - 12}{'a' if h < 12 else 'p'}",
            "previous": hourly[metrics["comparison_date"]].get(h, 0) / maximum * 100,
            "current": hourly[metrics["business_date"]].get(h, 0) / maximum * 100,
        }
        for h in sorted(hourly[metrics["business_date"]])
    ]
    return env.get_template("end_of_day.html").render(m=metrics, prose=prose, bars=bars)


def validate_pdf(pdf: bytes) -> None:
    from pypdf import PdfReader

    if not pdf.startswith(b"%PDF-") or len(pdf) > MAX_PDF_BYTES:
        raise ValueError("Invalid or oversized PDF output.")
    pages = PdfReader(BytesIO(pdf)).pages
    if (
        len(pages) != 1
        or abs(float(pages[0].mediabox.width) - 595.28) > 1
        or abs(float(pages[0].mediabox.height) - 841.89) > 1
    ):
        raise ValueError("Report must fit one A4 portrait page.")


async def render_pdf(metrics: dict, prose: dict) -> bytes:
    from playwright.async_api import async_playwright

    html = render_html(metrics, prose)
    if len(html.encode()) > 256_000:
        raise ValueError("Report HTML exceeds the rendering limit.")
    async with _render_lock, asyncio.timeout(45):
        # Fresh browser per export keeps process lifecycle simple and leaks bounded.
        # Rendering happens only on explicit export, never normal chat startup.
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                context = await browser.new_context(java_script_enabled=False)
                await context.route("**/*", lambda route: route.abort())
                page = await context.new_page()
                await page.set_content(html, wait_until="load")
                await page.emulate_media(media="print")
                bounds = await page.evaluate("""() => ({notes: document.querySelector('.notes').getBoundingClientRect().bottom,
                    footer: document.querySelector('footer').getBoundingClientRect().top,
                    overflow: Array.from(document.querySelectorAll('.summary,.notes,.notes p')).some(e => e.scrollWidth > e.clientWidth + 1)})""")
                if bounds["overflow"]:
                    raise ValueError("Report text exceeds its column width.")
                if bounds["notes"] > bounds["footer"] - 8:
                    raise ValueError("Report content overlaps its footer; shorten the narrative.")
                pdf = await page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
                validate_pdf(pdf)
                return pdf
            finally:
                await browser.close()
