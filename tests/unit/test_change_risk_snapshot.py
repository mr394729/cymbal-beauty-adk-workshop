"""Archive risk review verifies exact source rather than trusting a claimed Git head."""
import hashlib
import json

import pytest

from deployment import change_risk


def test_snapshot_review_verifies_source_and_preserves_risk_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(change_risk, 'ROOT', tmp_path)
    source = tmp_path / 'agents/cymbal_store_ops/plugins.py'
    source.parent.mkdir(parents=True)
    source.write_text('new control\n')
    patch = '+new control\n'
    (tmp_path / 'changes.patch').write_text(patch)
    manifest = {'base': 'actual-base-sha', 'head': 'snapshot:actual-digest',
        'files': [{'path': str(source.relative_to(tmp_path)), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
        'changed_files': [str(source.relative_to(tmp_path))], 'diff_sha256': hashlib.sha256(patch.encode()).hexdigest()}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    base, head, paths, actual = change_risk.snapshot_input(path)
    assert (base, head, actual) == ('actual-base-sha', 'snapshot:actual-digest', patch)
    assert change_risk.classify(paths)[1] == 'high'
    source.write_text('changed after manifest\n')
    with pytest.raises(ValueError, match='digest mismatch'):
        change_risk.snapshot_input(path)
    manifest['files'][0]['path'] = '../outside'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Invalid archive'):
        change_risk.snapshot_input(path)


def test_snapshot_diff_tampering_is_rejected(tmp_path):
    (tmp_path / 'changes.patch').write_text('different')
    manifest = {'files': [], 'diff_sha256': hashlib.sha256(b'original').hexdigest()}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='diff digest mismatch'):
        change_risk.snapshot_input(path)
