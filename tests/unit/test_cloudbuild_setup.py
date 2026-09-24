"""Namespace, release settings and approval boundaries in Cloud Build plans."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from deployment.iam.cloudbuild_runtime import NAMES, record
from deployment.iam.cloudbuild_setup import plan, read_runtime_settings, verify_definition


def test_dev_plan_uses_exact_repo_namespace_and_distinct_evaluation_scope():
    spec = plan("my-project", "owner", "workshop", "demo", connection="team", eval_namespace="checks")
    ci, deploy = spec["triggers"]
    assert spec["remote_uri"] == "https://github.com/owner/workshop.git"
    assert "/connections/team/" in spec["repository"]
    assert ci["substitutions"] == {"_NAMESPACE": "demo", "_EVAL_NAMESPACE": "checks",
                                    "_REPO_RESOURCE": spec["repository"], "_RISK_EVENT": "pr"}
    assert ci["repositoryEventConfig"]["pullRequest"]["commentControl"] == "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    assert ci["disabled"] and deploy["disabled"]
    assert deploy["substitutions"]["_ENV"] == "dev"


def test_promotions_are_manual_with_approval_even_when_enabled():
    triggers = plan("my-project", "owner", "workshop", "demo", enable=True, scope="ladder")["triggers"]
    assert len(triggers) == 7
    for trigger in triggers[2:]:
        assert trigger["eventType"] == "MANUAL"
        assert trigger["approvalConfig"]["approvalRequired"] is True
        assert "repositoryEventConfig" not in trigger
        assert trigger["sourceToBuild"]["ref"] == "refs/heads/main"
    assert all(not t["disabled"] for t in triggers)


def test_verification_detects_approval_loss_and_unintended_push_event():
    expected = plan("my-project", "owner", "workshop", "demo", scope="ladder")["triggers"][2]
    actual = copy.deepcopy(expected)
    actual["id"] = "server-generated"
    assert not verify_definition(expected, actual)
    actual["approvalConfig"]["approvalRequired"] = False
    assert "approvalConfig" in verify_definition(expected, actual)
    actual["repositoryEventConfig"] = {"push": {"branch": ".*"}}
    assert "repositoryEventConfig" in verify_definition(expected, actual)


def test_runtime_settings_are_data_not_shell_and_never_secret_values(tmp_path):
    settings = tmp_path / "settings.env"
    settings.write_text("export MEMORY_BANK_ENGINE=projects/example/locations/us-central1/reasoningEngines/123\n")
    values = read_runtime_settings(settings)
    assert values["MEMORY_BANK_ENGINE"].endswith("/123")
    settings.write_text("export CYMBAL_MCP_SCOPE_KEY=secret-value\n")
    with pytest.raises(ValueError, match="never credential"):
        read_runtime_settings(settings)
    settings.write_text("export MEMORY_BANK_ENGINE=x; touch /tmp/never-run\n")
    with pytest.raises(ValueError, match="plain KEY"):
        read_runtime_settings(settings)


def test_partial_mcp_or_mutable_secret_ref_fails_before_plan(tmp_path):
    settings = tmp_path / "settings.env"
    settings.write_text("CYMBAL_MCP_URL=https://example/mcp\n")
    with pytest.raises(ValueError, match="four MCP"):
        read_runtime_settings(settings)
    settings.write_text("\n".join(["CYMBAL_MCP_URL=https://example/mcp", "CYMBAL_MCP_AUDIENCE=https://example",
                                  "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT=runtime@example.iam.gserviceaccount.com",
                                  "CYMBAL_MCP_SCOPE_SECRET=scope:latest"]))
    with pytest.raises(ValueError, match="pinned"):
        read_runtime_settings(settings)


def test_pipeline_optional_settings_and_browser_installation_are_recorded(monkeypatch, tmp_path):
    for key in NAMES:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WORKSHOP_NAMESPACE", "demo")
    monkeypatch.setenv("STORE_OPS_ENV", "dev")
    monkeypatch.setenv("MEMORY_BANK_ENGINE", "projects/example/locations/us-central1/reasoningEngines/123")
    monkeypatch.setenv("COMMIT_SHA", "a" * 40)
    got = record(tmp_path / "features.json")
    assert got["runtime_settings"]["MEMORY_BANK_ENGINE"].endswith("/123")
    assert got["secret_values_resolved"] is False
    assert Path(got["browser_installation_script"]).is_file()
    deploy = yaml.safe_load(Path("cloudbuild/deploy.yaml").read_text())
    for step in deploy["steps"][:2]:
        assert "STORE_OPS_ENV=${_ENV}" in step["env"]
        assert "CYMBAL_MCP_SCOPE_SECRET=${_CYMBAL_MCP_SCOPE_SECRET}" in step["env"]
    assert "build/runtime-features.json" in deploy["artifacts"]["objects"]["paths"]
    ci = yaml.safe_load(Path("cloudbuild/ci.yaml").read_text())
    gate = next(s for s in ci["steps"] if s["id"] == "eval-gate")
    assert "SOP_DATA_STORE=" in gate["env"] and "CYMBAL_MCP_URL=" in gate["env"]


def test_updates_preserve_existing_optional_service_substitutions(monkeypatch, tmp_path):
    from deployment.iam import cloudbuild_setup

    spec = plan('my-project', 'owner', 'workshop', 'demo')
    current = copy.deepcopy(spec['triggers'])
    for index, trigger in enumerate(current):
        trigger['id'] = str(index)
        trigger['disabled'] = False
    current[1]['substitutions']['_SOP_DATA_STORE'] = 'projects/my-project/locations/global/collections/default_collection/dataStores/policy'
    imports = []

    def gcloud(*args):
        if args[:3] == ('builds', 'connections', 'describe'):
            return {'installationState': {'stage': 'COMPLETE'}}
        if args[:3] == ('builds', 'repositories', 'list'):
            return [{'name': spec['repository'], 'remoteUri': spec['remote_uri']}]
        if args[:3] in {('builds', 'connections', 'add-iam-policy-binding'), ('builds', 'connections', 'get-iam-policy')}:
            return {'bindings': [{'role': 'roles/cloudbuild.readTokenAccessor',
                                  'members': ['serviceAccount:cicd-evaluator@my-project.iam.gserviceaccount.com']}]}
        if args[:2] == ('projects', 'describe'):
            return {'projectNumber': '123'}
        if args[:3] == ('builds', 'triggers', 'list'):
            return current
        if args[:3] == ('builds', 'triggers', 'import'):
            import json
            path = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--source='))
            definition = json.loads(Path(path).read_text())
            imports.append(definition)
            current[int(definition['id'])] = definition
            return definition
        raise AssertionError(args)

    monkeypatch.setattr(cloudbuild_setup, 'gcloud', gcloud)
    cloudbuild_setup.configure(spec, tmp_path, apply=True)
    assert len(imports) == 2
    assert imports[1]['substitutions']['_SOP_DATA_STORE'].endswith('/policy')
    assert all(t['disabled'] for t in imports)


def test_dedicated_connection_rejects_other_repositories_before_iam(monkeypatch, tmp_path):
    from deployment.iam import cloudbuild_setup
    spec = plan('my-project', 'owner', 'workshop', 'demo')
    wanted = {'name': spec['repository'], 'remoteUri': spec['remote_uri']}
    cloudbuild_setup.validate_dedicated_repository([], spec)
    cloudbuild_setup.validate_dedicated_repository([wanted], spec)
    def no_mutations(*args):
        pytest.fail('Other repository must fail before any IAM call')
    monkeypatch.setattr(cloudbuild_setup, 'gcloud', no_mutations)
    for repositories in ([wanted, {'name': 'other', 'remoteUri': 'https://github.com/owner/other.git'}],
                         [{'name': 'other', 'remoteUri': spec['remote_uri']}], []):
        with pytest.raises(RuntimeError):
            cloudbuild_setup.ensure_connection_read_access(spec, repositories, tmp_path, apply=True)


def test_apply_grants_only_read_token_role_on_dedicated_connection(monkeypatch, tmp_path):
    from deployment.iam import cloudbuild_setup
    spec = plan('my-project', 'owner', 'workshop', 'demo')
    wanted = {'name': spec['repository'], 'remoteUri': spec['remote_uri']}
    calls = []
    member = 'serviceAccount:cicd-evaluator@my-project.iam.gserviceaccount.com'
    def gcloud(*args):
        calls.append(args)
        return {'bindings': [{'role': 'roles/cloudbuild.readTokenAccessor', 'members': [member]}]}
    monkeypatch.setattr(cloudbuild_setup, 'gcloud', gcloud)
    result = cloudbuild_setup.ensure_connection_read_access(spec, [wanted], tmp_path, apply=True)
    assert calls[0][:4] == ('builds', 'connections', 'add-iam-policy-binding', spec['connection'])
    assert '--role=roles/cloudbuild.readTokenAccessor' in calls[0]
    assert '--member=' + member in calls[0]
    assert result['scope'] == 'connection' and result['verified']
    calls.clear()
    cloudbuild_setup.ensure_connection_read_access(spec, [wanted], tmp_path, apply=False)
    assert len(calls) == 1 and calls[0][2] == 'get-iam-policy'


def test_pending_oauth_never_grants_read_token_access(monkeypatch, tmp_path):
    from deployment.iam import cloudbuild_setup
    spec = plan('my-project', 'owner', 'workshop', 'demo')
    calls = []
    def gcloud(*args):
        calls.append(args)
        assert args[:3] == ('builds', 'connections', 'describe')
        return {'installationState': {'stage': 'PENDING_USER_OAUTH', 'actionUri': 'https://console.cloud.google.com/'}}
    monkeypatch.setattr(cloudbuild_setup, 'gcloud', gcloud)
    with pytest.raises(RuntimeError, match='PENDING_USER_OAUTH'):
        cloudbuild_setup.configure(spec, tmp_path, apply=True)
    assert len(calls) == 1
