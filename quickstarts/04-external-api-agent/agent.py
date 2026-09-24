"""Quickstart 04 — external API agent.

Two ways to reach systems outside the agent: an `OpenAPIToolset` generated from an OpenAPI document (the mock
order management API for buy-online-pick-up-in-store orders, API key from the ORDERS_API_KEY environment variable —
a Secret Manager reference on Agent Runtime), and a plain function tool over a keyless public API (Open-Meteo
weather for the store's city). `ReflectAndRetryToolPlugin` lets the model correct a bad call up to twice instead of
giving up on the first tool error.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", module=r"google\.adk.*")

import httpx  # noqa: E402
from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.plugins import ReflectAndRetryToolPlugin  # noqa: E402
from google.adk.tools.openapi_tool import OpenAPIToolset  # noqa: E402
from google.adk.tools.openapi_tool.auth.auth_helpers import token_to_scheme_credential  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.models import workshop_model  # noqa: E402

SPEC = Path(__file__).with_name("openapi.yaml")
INSTRUCTION = """You help Cymbal Beauty store associates with buy-online-pick-up-in-store (BOPIS) orders. The store
is Cymbal Beauty Naperville (S-014) unless the associate names another store id.
- One order: call get_order with its id (like BO-000651). Several orders: call list_orders with the store_id and,
  when asked, a status (pending | picked | ready | collected | cancelled).
- Report status and items with quantities exactly as returned. Give times in the store's local time with AM/PM and
  the day, for example 9:30 AM Saturday. For a ready order also give hold_until: after that time the order is
  cancelled and its items go back to stock.
- Weather questions: call get_weather with the store's city and say in one sentence what it means for pick-up
  traffic (rain, snow or heat tends to move guests to pick-up orders).
- Answer in at most three sentences. If the API returns an error, say what failed.
Never invent order ids, times, quantities or temperatures."""


def get_weather(city: str) -> dict:
    """Current temperature (°C) and humidity (%) for a city, from the public Open-Meteo API (no key)."""
    geo = httpx.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1}, timeout=10).json()
    if not geo.get("results"):
        return {"status": "ERROR", "error_details": f"no coordinates found for {city!r}"}
    place = geo["results"][0]
    wx = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10,
                   params={"latitude": place["latitude"], "longitude": place["longitude"],
                           "current": "temperature_2m,relative_humidity_2m,precipitation"}).json()["current"]
    return {"status": "SUCCESS", "rows": [{"city": place["name"], "temperature_c": wx["temperature_2m"],
                                          "humidity_pct": wx["relative_humidity_2m"], "precipitation_mm": wx["precipitation"]}]}


def orders_toolset() -> OpenAPIToolset:
    key = os.environ.get("ORDERS_API_KEY")
    if not key:
        raise RuntimeError("ORDERS_API_KEY is not set (locally in .env; on Agent Runtime a Secret Manager reference)")
    scheme, credential = token_to_scheme_credential("apikey", "header", "X-API-Key", key)
    spec = SPEC.read_text().replace("http://localhost:8010", os.environ.get("ORDERS_API_URL", "http://localhost:8010"))
    return OpenAPIToolset(spec_str=spec, spec_str_type="yaml", auth_scheme=scheme, auth_credential=credential)


def make_root_agent() -> LlmAgent:
    cfg = load_env_config()
    return LlmAgent(
        name="external_api_agent",
        model=workshop_model(cfg),
        description="BOPIS order status and hold times from the order management API, plus weather for the store's city.",
        instruction=INSTRUCTION,
        tools=[orders_toolset(), get_weather],
    )


def create_app() -> App:
    return App(name="external_api_agent", root_agent=make_root_agent(),
               plugins=[ReflectAndRetryToolPlugin(max_retries=2)])


app = create_app()
root_agent = app.root_agent
