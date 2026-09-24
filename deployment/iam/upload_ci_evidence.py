"""Persist allowlisted CI evidence before a failed build skips artifact upload."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

MAX_FILES = 100
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
FIXED = {'build/ci-unit.xml', 'build/ci-eval.xml', 'build/change-risk.json',
         'build/change-risk.md', 'build/change-risk.exit', 'build/risk-base.json'}
RUN_FILE = re.compile(r'build/eval_runs/[A-Za-z0-9_.-]+/(?:metrics\.csv|cymbal_store_ops/\.adk/eval_history/[A-Za-z0-9_.-]+\.evalset_result\.json)\Z')


def allowed(relative: str, phase: str) -> bool:
    return relative in FIXED or phase == 'eval' and bool(RUN_FILE.fullmatch(relative))


def collect(root: Path, phase: str) -> list[tuple[str, bytes]]:
    if phase not in {'eval', 'risk'}:
        raise ValueError('Unknown evidence phase')
    root = root.resolve(strict=True)
    build = root / 'build'
    if build.is_symlink():
        raise ValueError('Evidence build directory must not be a symlink')
    candidates = [root / path for path in FIXED]
    if phase == 'eval' and (build / 'eval_runs').exists():
        candidates.extend((build / 'eval_runs').rglob('*'))
    records = []
    total = 0
    for path in sorted(set(candidates)):
        relative = path.relative_to(root).as_posix()
        # Fail on any symlink encountered in the evidence tree, even if it is not selected.
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root and root in parent.parents):
            raise ValueError('Evidence symlink rejected')
        if not allowed(relative, phase) or not path.exists() or not path.is_file():
            continue
        if root not in path.resolve(strict=True).parents:
            raise ValueError('Evidence escaped the workspace')
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES or len(records) >= MAX_FILES:
            raise ValueError('Evidence exceeds its bounded upload size')
        with path.open("rb") as handle:
            content = handle.read(size + 1)
        if len(content) != size:
            raise ValueError('Evidence changed during capture')
        records.append((relative, content))
        total += size
    return records


def bundle(root: Path, phase: str, exit_code: int) -> tuple[bytes, dict]:
    records = collect(root, phase)
    manifest = {'phase': phase, 'original_exit_code': exit_code,
                'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in records]}
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, content in [*records, ('evidence-manifest.json', json.dumps(manifest, indent=2).encode())]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), 0o600, 0
            archive.addfile(info, io.BytesIO(content))
    return data.getvalue(), manifest


def upload(project: str, build_id: str, root: Path, phase: str, exit_code: int, client=None) -> dict:
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project):
        raise ValueError('Invalid project')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,80}', build_id):
        raise ValueError('Invalid build identifier')
    data, manifest = bundle(root, phase, exit_code)
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=project)
    bucket = project + '-cymbal-store-ops-staging'
    object_name = f'ci/{build_id}/evidence-{phase}.tar.gz'
    client.bucket(bucket).blob(object_name).upload_from_string(
        data, content_type='application/gzip', if_generation_match=0, timeout=60)
    result = {'uri': f'gs://{bucket}/{object_name}', 'file_count': len(manifest['files']),
              'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'original_exit_code': exit_code}
    print(json.dumps(result), flush=True)
    return result


def preserve_exit(exit_code: int, action) -> int:
    """Evidence failure must never conceal or replace the original test result."""
    try:
        action()
    except Exception as exc:
        # No arbitrary provider response/headers or file contents in logs.
        print(f'CI evidence upload failed ({type(exc).__name__}); original exit status remains {exit_code}.', flush=True)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--build-id', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--phase', required=True, choices=['eval', 'risk'])
    parser.add_argument('--exit-code', type=int, required=True, choices=range(256))
    args = parser.parse_args()
    return preserve_exit(args.exit_code, lambda: upload(args.project, args.build_id, args.root, args.phase, args.exit_code))


if __name__ == '__main__':
    raise SystemExit(main())
