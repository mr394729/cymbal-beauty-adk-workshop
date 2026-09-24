"""Real Git DAG checks: PR ancestry and main-push comparison cannot erase changes."""
from types import SimpleNamespace

import pytest

from deployment.iam.prepare_risk_base import choose_base, fetch_baseline, git


def repository(tmp_path):
    git('init', '-b', 'main', cwd=tmp_path)
    git('config', 'user.email', 'unit@example.test', cwd=tmp_path)
    git('config', 'user.name', 'Unit Test', cwd=tmp_path)
    for text in ('base', 'main update'):
        (tmp_path / 'data.txt').write_text(text)
        git('add', '.', cwd=tmp_path)
        git('commit', '-m', text, cwd=tmp_path)
    return git('rev-parse', 'HEAD', cwd=tmp_path)


def test_main_push_uses_parent_even_when_base_branch_equals_head(tmp_path):
    head = repository(tmp_path)
    git('update-ref', 'refs/remotes/risk/base', head, cwd=tmp_path)
    result = choose_base('push', cwd=tmp_path)
    assert result['head'] == head
    assert result['base'] == git('rev-parse', 'HEAD^', cwd=tmp_path)
    assert git('diff', '--name-only', result['base'], result['head'], cwd=tmp_path) == 'data.txt'
    with pytest.raises(ValueError, match='equals HEAD'):
        choose_base('push', cwd=tmp_path, previous_sha=head)


def test_pull_request_uses_shared_ancestor_not_new_base_changes(tmp_path):
    head = repository(tmp_path)
    git('update-ref', 'refs/remotes/risk/base', head, cwd=tmp_path)
    git('checkout', '-b', 'feature', 'HEAD^', cwd=tmp_path)
    (tmp_path / 'feature.txt').write_text('feature')
    git('add', '.', cwd=tmp_path)
    git('commit', '-m', 'feature', cwd=tmp_path)
    result = choose_base('pr', cwd=tmp_path)
    assert result['base'] == git('rev-parse', 'main^', cwd=tmp_path)
    assert git('diff', '--name-only', result['base'], result['head'], cwd=tmp_path) == 'feature.txt'


def test_private_token_never_requested_for_wrong_checkout_origin(tmp_path):
    repository(tmp_path)
    git('remote', 'add', 'origin', 'https://github.com/wrong/repo.git', cwd=tmp_path)
    class Session:
        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {'remoteUri': 'https://github.com/right/repo.git'})
        def post(self, *args, **kwargs):
            pytest.fail('Wrong origin must fail before credentials are requested')
    with pytest.raises(ValueError, match='origin does not match'):
        fetch_baseline('projects/project/locations/us-central1/connections/github/repositories/repo', 'main', Session(), cwd=tmp_path)


def test_read_token_is_ephemeral_and_absent_from_fetch_arguments(tmp_path, monkeypatch):
    from deployment.iam import prepare_risk_base
    repository(tmp_path)
    git('remote', 'add', 'origin', 'https://github.com/right/repo.git', cwd=tmp_path)
    calls = []
    actual_git = prepare_risk_base.git
    def intercept(*args, **kwargs):
        if args[0] == 'fetch':
            assert 'private-read-token' not in repr(args)
            env = kwargs['env']
            assert env['CYMBAL_BUILD_READ_TOKEN'] == 'private-read-token'
            assert env['GIT_TRACE_CURL'] == '0'
            from pathlib import Path
            path = Path(env['GIT_ASKPASS'])
            assert path.is_file()
            assert 'private-read-token' not in path.read_text()
            calls.append(path)
            return ''
        return actual_git(*args, **kwargs)
    monkeypatch.setattr(prepare_risk_base, 'git', intercept)
    class Session:
        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {'remoteUri': 'https://github.com/right/repo.git'})
        def post(self, url, **kwargs):
            assert url.endswith(':accessReadToken')
            return SimpleNamespace(status_code=200, json=lambda: {'token': 'private-read-token'})
    fetch_baseline('projects/project/locations/us-central1/connections/github/repositories/repo', 'main', Session(), cwd=tmp_path)
    assert len(calls) == 1 and not calls[0].exists()
    assert 'private-read-token' not in (tmp_path / '.git/config').read_text()
