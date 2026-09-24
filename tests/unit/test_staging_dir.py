"""Two people deploying at once in one project must not write to the same staging folder."""
from types import SimpleNamespace

from deployment._common import staging_dir


def cfg(ns: str, env: str = "dev") -> SimpleNamespace:
    return SimpleNamespace(namespace=ns, env=env)


def test_the_staging_folder_carries_the_namespace_and_the_environment():
    assert staging_dir(cfg("u1a2b3c")) == "agent_engine/u1a2b3c/store-ops-dev"
    assert staging_dir(cfg("u1a2b3c", "prod")) == "agent_engine/u1a2b3c/store-ops-prod"


def test_two_namespaces_never_share_a_folder_and_a_quickstart_has_its_own():
    assert staging_dir(cfg("u1a2b3c")) != staging_dir(cfg("u9f8e7d"))
    assert staging_dir(cfg("u1a2b3c"), "03-form-completion-agent") == "agent_engine/u1a2b3c/03-form-completion-agent-dev"


def test_the_deploy_config_asks_for_that_folder(monkeypatch):
    import deployment.deploy as deploy

    monkeypatch.setattr(deploy, "agent_engine_settings", lambda c: {
        "display_name": "x", "traffic": "manual", "identity": "service_account", "gateway": ""})
    monkeypatch.setattr(deploy, "staging_bucket", lambda c: "gs://bucket")
    monkeypatch.setattr(deploy, "env_vars_for", lambda c: {})
    monkeypatch.setattr(deploy, "service_account_email", lambda c: "sa@example.iam.gserviceaccount.com")
    release = {"adk_version": "2.9.0", "requirements": [], "git_sha": "abcdef1234567890", "data_version": "2026.09.18-1"}
    config = deploy.build_config(cfg("u1a2b3c", "preprod"), release)
    assert config["gcs_dir_name"] == "agent_engine/u1a2b3c/store-ops-preprod"


def test_the_release_sha_comes_from_the_pipeline_when_there_is_no_git(monkeypatch):
    """A Cloud Build step runs in an image without git; the trigger passes COMMIT_SHA instead. Before this, the
    release manifest and the engine's git-sha label read 'uncommitted' for every pipeline deploy."""
    from deployment import _common as c

    monkeypatch.setattr(c, "_git", lambda *a: None)
    monkeypatch.setenv("COMMIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert c.git_sha() == "0123456789abcdef0123456789abcdef01234567" and c.git_dirty() is False
    monkeypatch.delenv("COMMIT_SHA")
    assert c.git_sha() == "uncommitted"
    monkeypatch.setattr(c, "_git", lambda *a: "feedface\n" if a[0] == "rev-parse" else " M x.py\n")
    monkeypatch.setenv("COMMIT_SHA", "ignored-when-a-checkout-exists")
    assert c.git_sha() == "feedface" and c.git_dirty() is True
