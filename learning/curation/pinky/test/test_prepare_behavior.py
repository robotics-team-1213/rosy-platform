"""Behavior input preparation runs raw verification and publishes nothing on failure."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/curation/pinky'))
import prepare_behavior


def test_verification_failure_never_publishes_input(tmp_path, monkeypatch):
    def rejected(root):
        raise ValueError('raw camera/command mismatch')
    monkeypatch.setattr(prepare_behavior, 'verify', rejected)
    output = tmp_path / 'inputs'
    with pytest.raises(ValueError, match='raw'):
        prepare_behavior.prepare(tmp_path / 'recording', output)
    assert not output.exists()


def test_preparation_never_uses_an_existing_report_instead_of_verification(tmp_path, monkeypatch):
    source = tmp_path / 'recording'; source.mkdir()
    (source / 'raw-verification.json').write_text('{"verdict":"pass"}')
    calls = []
    def rejected(root):
        calls.append(root)
        raise ValueError('raw verification still required')
    monkeypatch.setattr(prepare_behavior, 'verify', rejected)
    with pytest.raises(ValueError, match='raw verification'):
        prepare_behavior.prepare(source, tmp_path / 'inputs')
    assert len(calls) == 1 and not (tmp_path / 'inputs').exists()
