import pytest

from agents.cymbal_store_ops import config


@pytest.fixture(autouse=True)
def _clear():
    config.load_env_config.cache_clear()
    yield
    config.load_env_config.cache_clear()


def test_loads_dev_defaults(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    cfg = config.load_env_config("dev")
    assert cfg.project == "p1" and cfg.bigquery.dataset == "cymbal_beauty_unit_dev"
    assert cfg.bigquery.job_labels["ns"] == "unit" and cfg.engine_display_name == "cymbal-store-ops-unit-dev"
    assert not hasattr(cfg.bigquery, "members_dataset")   # one dataset per environment
    assert cfg.model == "gemini-3.8-flash"
    assert cfg.dialect == "BigQuery Standard SQL"


@pytest.mark.parametrize("env_name", ["preprod", "prod"])
def test_other_envs_differ_only_in_config(monkeypatch, env_name):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    cfg = config.load_env_config(env_name)
    assert cfg.bigquery.dataset == f"cymbal_beauty_unit_{env_name}"
    assert cfg.engine_display_name == f"cymbal-store-ops-unit-{env_name}"


def test_missing_project_is_loud(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        config.load_env_config("dev")


def test_unknown_env_is_loud(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    with pytest.raises(RuntimeError, match="Unknown STORE_OPS_ENV"):
        config.load_env_config("staging")


def test_bad_fault_is_loud(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    monkeypatch.setenv("STORE_OPS_FAULT", "explode")
    with pytest.raises(RuntimeError, match="STORE_OPS_FAULT"):
        config.load_env_config("dev")


def test_missing_namespace_is_loud(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    monkeypatch.setenv("WORKSHOP_NAMESPACE", "")
    with pytest.raises(RuntimeError, match="uv run python scripts/namespace.py"):
        config.load_env_config("dev")


@pytest.mark.parametrize("bad", ["A1", "ab", "1abc", "has-dash", "waytoolongname1"])
def test_invalid_namespace_is_loud(monkeypatch, bad):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p1")
    monkeypatch.setenv("WORKSHOP_NAMESPACE", bad)
    with pytest.raises(RuntimeError, match="lowercase"):
        config.load_env_config("dev")
