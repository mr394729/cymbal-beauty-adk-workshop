"""check_env pre-flight: an expired sign-in is diagnosed as a sign-in problem, never as disabled APIs; deploy-only APIs
warn; the gcloud CLI token is checked on its own and never printed. gcloud and ADC are replaced; nothing leaves the
machine."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from google.auth.exceptions import RefreshError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_env", ROOT / "scripts" / "check_env.py")
ce = importlib.util.module_from_spec(spec)
sys.modules["check_env"] = ce   # dataclasses resolve annotations through the module registry
spec.loader.exec_module(ce)

TOKEN = "ya29.never-print-me"
CLOUD_ROWS = ("project reachable", "api enabled", "model probe")


class Creds:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self._account = error, "you@example.com"

    def refresh(self, request) -> None:
        if self.error:
            raise self.error


@pytest.fixture
def env(monkeypatch):
    for key, value in {"GOOGLE_CLOUD_PROJECT": "unit-test-project", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
                       "GOOGLE_CLOUD_LOCATION": "global", "WORKSHOP_NAMESPACE": "unit", "STORE_OPS_ENV": "dev",
                       "MODEL": "gemini-3.8-flash"}.items():
        monkeypatch.setenv(key, value)
    calls: list[list[str]] = []
    state = {"adc_error": None, "cli_ok": True, "project_ok": True,
             "enabled": ["aiplatform.googleapis.com", "bigquery.googleapis.com"], "model_probed": False}

    def fake_sh(cmd, timeout=60):
        calls.append(cmd)
        if cmd[:3] == ["gcloud", "auth", "print-access-token"]:
            return (0, TOKEN) if state["cli_ok"] else (1, "ERROR: (gcloud.auth.print-access-token) There was a problem "
                                                          "refreshing your current auth tokens: Reauthentication failed.\n"
                                                          "Please run:\n\n  $ gcloud auth login")
        if cmd[:3] == ["gcloud", "config", "get-value"]:
            return 0, "you@example.com"
        if cmd[:3] == ["gcloud", "projects", "describe"]:
            return (0, "123456789") if state["project_ok"] else (1, "ERROR: (gcloud.projects.describe) NOT_FOUND")
        if cmd[:3] == ["gcloud", "services", "list"]:
            return 0, "\n".join(state["enabled"])
        raise AssertionError(f"unexpected command {cmd}")

    def fake_probe(model):
        state["model_probed"] = True
        return ce.Row(f"model probe: {model}", True, "'ok' in 1.0s")

    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (Creds(state["adc_error"]), "unit-test-project"))
    monkeypatch.setattr(ce, "sh", fake_sh)
    monkeypatch.setattr(ce, "model_probe_row", fake_probe)
    return state, calls


def rows_by_name(rows):
    return {r.check: r for r in rows}


def cloud(rows):
    return [r for r in rows if r.check.startswith(CLOUD_ROWS)]


def test_expired_adc_fails_with_the_login_fix_and_stops_the_cloud_checks(env, monkeypatch):
    state, calls = env
    state["adc_error"] = RefreshError("Reauthentication is needed.")
    rows = ce.prereqs()
    adc = rows_by_name(rows)["ADC present"]
    assert adc.status == "FAIL" and adc.fix == "gcloud auth application-default login" and "RefreshError" in adc.detail
    assert cloud(rows) and all(r.status == "SKIP" and r.detail == "not checked: sign in first" for r in cloud(rows))
    assert not any("disabled" in r.detail for r in rows)
    assert not any(c[:2] in (["gcloud", "projects"], ["gcloud", "services"]) for c in calls)
    assert state["model_probed"] is False
    monkeypatch.setattr("sys.argv", ["check_env.py", "--stage", "prereqs"])
    assert ce.main() == 1


def test_expired_gcloud_cli_token_is_its_own_failure_and_the_token_is_never_printed(env):
    state, _ = env
    state["cli_ok"] = False
    rows = ce.prereqs()
    cli = rows_by_name(rows)["gcloud CLI signed in"]
    assert cli.status == "FAIL" and cli.fix == "gcloud auth login" and cli.detail.startswith("ERROR: (gcloud.auth.print-access-token)")
    assert rows_by_name(rows)["ADC present"].status == "PASS"
    assert all(r.status == "SKIP" and "sign in first" in r.detail for r in cloud(rows))
    state["cli_ok"] = True
    assert not any(TOKEN in r.detail for r in ce.prereqs())


def test_deploy_only_apis_warn_and_name_what_deploy_calls(env, monkeypatch):
    state, _ = env
    rows = ce.prereqs()
    deploy = [r for r in rows if r.check.startswith("api enabled (deploy only)")]
    assert [r.check.split(": ")[1] for r in deploy] == ["storage.googleapis.com", "iamcredentials.googleapis.com"]
    assert all(r.status == "WARN" and r.ok and "uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json" in r.detail and r.fix.startswith("gcloud services enable") for r in deploy)
    assert all(rows_by_name(rows)[f"api enabled: {api}"].status == "PASS" for api in ce.REQUIRED_APIS)
    assert state["model_probed"] is True
    assert "2 warning(s)" in ce.summary(rows)
    state["enabled"] += ["storage.googleapis.com", "iamcredentials.googleapis.com"]
    assert all(r.status == "PASS" for r in ce.prereqs() if r.check.startswith("api enabled (deploy only)"))


def test_secret_manager_is_a_deploy_api_only_when_the_env_declares_secrets(tmp_path, monkeypatch):
    envs = tmp_path / "agents" / "cymbal_store_ops" / "config" / "envs"
    envs.mkdir(parents=True)
    (envs / "dev.yaml").write_text("secret_env_vars: {}\n")
    (envs / "prod.yaml").write_text("secret_env_vars:\n  PARTNER_API_KEY: {secret: k, version: '1'}\n")
    monkeypatch.setattr(ce, "ROOT", tmp_path)
    assert ce.SECRET_API not in ce.deploy_apis("dev")
    assert ce.deploy_apis("prod")[-1] == ce.SECRET_API


def test_an_unreachable_project_does_not_read_as_disabled_apis(env):
    state, _ = env
    state["project_ok"] = False
    rows = ce.prereqs()
    assert rows_by_name(rows)["project reachable"].status == "FAIL"
    rest = [r for r in cloud(rows) if r.check != "project reachable"]
    assert rest and all(r.status == "SKIP" and "not reachable" in r.detail for r in rest)
    assert not any("disabled" in r.detail for r in rows)


def test_ready_stops_on_expired_adc_instead_of_blaming_the_data(env, monkeypatch):
    state, _ = env
    state["adc_error"] = RefreshError("Reauthentication is needed.")
    from google.cloud import bigquery

    monkeypatch.setattr(bigquery, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no BigQuery without a sign-in")))
    rows = ce.ready()
    assert [r.status for r in rows] == ["FAIL", "SKIP"] and rows[0].fix == "gcloud auth application-default login"
    assert not any("uv run python data/generate.py && bash data/load.sh --env dev" in r.fix for r in rows)
