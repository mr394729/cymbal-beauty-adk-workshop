"""Engine resolution by labels: a fresh pipeline checkout must update the namespace's engine, never duplicate it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _engine(name: str, **labels):
    return SimpleNamespace(api_resource=SimpleNamespace(name=name, labels=labels))


class FakeClient:
    def __init__(self, engines):
        self.agent_engines = SimpleNamespace(list=lambda: list(engines))


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.delenv("AGENT_ENGINE_ID", raising=False)
    from deployment._common import load_config

    c = load_config("dev")
    c.agent_engine.pop("agent_engine_id", None)
    return c


def test_finds_only_this_namespace_and_env(cfg):
    from deployment._common import existing_engine_name

    client = FakeClient([
        _engine("projects/p/locations/us-central1/reasoningEngines/1", app="cymbal-store-ops", ns="someone", env="dev"),
        _engine("projects/p/locations/us-central1/reasoningEngines/2", app="cymbal-store-ops", ns="unit", env="prod"),
        _engine("projects/p/locations/us-central1/reasoningEngines/3", app="cymbal-store-ops", ns="unit", env="dev"),
        _engine("projects/p/locations/us-central1/reasoningEngines/4"),   # created before namespaces: never matched
    ])
    assert existing_engine_name(client, cfg).endswith("/3")


def test_none_means_create_and_resolve_is_loud(cfg, capsys):
    from deployment._common import DeployError, existing_engine_name, resolve_engine_name

    client = FakeClient([])
    assert existing_engine_name(client, cfg) is None
    with pytest.raises(DeployError):
        resolve_engine_name(cfg, client)
    assert "uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json" in capsys.readouterr().err


def test_duplicates_are_refused(cfg, capsys):
    from deployment._common import DeployError, existing_engine_name

    client = FakeClient([_engine(f"e{i}", app="cymbal-store-ops", ns="unit", env="dev") for i in (1, 2)])
    with pytest.raises(DeployError):
        existing_engine_name(client, cfg)
    assert "2 engines are labelled" in capsys.readouterr().err


def test_explicit_id_wins_without_listing(cfg, monkeypatch):
    from deployment._common import existing_engine_name

    monkeypatch.setenv("AGENT_ENGINE_ID", "123")

    class NoList:
        agent_engines = SimpleNamespace(list=lambda: pytest.fail("must not list when an id is set"))

    assert existing_engine_name(NoList(), cfg).endswith("/reasoningEngines/123")


def test_deploy_logs_prompts_and_responses_for_online_evaluation(cfg):
    """Online monitors score the logged conversation: telemetry and message content on, payloads in the agent's own
    bucket, and AdkApp(enable_tracing=True), without which the template strips the prompt from ADK's call_llm spans."""
    from pathlib import Path

    from deployment.deploy import env_vars_for

    env = env_vars_for(cfg)
    assert env["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] == "true"
    assert env["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"
    assert env["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "SPAN_AND_EVENT"
    assert env["OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH"].startswith(f"gs://{cfg.project}-cymbal-artifacts-{cfg.namespace}-")
    root = Path(__file__).resolve().parents[2] / "deployment"
    assert "enable_tracing=True" in (root / "deploy.py").read_text()
