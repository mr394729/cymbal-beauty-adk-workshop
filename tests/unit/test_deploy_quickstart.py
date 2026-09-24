"""Quickstarts deploy under an importable package name (eight of twelve failed to start on the engine before)."""
from __future__ import annotations

import subprocess
import sys


def test_staged_quickstart_pickles_by_its_engine_name(tmp_path, monkeypatch):
    from deployment import deploy_quickstart as dq

    monkeypatch.setattr(dq, "STAGING", tmp_path / "qs_staging")
    assert dq.package_name("03-form-completion-agent") == "qs_03_form_completion_agent"
    staging, pkg = dq.stage("03-form-completion-agent")
    assert (staging / pkg / "agent.py").exists() and (staging / "agents" / "cymbal_store_ops" / "agent.py").exists()
    assert not (staging / pkg / "tests").exists()
    # A fresh interpreter with only the staging dir on its path: the pickle must reference qs_..., never the folder name.
    code = (
        "import sys, cloudpickle, importlib; sys.path.insert(0, sys.argv[1]); m = importlib.import_module(sys.argv[2] + '.agent');"
        " b = cloudpickle.dumps(m.create_app()); print(sys.argv[2].encode() in b, b'03-form-completion-agent.' in b)"
    )
    out = subprocess.run([sys.executable, "-c", code, str(staging), pkg], capture_output=True, text=True,
                         env={**dict(__import__('os').environ), "WORKSHOP_NAMESPACE": "unit", "GOOGLE_CLOUD_PROJECT": "unit-test-project"})
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip() == "True False"


def test_mcp_quickstart_ships_its_server():
    from deployment import deploy_quickstart as dq

    staging, pkg = dq.stage("08-mcp-tools-agent")
    assert (staging / pkg / "cymbal_mcp_server.py").exists()


def test_the_developer_ui_copy_has_importable_names_and_no_agents_folder(tmp_path):
    """adk web lists 05-data-analyst-agent but refuses every message to it (404 Invalid agent name, ADK 2.9, seen in
    a browser): the UI runs a staged copy named qs_05_data_analyst_agent, without the agents package it does not need."""
    from deployment import deploy_quickstart as dq
    root, pkg = dq.stage("05-data-analyst-agent", tmp_path / "ui", with_agents=False)
    assert root == tmp_path / "ui" and pkg == "qs_05_data_analyst_agent"
    assert (root / pkg / "agent.py").exists() and not (root / "agents").exists() and not (root / pkg / "tests").exists()
    assert pkg.isidentifier()
