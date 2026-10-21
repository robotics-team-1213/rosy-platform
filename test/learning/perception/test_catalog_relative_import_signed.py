"""Actual committed-source signed handoff; physical GPU and host idle are fixtures.

Temporary CODE READY, production signing/Updater/lock/bootstrap/import/store run.
No operational installation, native admission, reader proof or model qualification.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

from test_model_pc_autoupdate import keys, SCRIPT  # noqa: F401
from test_catalog_relative_import import prepared, assert_pending, human_approve, snapshot
from review_app import ReviewStore


ROOT = Path(__file__).resolve().parents[3]
ENTRY = 'learning/curation/perception/edge_capture.py'
IMPORTER = 'learning/curation/perception/review_ingest.py'
CONTROLLER_FILES = ('rosy_model_code.py', 'candidate_signing.py',
    'model_code_layout.py', 'model_code_execution.py', 'model_code_source.py')

# This launcher is outside the payload. Its only observation overrides are
# explicitly scoped GPU health and host idle. Production execute/main and child
# are unmodified; a real inherited work lock surrounds the isolated child.
LAUNCHER = '''import json,pathlib,sys
installed,operation,config_path=sys.argv[1:4]
sys.path.insert(0,installed)
import rosy_model_code as controller
def fixture_idle(*args,**kwargs):
    return None
def fixture_gpu_health(source):
    assert pathlib.Path(source).is_dir()
controller.gpu_busy=fixture_idle
controller.legacy_busy=fixture_idle
config=controller.load_config(config_path)
if operation=='activate':
    repo,commit,private,public=sys.argv[4:]
    updater=controller.Updater(config['root'],'test',public,config['python'],
        busy=fixture_idle,health=fixture_gpu_health,legacy_roots=config['legacy_roots'])
    environment=updater.probe_environment()
    output=pathlib.Path(config['root'])/'inbox'/'1'
    manifest=controller.build(repo,commit,1,environment,output,'test',private,public)
    result=updater.run()
    assert result['result']=='applied',result
    print(json.dumps(dict(manifest=manifest,manifest_sha256=controller.digest(output/'release.json'),
        environment_sha256=environment,source=str((pathlib.Path(config['root'])/'current').resolve()))))
elif operation=='strict':
    pins=json.loads(sys.argv[4])
    raise SystemExit(controller.execute(config,'dataset/edge_capture.py',sys.argv[5:],source_expectation=pins))
elif operation=='cli':
    sys.argv=[str(pathlib.Path(installed)/'rosy_model_code.py'),'--config',config_path,
        'exec','dataset/edge_capture.py',*sys.argv[4:]]
    raise SystemExit(controller.main())
else:
    raise AssertionError('unknown test launcher operation')
'''


def invoke(setup, operation, *args):
    return subprocess.run([sys.executable, '-I', str(setup.launcher), str(setup.installed),
        operation, str(setup.config), *args], cwd=setup.work, capture_output=True, text=True,
        timeout=180, check=False)


@pytest.fixture
def signed_catalog(tmp_path, keys):
    folder, rows = prepared(tmp_path)
    work, legacy, installed, root = (tmp_path / name for name in
                                    ('unrelated-work', 'empty-legacy', 'installed-controller', 'code-root'))
    for path in (work, legacy, installed, root):
        path.mkdir(mode=0o700)
    for name in CONTROLLER_FILES:
        shutil.copyfile(SCRIPT.parent / name, installed / name)
    launcher = tmp_path / 'installed-test-observations.py'
    launcher.write_text(LAUNCHER, encoding='utf-8')
    config = tmp_path / 'model-code.json'
    config.write_text(json.dumps(dict(root=str(root), key_id='test', public_key=str(keys[1]),
        python=sys.executable, work_dir=str(work), legacy_roots=[str(legacy)])), encoding='utf-8')
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    assert len(commit) == 40
    setup = SimpleNamespace(folder=folder, rows=rows, work=work, root=root, installed=installed,
        launcher=launcher, config=config, commit=commit, state=tmp_path / 'review-state')
    result = invoke(setup, 'activate', str(ROOT), commit, str(keys[0]), str(keys[1]))
    assert result.returncode == 0, (result.stdout, result.stderr)
    metadata = json.loads(result.stdout)
    setup.source = Path(metadata['source'])
    setup.manifest = metadata['manifest']
    setup.pins = dict(source_commit=commit, environment_sha256=metadata['environment_sha256'],
                      manifest_sha256=metadata['manifest_sha256'])
    assert setup.manifest['source_commit'] == commit
    assert setup.manifest['environment_sha256'] == setup.pins['environment_sha256']
    archive = root / 'inbox/1/code.tar'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == setup.manifest['archive_sha256']
    with tarfile.open(archive) as payload:
        for relative in (ENTRY, IMPORTER, 'tools/data_paths.py'):
            committed = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{commit}:{relative}'])
            assert payload.extractfile(relative).read() == committed
            assert (setup.source / relative).read_bytes() == committed
            assert (setup.source / relative).stat().st_mode & 0o222 == 0
    # Wrong but valid CWD shadow PNGs expose a discarded catalog anchor.
    import cv2
    import numpy as np
    (work / 'images').mkdir()
    for row in rows:
        (work / row['image']).write_bytes(cv2.imencode('.png', np.zeros((24, 32, 3), np.uint8))[1].tobytes())
    # Signed bootstrap must also exclude ambient unsigned module alternatives.
    (work / 'review_ingest.py').write_text('raise RuntimeError("unsigned importer used")\n')
    setup.store = ReviewStore(setup.state, empty_training=True)
    setup.catalog_raw = (folder / 'verified-inputs.jsonl').read_bytes()
    setup.arguments = ['import', str(folder / 'verified-inputs.jsonl'), '--state', str(setup.state),
                       '--catalog-relative']
    return setup


def receipts(setup):
    return [json.loads(path.read_bytes()) for path in sorted((setup.root / 'jobs').glob('*.json'))]


def test_actual_signed_head_mapped_import_and_ordinary_cli_reimport_preserve_human_history(signed_catalog):
    setup = signed_catalog
    strict = invoke(setup, 'strict', json.dumps(setup.pins), *setup.arguments)
    assert strict.returncode == 0, (strict.stdout, strict.stderr)
    assert_pending(setup.store, setup.folder, setup.rows, setup.catalog_raw)
    strict_receipts = receipts(setup)
    assert len(strict_receipts) == 1
    receipt = strict_receipts[0]
    assert receipt['script'] == 'dataset/edge_capture.py' and receipt['entry'] == ENTRY
    assert receipt['exit_code'] == 0
    assert receipt['source_commit'] == setup.commit
    assert receipt['environment_sha256'] == setup.pins['environment_sha256']
    proof = receipt['source_proof']
    for key, value in setup.pins.items():
        assert proof[key] == value
    assert proof['archive_sha256'] == setup.manifest['archive_sha256']
    assert proof['sequence'] == 1
    human_approve(setup.store)
    before = snapshot(setup.store)
    frame, history = setup.store.get(0), setup.store.history(0)
    ordinary = invoke(setup, 'cli', *setup.arguments)
    assert ordinary.returncode == 0, (ordinary.stdout, ordinary.stderr)
    assert snapshot(setup.store) == before
    assert setup.store.get(0) == frame and setup.store.history(0) == history
    all_receipts = receipts(setup)
    assert len(all_receipts) == 2
    ordinary_receipt = next(row for row in all_receipts if 'source_proof' not in row)
    assert ordinary_receipt['exit_code'] == 0 and ordinary_receipt['entry'] == ENTRY
    assert ordinary_receipt['source_commit'] == setup.commit
    assert (setup.folder / 'verified-inputs.jsonl').read_bytes() == setup.catalog_raw


@pytest.mark.parametrize('fault', ['entry', 'dependency', 'manifest-expectation'])
def test_strict_signed_tampering_refuses_before_import_writes(signed_catalog, fault):
    setup = signed_catalog
    pins = dict(setup.pins)
    if fault == 'manifest-expectation':
        pins['manifest_sha256'] = '0' * 64
    else:
        selected = setup.source / (ENTRY if fault == 'entry' else IMPORTER)
        selected.chmod(0o600)
        selected.write_bytes(selected.read_bytes() + b'\n# temporary installed fixture tampering\n')
        selected.chmod(0o444)
    before = snapshot(setup.store)
    result = invoke(setup, 'strict', json.dumps(pins), *setup.arguments)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert 'ValueError' in result.stderr, result.stderr
    assert not receipts(setup), 'strict source verification must precede job/import execution'
    assert snapshot(setup.store) == before
