"""A release switch keeps the operator's existing service-token file binding."""

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

from test_model_review_release import release, source_tree


@pytest.mark.skipif(os.name == 'nt', reason='Linux managed release symlinks and permissions')
@pytest.mark.parametrize('retained', [False, True], ids=['install', 'reactivate'])
@pytest.mark.parametrize('supported', [False, True], ids=['refuse', 'preserve'])
def test_external_service_token_binding(tmp_path, monkeypatch, capsys, retained, supported):
    root, state = tmp_path / 'releases-root', tmp_path / 'state'
    current = root / 'releases' / 'current-release'
    source_tree(current)
    (root / 'current').symlink_to(current)
    state.mkdir()
    (state / 'reviews.sqlite3').touch()
    token_file = tmp_path / 'operator' / 'edge-service.json'
    token_file.parent.mkdir()
    marker = 'test-only-offline-credential-value'
    token_file.write_text(json.dumps({'tokens': [{'scope': 'service_offline_job', 'token': marker}]}))
    token_file.chmod(0o600)
    service = 'rosy-edge-review.service'
    unit = tmp_path / service
    unit.write_text(f'[Service]\nExecStart={sys.executable} {root / "current" / release.APP} '
                    f'--host 127.0.0.1 --port 8768 --state {state} --service-tokens {token_file}\n')
    before = unit.read_bytes()
    source = root / 'releases' / 'candidate' if retained else tmp_path / 'source'
    source_tree(source)
    if supported:
        (source / release.APP).write_text("parser.add_argument('--service-tokens')")
    calls = []
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(release, 'run_systemctl', lambda *args: calls.append(args))
    monkeypatch.setattr(release, 'check_live', lambda *args: None)
    args = (None if retained else source, 'candidate', root, None if retained else state,
            None if retained else Path(sys.executable), '127.0.0.1', 8768, unit, service)
    if supported:
        selected = release.install(*args)
        assert (root / 'current').resolve() == selected
        command, = (line.removeprefix('ExecStart=') for line in unit.read_text().splitlines()
                    if line.startswith('ExecStart='))
        words = shlex.split(command)
        assert words.count('--service-tokens') == 1
        assert words[words.index('--service-tokens') + 1] == str(token_file)
        assert ('restart', service) in calls
    else:
        with pytest.raises(ValueError, match='service.tokens') as failure:
            release.install(*args)
        assert marker not in str(failure.value)
        assert (root / 'current').resolve() == current
        assert unit.read_bytes() == before
        assert not calls
    output = capsys.readouterr()
    assert marker not in unit.read_text() + output.out + output.err
