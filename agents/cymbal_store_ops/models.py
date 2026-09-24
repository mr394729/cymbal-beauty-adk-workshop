"""The one Gemini client every agent in this repository uses.

Two things it fixes, both of which only show up away from a laptop:

- **Location.** Gemini 3.x is served from the `global` Vertex location. Agent Runtime sets
  GOOGLE_CLOUD_LOCATION to its own region, so an agent built with a bare model string (`model="gemini-3.8-flash"`)
  works locally and returns 404 once deployed. The location is pinned on the client instead.
- **Shared quota.** In a workshop, twenty people share one project's requests-per-minute. A 429 is retried with
  exponential backoff (logged by the google-genai client), a bounded number of times; after that the error
  reaches the caller unchanged. A request that hangs for 90 seconds is abandoned and retried the same way. That is
  a retry of the same call, not a fallback to something else.
"""
from __future__ import annotations

from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client, types

from agents.cymbal_store_ops.config import EnvConfig, load_env_config

RETRY = types.HttpRetryOptions(attempts=6, initial_delay=2.0, max_delay=40.0, exp_base=2.0, jitter=1.0,
                               http_status_codes=[429, 500, 503, 504])
REQUEST_TIMEOUT_MS = 90_000   # a request that hangs is abandoned and retried (timeouts are transient to the client)


class VertexGemini(Gemini):
    """Gemini with the Vertex location pinned on the client (default `global`)."""

    location: str = "global"

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, location=self.location,
                      http_options=types.HttpOptions(retry_options=self.retry_options, timeout=REQUEST_TIMEOUT_MS))


def workshop_model(cfg: EnvConfig | None = None) -> VertexGemini:
    """A fresh model object for the configured model id, location and retry policy."""
    cfg = cfg or load_env_config()
    return VertexGemini(model=cfg.model, location=cfg.model_location, retry_options=RETRY)


LEVELS = {"low": types.ThinkingLevel.LOW, "medium": types.ThinkingLevel.MEDIUM, "high": types.ThinkingLevel.HIGH}


def thinking(cfg: EnvConfig | None = None, *, level: str | None = None) -> types.GenerateContentConfig | None:
    """How hard the model deliberates before answering, from `thinking_level` in config/envs/<env>.yaml.

    `none` uses the model default. The same environment setting is used by the root, specialists and
    briefing workflow so quality and latency can be evaluated for a consistent configuration.
    """
    cfg = cfg or load_env_config()
    name = (level or cfg.thinking_level or "none").strip().lower()
    if name in ("none", "", "default"):
        return None
    if name not in LEVELS:
        raise ValueError(f"thinking_level must be one of {sorted(LEVELS)} or 'none', got {name!r}")
    return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=LEVELS[name]))
