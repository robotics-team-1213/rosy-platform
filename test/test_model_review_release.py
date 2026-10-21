"""The Model PC code switch must never replace review state or strand its service."""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/model_pc/install_review_release.py"
SPEC = importlib.util.spec_from_file_location("install_review_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_current_checkout_satisfies_review_source_inventory():
    root = SCRIPT.parents[2]
    assert not [name for name in release.SPLIT_REQUIRED if not (root / name).is_file()]


def source_tree(path):
    for name in (release.APP, release.WEB / "index.html", release.WEB / "pixels.html",
                 Path("shared/web/shared-assets.json")):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name.as_posix(), encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_install_preserves_state_and_failed_update_restores_service(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source_tree(source)
    state = tmp_path / "state"
    state.mkdir()
    database = state / "reviews.sqlite3"
    database.write_bytes(b"existing-human-decisions")
    root = tmp_path / "releases-root"
    unit = tmp_path / "rosy-review-v13.service"
    unit.write_bytes(b"original service\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(release, "run_systemctl", lambda *args: None)
    monkeypatch.setattr(release, "check_live", lambda *args: None)

    first = release.install(source, "first", root, state, Path(sys.executable),
                            "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == first
    assert database.read_bytes() == b"existing-human-decisions"
    assert json.loads((first / "REVIEW_RELEASE.json").read_text())["source_sha256"]
    assert b"current/learning/curation/perception" in unit.read_bytes()
    assert str(Path(sys.executable)).encode() in unit.read_bytes()
    assert (root / "rosy-review-v13.service.before-managed").read_bytes() == b"original service\n"

    second_source = tmp_path / "second-source"
    shutil.copytree(source, second_source)
    (second_source / release.WEB / "index.html").write_text("new UI", encoding="utf-8")
    working_unit = unit.read_bytes()

    def fail_live(*args):
        raise RuntimeError("HTTP check failed")

    monkeypatch.setattr(release, "check_live", fail_live)
    with pytest.raises(RuntimeError, match="HTTP check failed"):
        release.install(second_source, "second", root, state, Path(sys.executable),
                        "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == first
    assert unit.read_bytes() == working_unit
    assert database.read_bytes() == b"existing-human-decisions"


def test_refuses_state_inside_release_source(tmp_path):
    source = tmp_path / "source"
    source_tree(source)
    with pytest.raises(ValueError, match="separate"):
        release.check_source(source, tmp_path / "root", source / "state")


@pytest.mark.skipif(os.name == 'nt', reason='Linux retained release symlinks')
def test_retained_release_control_flag_matches_its_cli(tmp_path, monkeypatch):
    root=tmp_path/'root'; state=tmp_path/'state'; state.mkdir()
    (state/'learning-control.json').write_text('{}')
    (state/'review-ai.json').write_text('{}')
    (state/'omx-center.json').write_text('{}')
    old=root/'releases/old'; new=root/'releases/new'
    source_tree(old); source_tree(new)
    (new/release.APP).write_text("parser.add_argument('--learning-control'); parser.add_argument('--decisions-port'); parser.add_argument('--review-ai-config'); parser.add_argument('--omx-center-config')")
    (root/'current').symlink_to(new)
    unit=tmp_path/'unit'
    unit.write_text(release.unit_contents(root/'current',state,Path('/usr/bin/python3'),'127.0.0.1',8774))
    monkeypatch.setattr(release,'run_systemctl',lambda *args:None)
    monkeypatch.setattr(release,'check_live',lambda *args:None)
    release.install(None,'old',root,None,None,'127.0.0.1',8774,unit)
    assert '--learning-control' not in unit.read_text()
    assert '--decisions-port' not in unit.read_text()
    assert '--review-ai-config' not in unit.read_text()
    assert '--omx-center-config' not in unit.read_text()
    release.install(None,'new',root,None,None,'127.0.0.1',8774,unit)
    assert f'--learning-control {state}/learning-control.json' in unit.read_text()
    assert '--decisions-port 18774' in unit.read_text()
    assert f'--review-ai-config {state}/review-ai.json' in unit.read_text()
    assert f'--omx-center-config {state}/omx-center.json' in unit.read_text()


@pytest.mark.skipif(os.name == 'nt', reason='Linux retained release symlinks')
@pytest.mark.parametrize('prior_release', [False, True])
@pytest.mark.parametrize('supports_center', [False, True])
def test_new_release_uses_target_cli_for_center_binding(tmp_path, monkeypatch, prior_release, supports_center):
    source = tmp_path/'source'
    source_tree(source)
    (source/release.APP).write_text("parser.add_argument('--omx-center-config')" if supports_center else 'pass')
    root = tmp_path/'root'
    root.mkdir()
    state = tmp_path/'state'
    state.mkdir()
    (state/'reviews.sqlite3').touch()
    (state/'omx-center.json').write_text('{}')
    if prior_release:
        old = root/'releases/old'
        source_tree(old)
        (old/release.APP).write_text('pass' if supports_center else "parser.add_argument('--omx-center-config')")
        (root/'current').symlink_to(old)
    unit = tmp_path/'review.service'
    unit.write_text('[Service]\nExecStart=/existing/review\n')
    monkeypatch.setattr(release, 'run_systemctl', lambda *args: None)
    monkeypatch.setattr(release, 'check_live', lambda *args: None)
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: None)
    release.install(source, 'new', root, state, Path(sys.executable), '127.0.0.1', 8774, unit)
    assert ('--omx-center-config' in unit.read_text()) is supports_center
    assert str(root/'current'/release.APP) in unit.read_text()
    assert str(source/release.APP) not in unit.read_text()


def test_split_source_requires_drive_closure_and_hashes_it(tmp_path):
    source = tmp_path / "source"
    source_tree(source)
    helper = source / "middleware/perception/control/_source_layout.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("pass\n")
    with pytest.raises(ValueError, match="missing"):
        release.check_source(source, tmp_path / "root", tmp_path / "state")
    for name in release.SPLIT_REQUIRED:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source\n")
    release.check_source(source, tmp_path / "root", tmp_path / "state")
    before = release.digest_tree(source)
    (source / "middleware/drive/motion_limits/command_gate.py").write_bytes(b"changed\n")
    assert release.digest_tree(source) != before


@pytest.mark.skipif(os.name == "nt", reason="Linux managed review release symlinks")
def test_retained_legacy_release_reactivation_roundtrip_preserves_code_state_and_receipts(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source_tree(source)
    (source / release.APP).write_text("parser.add_argument('--decisions-port')", encoding='utf-8')
    state = tmp_path / "state"
    state.mkdir()
    database = state / "reviews.sqlite3"
    database.write_bytes(b"persistent human decisions")
    root = tmp_path / "root"
    unit = tmp_path / release.SERVICE
    unit.write_bytes(b"existing service\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(release, "run_systemctl", lambda *a: None)
    monkeypatch.setattr(release, "check_live", lambda *a: None)
    canonical = release.install(source, "canonical", root, state, Path(sys.executable),
                                "127.0.0.1", 8774, unit)
    # Only managed source fields may change: even exact holder prefixes in the
    # interpreter, state argument, other env tokens and unrelated unit text stay.
    interpreter = str(root / "current/tools/perception/python")
    state_argument = str(root / "current/learning/curation/perception-state")
    unrelated = str(tmp_path / (str(root / "current/tools/perception").lstrip("/")) / "other")
    text = unit.read_text().replace(str(Path(sys.executable)), interpreter).replace(str(state), state_argument)
    text += f"Environment=OTHER={unrelated}\nDescription={root / 'current/tools/perception'}\n"
    text = text.replace("Environment=PYTHONPATH=", f"Environment=PYTHONPATH={unrelated}:")
    unit.write_text(text)
    canonical_unit = unit.read_bytes()
    legacy = root / "releases" / "retained"
    old_app = legacy / release.LEGACY_APP
    old_app.parent.mkdir(parents=True)
    old_app.write_bytes(b"unchanged retained review implementation\n")
    (legacy / "REVIEW_RELEASE.json").write_bytes(b'{"source_sha256":"retained-original-digest"}\n')
    before = {file.relative_to(legacy): file.read_bytes() for file in legacy.rglob("*") if file.is_file()}
    release.install(None, "retained", root, None, None, "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == legacy
    assert f"WorkingDirectory={root / 'current' / release.LEGACY_APP.parent}\n" in unit.read_text()
    assert f"{root / 'current' / release.LEGACY_APP} --state {state_argument}" in unit.read_text()
    assert f"ExecStart={interpreter} " in unit.read_text()
    assert f"Environment=OTHER={unrelated}\nDescription={root / 'current/tools/perception'}\n" in unit.read_text()
    release.install(None, "canonical", root, None, None, "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == canonical
    assert unit.read_bytes() == canonical_unit
    assert {file.relative_to(legacy): file.read_bytes() for file in legacy.rglob("*") if file.is_file()} == before
    assert database.read_bytes() == b"persistent human decisions"


def test_generated_unit_uses_exact_canonical_runtime_holders(tmp_path):
    current = tmp_path / "current"
    text = release.unit_contents(current, tmp_path / "state", Path("/usr/bin/python3"), "127.0.0.1", 8774)
    path_line = next(line for line in text.splitlines() if line.startswith("Environment=PYTHONPATH="))
    paths = path_line.partition("=")[2].partition("=")[2].split(":")
    assert paths == [str(current / relative) for relative in (
        "middleware/perception", "contracts/foundation", "tools/perception",
        "learning/registry/perception", "learning/curation/perception", "learning/training/perception",
    )]
    assert len(paths) == len(set(paths))

@pytest.mark.parametrize("missing", [
    "middleware/perception/localization/loc_assist.py",
    "middleware/perception/graph_health/watch.py",
    "middleware/perception/snapshots/capture_trigger.py",
])
def test_functional_holder_cannot_be_omitted_from_review_source(tmp_path, missing):
    assert missing in release.SPLIT_REQUIRED
    source = tmp_path / "source"
    source_tree(source)
    for name in ("middleware/perception/control/_source_layout.py", *release.SPLIT_REQUIRED):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source\n")
    (source / missing).unlink()
    with pytest.raises(ValueError, match="missing"):
        release.check_source(source, tmp_path / "root", tmp_path / "state")

def test_generated_unit_can_opt_in_to_private_owner_controls(tmp_path):
    state = tmp_path / 'state'; state.mkdir()
    (state / 'learning-control.json').write_text('{}')
    (state / 'review-ai.json').write_text('{}')
    text = release.unit_contents(tmp_path / 'current', state, Path('/usr/bin/python3'), '127.0.0.1', 8774)
    assert f'--learning-control {state / "learning-control.json"}' in text
    assert f'--review-ai-config {state / "review-ai.json"}' in text


def test_collaboration_unit_is_loopback_and_has_no_unprotected_decisions_port(tmp_path):
    state = tmp_path / 'state'; state.mkdir()
    (state / 'learning-collaboration.json').write_text('{}')
    text = release.unit_contents(tmp_path / 'current', state, Path('/usr/bin/python3'), '127.0.0.1', 8774)
    assert f'--collaboration {state / "learning-collaboration.json"}' in text
    assert '--decisions-port' not in text
    with pytest.raises(ValueError, match='loopback'):
        release.unit_contents(tmp_path / 'current', state, Path('/usr/bin/python3'), '100.100.1.2', 8774)


@pytest.mark.skipif(os.name == 'nt', reason='Linux managed release symlinks')
@pytest.mark.parametrize('supports_center', [False, True])
def test_collaboration_survives_update_and_retained_roundtrip(tmp_path, monkeypatch, supports_center):
    source = tmp_path / 'source'; source_tree(source)
    cli = "parser.add_argument('--collaboration')"
    if supports_center:
        cli += "; parser.add_argument('--omx-center-config')"
    (source / release.APP).write_text(cli)
    state = tmp_path / 'state'; state.mkdir()
    (state / 'reviews.sqlite3').write_bytes(b'human decisions')
    (state / 'learning-collaboration.json').write_text('{}')
    (state / 'omx-center.json').write_text('{}')
    root = tmp_path / 'root'; unit = tmp_path / 'rosy-edge-review.service'
    unit.write_text('original unit')
    calls = []
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(release, 'run_systemctl', lambda *a: calls.append(a))
    monkeypatch.setattr(release, 'check_live', lambda *a: None)
    service = 'rosy-edge-review.service'
    for name in ('first', 'second'):
        release.install(source, name, root, state, Path(sys.executable), '127.0.0.1', 8768, unit, service)
    text = unit.read_text()
    release.install(None, 'first', root, None, None, '127.0.0.1', 8768, unit, service)
    assert unit.read_text() == text
    assert '--collaboration' in text and '--decisions-port' not in text
    assert ('--omx-center-config' in text) is supports_center
    assert ('restart', service) in calls
    assert (root / (service + '.before-managed')).read_text() == 'original unit'
    old = root / 'releases/old'; source_tree(old)
    with pytest.raises(ValueError, match='collaboration'):
        release.install(None, 'old', root, None, None, '127.0.0.1', 8768, unit, service)
    assert (root / 'current').resolve().name == 'first'
    assert (state / 'reviews.sqlite3').read_bytes() == b'human decisions'


@pytest.mark.parametrize('service', ['../other.service', 'bad name.service', 'bad;name.service', '--other.service', 'other'])
def test_service_name_rejects_unsafe_names(service):
    with pytest.raises(ValueError, match='service'):
        release.validate_service(service)


def test_collaboration_health_requires_denial_options_and_accounts(tmp_path, monkeypatch):
    import io
    import urllib.error
    from types import SimpleNamespace
    seen = []
    public_workspace = False
    def open_url(url, timeout):
        seen.append(url)
        path = url.split(':8774')[-1]
        if path == '/api/workspace' and not public_workspace:
            raise urllib.error.HTTPError(url, 401, 'login required', {}, io.BytesIO(b'{}'))
        payload = (b'{"enabled":true,"rosy_account":true,"project_id":"alpha"}' if path.endswith('options')
                   else b'{}' if path == '/api/workspace' else b'accounts page')
        response = io.BytesIO(payload)
        response.status = 200
        return response
    monkeypatch.setattr(release.urllib.request, 'build_opener', lambda *a: SimpleNamespace(open=open_url))
    monkeypatch.setattr(release, 'run_systemctl', lambda *a: None)
    monkeypatch.setattr(release.time, 'sleep', lambda *a: None)
    release.check_live('127.0.0.1', 8774, 'rosy-edge-review.service', {'project_id': 'alpha', 'account_client_file': '/private/client.json'})
    assert [url.split(':8774')[-1] for url in seen] == ['/api/workspace', '/api/accounts/options', '/accounts']
    with pytest.raises(RuntimeError):
        release.check_live('127.0.0.1', 8774, 'rosy-edge-review.service', {'project_id': 'wrong'})
    public_workspace = True
    with pytest.raises(RuntimeError):
        release.check_live('127.0.0.1', 8774, 'rosy-edge-review.service', {'project_id': 'alpha', 'account_client_file': '/private/client.json'})


def test_bound_central_account_refuses_source_without_account_bridge(tmp_path):
    app = tmp_path / 'review_app.py'
    app.write_text("parser.add_argument('--collaboration')")
    binding = tmp_path / 'learning-collaboration.json'
    binding.write_text('{"account_client_file":"/private/client.json"}')
    with pytest.raises(ValueError, match='central Account'):
        release.check_collaboration(app, binding, '127.0.0.1')
    (tmp_path / 'learning_rosy_accounts.py').write_text('bridge')
    assert release.check_collaboration(app, binding, '127.0.0.1')['account_client_file'] == '/private/client.json'
