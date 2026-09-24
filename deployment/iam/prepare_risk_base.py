"""Fetch a private repository baseline with a short-lived Cloud Build read token.

No token is stored in Git configuration, command arguments, source files or logs.
A missing history/authentication boundary fails closed rather than reviewing HEAD
against itself. This is for repository triggers; verified archive reviews do not
need a repository token.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def git(*args, cwd=None, env=None, input_text=None):
    result = subprocess.run(['git', *args], cwd=cwd, env=env, input=input_text,
                            text=True, capture_output=True)
    if result.returncode:
        # Do not relay transport stderr: it can include credential-bearing URLs.
        raise RuntimeError('Git baseline operation failed; verify repository authorization and available history.')
    return result.stdout.strip()


def choose_base(kind, *, cwd=None, previous_sha=''):
    head = git('rev-parse', 'HEAD', cwd=cwd)
    if kind == 'pr':
        base = git('merge-base', 'HEAD', 'refs/remotes/risk/base', cwd=cwd)
    elif kind == 'push':
        if previous_sha:
            if not re.fullmatch(r'[0-9a-f]{40}', previous_sha):
                raise ValueError('Previous commit must be an exact SHA')
            base = git('rev-parse', previous_sha + '^{commit}', cwd=cwd)
        else:
            parents = git('rev-list', '--parents', '-n', '1', 'HEAD', cwd=cwd).split()
            if len(parents) < 2:
                raise ValueError('Push baseline is unavailable; supply the previous commit and fetch its history.')
            base = parents[1]
    else:
        raise ValueError('Risk event must be pr or push')
    if base == head:
        raise ValueError('Risk baseline equals HEAD; refusing an empty comparison')
    return {'base': base, 'head': head, 'event': kind,
            'baseline_kind': 'merge_base' if kind == 'pr' else 'previous_push' if previous_sha else 'first_parent'}


def fetch_baseline(repository, base_ref, session, *, cwd=None):
    if not re.fullmatch(r'projects/[\w-]+/locations/[\w-]+/connections/[\w-]+/repositories/[\w-]+', repository):
        raise ValueError('An exact Cloud Build repository resource is required')
    git('check-ref-format', 'refs/heads/' + base_ref, cwd=cwd)
    endpoint = 'https://cloudbuild.googleapis.com/v2/' + repository
    response = session.get(endpoint, timeout=30)
    if response.status_code != 200:
        raise RuntimeError('Cannot read the configured Cloud Build repository')
    uri = response.json().get('remoteUri', '')
    if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', uri):
        raise ValueError('Only a credential-free configured GitHub HTTPS repository is supported')
    origin = git('remote', 'get-url', 'origin', cwd=cwd)
    if origin.removesuffix('.git') != uri.removesuffix('.git'):
        raise ValueError('Checkout origin does not match the authenticated repository')
    response = session.post(endpoint + ':accessReadToken', json={}, timeout=30)
    if response.status_code != 200 or not response.json().get('token'):
        raise RuntimeError('Cannot obtain a Cloud Build read token; complete connection OAuth and scoped IAM first')
    token = response.json()['token']
    with tempfile.TemporaryDirectory(prefix='risk-git-') as directory:
        askpass = Path(directory) / 'askpass.sh'
        askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) printf "%s\\n" x-access-token;; *) printf "%s\\n" "$CYMBAL_BUILD_READ_TOKEN";; esac\n')
        askpass.chmod(0o700)
        env = {**os.environ, 'GIT_ASKPASS': str(askpass), 'GIT_TERMINAL_PROMPT': '0',
               'CYMBAL_BUILD_READ_TOKEN': token, 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_TRACE': '0', 'GIT_TRACE_CURL': '0', 'GIT_CURL_VERBOSE': '0',
               'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'credential.helper', 'GIT_CONFIG_VALUE_0': ''}
        git('fetch', '--no-tags', '--depth=200', uri,
            f'+refs/heads/{base_ref}:refs/remotes/risk/base', cwd=cwd, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--base-ref', default='main')
    parser.add_argument('--event', required=True, choices=['pr', 'push'])
    parser.add_argument('--previous-sha', default='')
    parser.add_argument('--out', type=Path, default=Path('build/risk-base.json'))
    args = parser.parse_args()
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    with AuthorizedSession(credentials) as session:
        fetch_baseline(args.repository, args.base_ref, session)
    result = choose_base(args.event, previous_sha=args.previous_sha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
