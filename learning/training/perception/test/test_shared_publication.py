"""POSIX shared-store publication must survive restrictive source modes and umask."""
import json
import os
from pathlib import Path
import stat
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE/'training')]
import store
import handover
from train_job import publish_ready
from export_cell import write_manifest

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX service group permissions')


def shared_root(path):
    path.mkdir()
    path.chmod(0o2770)
    return path


def accessible(folder):
    for path in [folder, *folder.rglob('*')]:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o2770 if path.is_dir() else 0o640), (path, oct(mode))
        assert path.stat().st_gid == folder.stat().st_gid


def test_dataset_private_source_publishes_for_shared_reader(tmp_path):
    source = tmp_path/'source'
    source.mkdir(mode=0o700)
    (source/'sample').write_bytes(b'private data')
    (source/'sample').chmod(0o600)
    root = shared_root(tmp_path/'store')
    previous = os.umask(0o077)
    try:
        dest, digest = store.Store(root).put_dataset(source, 'lanes')
    finally:
        os.umask(previous)
    accessible(dest)
    assert stat.S_IMODE(dest.parent.stat().st_mode) == 0o2770
    assert stat.S_IMODE(dest.parent.parent.stat().st_mode) == 0o2770
    assert store.content_sha(dest) == digest == store.content_sha(source)
    assert stat.S_IMODE(source.stat().st_mode) == 0o700
    assert stat.S_IMODE((source/'sample').stat().st_mode) == 0o600


@pytest.mark.parametrize('publisher', ['handover', 'gpu-job'])
def test_ready_under_private_umask_is_group_readable(tmp_path, publisher):
    source = tmp_path/'artifact'
    source.mkdir()
    weights = source/'model.onnx'
    weights.write_bytes(b'test artifact, not deployable')
    doc = write_manifest(source, onnx_path=weights, classes=[('floor', 'background'), ('line', 'lane_marking')],
                         color='rgb', scale=1/255, mean=[0,0,0], std=[1,1,1],
                         dataset_repo='store:fixture', dataset_revision='a'*64,
                         camera_profile_revision='provisional', trainer='test')
    (source/'intake_report.json').write_text(json.dumps({
        'verdict':'pass', 'model_revision':doc['model_revision'],
        'files':[{'name':f['name'], 'sha256':f['sha256']} for f in doc['files']]}))
    for path in source.iterdir():
        path.chmod(0o600)
    root = shared_root(tmp_path/'store')
    previous = os.umask(0o077)
    try:
        target = (handover.package(source, root/'models/inbox') if publisher == 'handover'
                  else publish_ready(source, root, 'job'))
    finally:
        os.umask(previous)
    accessible(target)
    assert store.Store(root).inbox_ready(target)
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o2770


def test_shared_dataset_refuses_source_symlink_without_touching_target(tmp_path):
    outside = tmp_path/'outside'
    outside.write_bytes(b'private outside bytes')
    outside.chmod(0o600)
    source = tmp_path/'source'
    source.mkdir()
    (source/'link').symlink_to(outside)
    root = shared_root(tmp_path/'store')
    with pytest.raises(store.StoreError, match='symlink'):
        store.Store(root).put_dataset(source, 'links')
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600
    assert outside.read_bytes() == b'private outside bytes'


def test_fixed_eval_build_survives_private_umask(tmp_path):
    pytest.importorskip('cv2')
    import build
    import labels
    from test_d379_catalog_and_store import _labels_dir
    source = _labels_dir(tmp_path, '20261001T090000Z_e', [(labels.FLOOR, False)] * 3)
    root = shared_root(tmp_path/'store')
    previous = os.umask(0o077)
    try:
        _, final = build.build_auto_dataset([source], root, 'fixed', eval_set=True)
    finally:
        os.umask(previous)
    accessible(final)
    assert stat.S_IMODE(final.parent.stat().st_mode) == 0o2770


def test_publish_directory_refuses_symlink_ancestor(tmp_path):
    real = tmp_path/'real'
    real.mkdir()
    root = shared_root(real/'store')
    alias = tmp_path/'alias'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(store.StoreError, match='symlink'):
        store.publication_directory(alias/'store/new')
    assert not (root/'new').exists()


def test_job_partial_symlink_cannot_overwrite_outside(tmp_path):
    from test_training_job import model
    source = tmp_path/'artifact'
    doc = model(source)
    root = shared_root(tmp_path/'store')
    target = root/'models/inbox'/(doc['model_revision']+'__job')
    target.mkdir(parents=True)
    outside = tmp_path/'outside'
    outside.write_bytes(b'preserve outside bytes')
    (target/'model.onnx.part').symlink_to(outside)
    with pytest.raises((store.StoreError, ValueError), match='symlink'):
        publish_ready(source, root, 'job')
    assert outside.read_bytes() == b'preserve outside bytes'
    assert not (target/'READY').exists()


def test_job_resume_repairs_ready_permission_after_interruption(tmp_path, monkeypatch):
    from test_training_job import model
    source = tmp_path/'artifact'
    model(source)
    root = shared_root(tmp_path/'store')
    real_chmod = Path.chmod
    def interrupted(path, mode, **kwargs):
        if path.name == 'READY':
            raise OSError('injected stop before READY chmod')
        return real_chmod(path, mode, **kwargs)
    previous = os.umask(0o077)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'chmod', interrupted)
            with pytest.raises(OSError, match='injected stop'):
                publish_ready(source, root, 'job')
        target = publish_ready(source, root, 'job')
    finally:
        os.umask(previous)
    accessible(target)
    assert store.Store(root).inbox_ready(target)
