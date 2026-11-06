"""Only an accepted signed code generation may drive the review release."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/model_pc/auto_review_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("auto_review_release", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_new_generation_activates_and_recheck_is_idle(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    (root / "work.lock").touch()
    commit = "a" * 40
    signed = root / "releases" / f"20-{commit}"
    for name in (module.APP, module.WEB / "index.html", module.WEB / "pixels.html",
                 Path("shared/web/shared-assets.json")):
        file = signed / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("signed")
    (signed / "data").symlink_to(tmp_path, target_is_directory=True)
    (root / "current").symlink_to(signed, target_is_directory=True)
    (root / "state.json").write_text(json.dumps({"sequence": 20, "source_commit": commit, "result": "idle"}))
    review = tmp_path / "review"
    seen = []

    def install(source, release, review_root, *_args):
        if source is None:
            return
        assert (source / module.APP).read_text() == "signed"
        assert not (source / "data").exists()
        seen.append(release)
        target = review_root / "releases" / release
        target.mkdir(parents=True)
        review_root.joinpath("current").symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(module, "install", install)
    args = (root, review, tmp_path / "state", tmp_path / "python", "127.0.0.1", 8774, tmp_path / "unit", 19)
    assert module.apply(*args) == f"activated: model-code-20-{commit[:12]}"
    assert module.apply(*args) == f"already active: model-code-20-{commit[:12]}"
    assert seen == [f"model-code-20-{commit[:12]}"]


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_old_or_mismatched_generation_does_not_activate(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    (root / "work.lock").touch()
    state = {"sequence": 19, "source_commit": "a" * 40, "result": "idle"}
    (root / "state.json").write_text(json.dumps(state))
    args = (root, tmp_path / "review", tmp_path / "state", tmp_path / "python",
            "127.0.0.1", 8774, tmp_path / "unit", 19)
    assert module.apply(*args).startswith("waiting")
    state["sequence"] = 20
    (root / "state.json").write_text(json.dumps(state))
    wrong = root / "releases" / ("20-" + "b" * 40)
    wrong.mkdir(parents=True)
    (root / "current").symlink_to(wrong, target_is_directory=True)
    with pytest.raises(ValueError, match="differs"):
        module.apply(*args)


def test_cli_selects_explicit_service(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(module, 'apply', lambda *args: seen.append(args) or 'waiting')
    monkeypatch.setattr(sys, 'argv', ['auto_review_release.py', '--model-code-root', str(tmp_path),
        '--review-root', str(tmp_path), '--state', str(tmp_path), '--python', '/usr/bin/python3',
        '--host', '127.0.0.1', '--minimum-sequence', '29', '--service', 'rosy-edge-review.service'])
    module.main()
    assert seen[0][-1] == 'rosy-edge-review.service'
    assert seen[0][6].name == 'rosy-edge-review.service'


def test_release_update_unit_takes_the_running_review_python_and_host_from_its_env():
    unit = (Path(__file__).resolve().parents[1] / 'deploy/model_pc/rosy-review-release-update.service').read_text(encoding='utf-8')
    start = next(line for line in unit.splitlines() if line.startswith('ExecStart='))
    assert '--python ${REVIEW_PYTHON}' in start and '--host ${REVIEW_HOST}' in start
    assert '.venv/bin/python' not in start  # a fixed venv dropped the account rollout's environment (2026-10-20)


def test_the_learning_center_v12_and_eval_reviews_follow_the_same_accepted_release_before_v13():
    # D-871/D-857: each extra review app has its own root, state, port and service; v13 runs last and alone fails the unit
    unit = (Path(__file__).resolve().parents[1] / 'deploy/model_pc/rosy-review-release-update.service').read_text(encoding='utf-8')
    starts = [line for line in unit.splitlines() if line.startswith('ExecStart=')]
    assert len(starts) == 4
    assert starts[-1].startswith('ExecStart=/usr/bin/python3') and 'review-v13-code' in starts[-1]
    for line, root, port, service in ((starts[0], 'edge-capture/review-code', '8768', 'rosy-edge-review.service'),
                                      (starts[1], 'review-v12-code', '8773', 'rosy-review-v12.service'),
                                      (starts[2], 'review-v13-eval-code', '8775', 'rosy-review-v13-eval.service')):
        assert line.startswith('ExecStart=-/usr/bin/python3') and f'%h/rosy-ml/{root} ' in line
        assert f'--port {port} ' in line and f'--service {service} ' in line
        assert '--python ${REVIEW_PYTHON}' in line and '--minimum-sequence ${MINIMUM_SEQUENCE}' in line


def _manual_review(tmp_path):
    root = tmp_path / 'model'
    root.mkdir()
    (root / 'work.lock').touch()
    commit = 'a' * 40
    signed = root / 'releases' / f'45-{commit}'
    signed.mkdir(parents=True)
    (root / 'current').symlink_to(signed, target_is_directory=True)
    (root / 'state.json').write_text(json.dumps({
        'sequence': 45, 'source_commit': commit, 'result': 'idle'}))
    review = tmp_path / 'review'
    manual = review / 'releases' / 'manual-new'
    manual.mkdir(parents=True)
    (review / 'current').symlink_to(manual, target_is_directory=True)
    (review / 'releases' / f'model-code-45-{commit[:12]}').mkdir()
    return root, review, (root, review, tmp_path / 'state', tmp_path / 'python',
        '127.0.0.1', 8774, tmp_path / 'unit', 44)


def _write_hold(review, service=module.SERVICE):
    marker = review / 'manual-hold.json'
    marker.write_text(json.dumps({'schema': 'rosy.review.manual-hold/1',
        'service': service, 'hold_id': 'b' * 32}))
    marker.chmod(0o600)
    return marker


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX symlinks and flock')
def test_manual_hold_blocks_old_accepted_release_and_other_ui_still_updates(tmp_path, monkeypatch):
    root, review, args = _manual_review(tmp_path)
    _write_hold(review)
    before = (root / 'state.json').read_bytes()
    calls = []
    monkeypatch.setattr(module, 'install', lambda *a: calls.append(a))
    assert module.apply(*args).startswith('manual hold:')
    assert module.apply_locked(*args).startswith('manual hold:')
    assert calls == []
    assert (review / 'current').resolve().name == 'manual-new'
    assert (root / 'state.json').read_bytes() == before

    other = tmp_path / 'other-review'
    other.mkdir()
    (other / 'releases').symlink_to(review / 'releases', target_is_directory=True)
    (other / 'current').symlink_to(review / 'current', target_is_directory=True)
    other_args = (root, other, *args[2:])
    assert module.apply(*other_args).startswith('activated:')
    assert len(calls) == 1 and calls[0][2] == other


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX symlinks and flock')
@pytest.mark.parametrize('damage', ['json', 'symlink', 'public', 'service'])
def test_invalid_manual_hold_never_activates(tmp_path, monkeypatch, damage):
    _, review, args = _manual_review(tmp_path)
    marker = _write_hold(review)
    if damage == 'json':
        marker.write_text('{')
    elif damage == 'symlink':
        destination = review / 'hold-target'
        marker.rename(destination)
        marker.symlink_to(destination)
    elif damage == 'public':
        marker.chmod(0o644)
    else:
        _write_hold(review, 'rosy-edge-review.service')
    calls = []
    monkeypatch.setattr(module, 'install', lambda *a: calls.append(a))
    with pytest.raises((OSError, ValueError)):
        module.apply(*args)
    assert calls == []
    assert (review / 'current').resolve().name == 'manual-new'


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX symlinks and flock')
def test_hold_cli_requires_matching_id_to_resume_automatic_updates(tmp_path, monkeypatch):
    _, review, args = _manual_review(tmp_path)
    installer = sys.modules['install_review_release']

    def cli(*flags):
        monkeypatch.setattr(sys, 'argv', ['install_review_release.py',
            '--root', str(review), '--service', module.SERVICE, *flags])
        installer.main()

    cli('--hold')
    marker = review / 'manual-hold.json'
    metadata = json.loads(marker.read_text())
    assert metadata['schema'] == 'rosy.review.manual-hold/1'
    assert metadata['service'] == module.SERVICE
    hold_id = metadata['hold_id']
    assert len(hold_id) == 32 and int(hold_id, 16) >= 0
    assert marker.stat().st_mode & 0o077 == 0
    cli('--hold')
    assert json.loads(marker.read_text()) == metadata
    with pytest.raises(SystemExit) as refused:
        cli('--unhold', 'wrong-id')
    assert refused.value.code == 1 and marker.exists()
    cli('--unhold', hold_id)
    assert not marker.exists()
    calls = []
    monkeypatch.setattr(module, 'install', lambda *a: calls.append(a))
    assert module.apply(*args).startswith('activated:')
    assert len(calls) == 1


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX symlinks and flock')
def test_failed_manual_install_keeps_hold(tmp_path):
    _, review, args = _manual_review(tmp_path)
    installer = sys.modules['install_review_release']
    with pytest.raises(ValueError, match='existing service unit is missing'):
        installer.install(None, 'manual-next', review, None, None,
            '127.0.0.1', 8774, args[6], hold=True)
    metadata = json.loads((review / 'manual-hold.json').read_text())
    assert metadata['service'] == module.SERVICE
    assert (review / 'current').resolve().name == 'manual-new'


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX symlinks and flock')
def test_manual_hold_waits_for_inflight_automatic_install(tmp_path, monkeypatch):
    _, review, args = _manual_review(tmp_path)
    installer = sys.modules['install_review_release']
    entered, attempted, release, installed = Event(), Event(), Event(), Event()
    real_flock = module.fcntl.flock

    def observed_flock(file, operation):
        manual = current_thread().name == 'manual-hold'
        if manual:
            attempted.set()
        real_flock(file, operation)
        if manual:
            assert installed.is_set(), 'hold acquired before the automatic switch completed'

    def activate(_source, name, root, *_args):
        entered.set()
        assert release.wait(15)
        (root / 'current').unlink()
        (root / 'current').symlink_to(root / 'releases' / name, target_is_directory=True)
        installed.set()

    def hold():
        current_thread().name = 'manual-hold'
        return installer.hold(review, module.SERVICE)

    monkeypatch.setattr(module.fcntl, 'flock', observed_flock)
    monkeypatch.setattr(module, 'install', activate)
    with ThreadPoolExecutor(max_workers=2) as workers:
        automatic = workers.submit(module.apply, *args)
        try:
            assert entered.wait(15)
            manual = workers.submit(hold)
            assert attempted.wait(15), 'hold must use the same review lock as the updater'
        finally:
            release.set()
        assert automatic.result(timeout=15).startswith('activated:')
        hold_id = manual.result(timeout=15)
    assert json.loads((review / 'manual-hold.json').read_text())['hold_id'] == hold_id
    assert (review / 'current').resolve().name == 'model-code-45-aaaaaaaaaaaa'
    assert module.apply(*args).startswith('manual hold:')
