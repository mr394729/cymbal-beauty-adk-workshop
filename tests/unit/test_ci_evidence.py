"""Evidence upload is bounded, excludes adjacent build secrets, and cannot alter test status."""
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

from deployment.iam.upload_ci_evidence import allowed, bundle, collect, preserve_exit, upload


def write(root, path, text='evidence'):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def test_allowlist_contains_actual_hidden_adk_results_but_no_browser_or_env(tmp_path):
    raw = 'build/eval_runs/gate.evalset-20260922/cymbal_store_ops/.adk/eval_history/result.evalset_result.json'
    selected = [raw, 'build/eval_runs/gate.evalset-20260922/metrics.csv', 'build/ci-eval.xml', 'build/change-risk.json']
    for path in selected:
        write(tmp_path, path, '{}')
    for path in ['build/cookies.json', 'build/runtime.env', 'build/eval_runs/run/cookies.json',
                 'build/eval_runs/run/other.evalset_result.json', '.env']:
        write(tmp_path, path, 'must not upload')
    data, manifest = bundle(tmp_path, 'eval', 7)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        assert set(archive.getnames()) == {*selected, 'evidence-manifest.json'}
        assert json.load(archive.extractfile('evidence-manifest.json'))['original_exit_code'] == 7
    assert {item['path'] for item in manifest['files']} == set(selected)
    assert not allowed('../build/ci-unit.xml', 'eval')
    assert not allowed('/build/ci-unit.xml', 'eval')
    assert all(not name.startswith('build/eval_runs') for name, _ in collect(tmp_path, 'risk'))


def test_symlink_and_size_limits_fail_closed(tmp_path, monkeypatch):
    outside = write(tmp_path, 'outside-secret', 'secret')
    target = tmp_path / 'build/ci-unit.xml'
    target.parent.mkdir()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='symlink'):
        collect(tmp_path, 'eval')
    target.unlink()
    target.write_text('12345')
    monkeypatch.setattr('deployment.iam.upload_ci_evidence.MAX_FILE_BYTES', 4)
    with pytest.raises(ValueError, match='bounded'):
        collect(tmp_path, 'eval')


@pytest.mark.parametrize('status', [0, 1, 7, 143])
def test_upload_failure_preserves_original_status(status):
    def fail():
        raise RuntimeError('secret-content-never-logged')
    assert preserve_exit(status, fail) == status
    assert preserve_exit(status, lambda: None) == status


@pytest.mark.parametrize('step_id', ['eval-gate', 'change-risk'])
@pytest.mark.parametrize('status', [0, 1, 7])
def test_real_shell_exit_cleanup_keeps_status_even_if_uploader_fails(tmp_path, step_id, status):
    config = yaml.safe_load(Path('cloudbuild/ci.yaml').read_text())
    step = next(step for step in config['steps'] if step['id'] == step_id)
    trap = next(line.strip() for line in step['args'][-1].splitlines() if line.strip().startswith('trap '))
    fake_uv = write(tmp_path, 'uv', '#!/bin/sh\nexit 93\n')
    fake_uv.chmod(0o700)
    result = subprocess.run(['bash', '-c', 'set -euo pipefail\nmkdir -p build\n' + trap.replace('$$', '$') + f'\nexit {status}'],
        cwd=tmp_path, env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'], 'PROJECT_ID': 'test-project', 'BUILD_ID': 'test-build'})
    assert result.returncode == status


def test_cloud_object_is_only_private_ci_build_prefix(tmp_path):
    write(tmp_path, 'build/ci-eval.xml', '<testsuite/>')
    seen = {}
    class Client:
        def bucket(self, name):
            seen['bucket'] = name
            return self
        def blob(self, name):
            seen['object'] = name
            return self
        def upload_from_string(self, data, **kwargs):
            seen.update(kwargs)
            assert data.startswith(b'\x1f\x8b')
    upload('test-project', 'actual-build', tmp_path, 'eval', 1, Client())
    assert seen['object'] == 'ci/actual-build/evidence-eval.tar.gz'
    assert seen['if_generation_match'] == 0
    with pytest.raises(ValueError, match='build identifier'):
        upload('test-project', '../../outside', tmp_path, 'eval', 0, Client())
