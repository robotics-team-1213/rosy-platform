"""Portable prepared catalogs retain exact originals and human review authority."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

import pixel_label_job
import review_ingest
import review_masks
from review_app import ReviewStore


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_catalog(folder, rows):
    path = folder / 'verified-inputs.jsonl'
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows), encoding='utf-8')
    return path


def prepared(tmp_path):
    """Real codec and production preparer; no claimed custody or human labels."""
    video = tmp_path / 'legacy-camera-part01.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 5, (32, 24))
    assert writer.isOpened(), 'actual MP4 codec is required'
    for value in (30, 120, 210):
        writer.write(np.full((24, 32, 3), value, np.uint8))
    writer.release()
    folder = tmp_path / 'prepared'
    assert pixel_label_job.prepare_sources({'sources': [dict(video=str(video),
        sha256=sha(video.read_bytes()), frames=[0, 2], capture_group='camera-group',
        source_session='legacy-camera-session')]}, folder) == 2
    rows = [json.loads(line) for line in (folder / 'verified-inputs.jsonl').read_text().splitlines()]
    moved = tmp_path / 'moved-prepared'
    folder.rename(moved)
    return moved, rows


def snapshot(store):
    """All logical tables plus full importer-owned inventory and bytes."""
    with store.connect() as db:
        names = sorted(row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        tables = {name: sorted((tuple(row) for row in db.execute('SELECT * FROM "' + name + '"')),
                              key=repr) for name in names}
    files = {p.relative_to(store.state).as_posix(): p.read_bytes()
             for p in store.state.rglob('*') if p.is_file() and not p.name.startswith('reviews.sqlite3')}
    dirs = sorted(p.relative_to(store.state).as_posix() for p in store.state.rglob('*') if p.is_dir())
    return tables, files, dirs


def import_relative(store, folder, **kwargs):
    return review_ingest.import_frames(store, dict(path=str(folder), catalog_relative=True, **kwargs))


def assert_pending(store, folder, rows, catalog_raw):
    assert review_masks.classes(store)['sha256'] == sha((folder / 'classes.yaml').read_bytes())
    sources = []
    for index, row in enumerate(rows):
        frame = store.get(index)
        source = frame['source']
        assert frame['status'] == 'pending'
        assert frame['review']['review_status'] == 'pending_human'
        assert frame['review']['complete_frame_review'] is False
        assert source['video'] == str(folder / row['source_video'])
        assert Path(source['video']).is_absolute() and Path(source['video']).is_file()
        assert source['source_session'] == source['source_session_declared'] == row['source_session']
        assert source['capture_group'] == row['capture_group']
        assert source['source_video_sha256'] == row['source_video_sha256']
        assert source['video_frame'] == row['video_frame']
        assert source['original_source_path'] == row['image']
        assert source['original_video_verified'] is False
        assert source['import_catalog_sha256'] == sha(catalog_raw)
        assert source['timestamp_basis'] is source['video_time_s'] is None
        assert source.get('device_id') is source.get('capture_time_utc') is None
        assert not {'reader_verified', 'training_admission', 'approval'} & source.keys()
        assert store.image(index).read_bytes() == (folder / row['image']).read_bytes()
        mask = review_masks.get(store, index)
        assert mask['status'] == 'pending' and mask['approval'] is None
        assert mask['complete'] == mask['background'] == 0
        assert np.all(review_masks.pixels(store, mask) == 255)
        sources.append(dict(source, frame=index))
    assert len({source['capture_group'] for source in sources}) == 1
    assert len({source['source_video_sha256'] for source in sources}) == 1
    with store.connect() as db:
        assert [r[0] for r in db.execute('SELECT identity FROM frame_keys ORDER BY frame')] == [
            f"video:{r['source_video_sha256']}:{r['video_frame']}" for r in rows]
        assert db.execute('SELECT COUNT(*) FROM pixel_events').fetchone()[0] == 0
    assert (folder / 'verified-inputs.jsonl').read_bytes() == catalog_raw


def human_approve(store):
    current = review_masks.get(store, 0)
    filled = review_masks.update(store, 0, dict(version=current['version'], action='fill', label=0),
                                 ValueError, actor='test-human')
    return review_masks.update(store, 0, dict(version=filled['version'], action='approve',
        complete_frame_review=True, background_reviewed=True), ValueError, actor='test-human')


def test_moved_catalog_ignores_valid_wrong_cwd_shadow_and_preserves_human_history(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    raw = (folder / 'verified-inputs.jsonl').read_bytes()
    work = tmp_path / 'unrelated-work'
    (work / 'images').mkdir(parents=True)
    for row in rows:
        (work / row['image']).write_bytes(cv2.imencode('.png', np.zeros((24, 32, 3), np.uint8))[1].tobytes())
    monkeypatch.chdir(work)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    assert import_relative(store, folder)['added'] == 2
    assert_pending(store, folder, rows, raw)
    approved = human_approve(store)
    before = snapshot(store)
    old_frame, old_history = store.get(0), store.history(0)
    assert import_relative(store, folder)['added'] == 0
    assert snapshot(store) == before
    assert store.get(0) == old_frame and store.history(0) == old_history
    assert review_masks.get(store, 0) == approved


@pytest.mark.parametrize('flag', [None, 0, 1, 'true', [], {}])
def test_catalog_relative_requires_exact_boolean_before_selected_input_io(tmp_path, monkeypatch, flag):
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    def forbidden(*args, **kwargs):
        pytest.fail('non-bool flag reached selected input content')
    monkeypatch.setattr(review_ingest, 'bounded', forbidden)
    with pytest.raises(ValueError, match='bool'):
        review_ingest.import_frames(store, dict(path=str(tmp_path / 'absent'), catalog_relative=flag))
    assert snapshot(store) == before


@pytest.mark.parametrize('flag', ['omitted', False])
def test_unflagged_cwd_import_and_old_approved_source_are_not_migrated(tmp_path, monkeypatch, flag):
    folder, rows = prepared(tmp_path)
    monkeypatch.chdir(folder)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    body = {'path': str(folder)}
    if flag != 'omitted':
        body['catalog_relative'] = flag
    assert review_ingest.import_frames(store, body)['added'] == 2
    assert store.get(0)['source']['video'] == rows[0]['source_video']
    human_approve(store)
    before = snapshot(store)
    monkeypatch.chdir(tmp_path)
    assert import_relative(store, folder)['added'] == 0
    assert snapshot(store) == before
    assert store.get(0)['source']['video'] == rows[0]['source_video']


UNSAFE = ['', '.', '..', '../outside.png', 'images/../outside.png', '/outside.png',
          'C:/outside.png', 'C:outside.png', '//server/share.png', r'images\outside.png']


@pytest.mark.parametrize('field', ['image', 'source_video'])
@pytest.mark.parametrize('value', UNSAFE)
def test_later_unsafe_reference_has_no_store_effects(tmp_path, monkeypatch, field, value):
    folder, rows = prepared(tmp_path)
    rows[-1][field] = value
    write_catalog(folder, rows)
    monkeypatch.chdir(folder)  # all preceding images are valid even for a broken CWD implementation
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    with pytest.raises(ValueError, match='relative|portable|path|reference'):
        import_relative(store, folder)
    assert snapshot(store) == before


@pytest.mark.parametrize('fault,match', [('suffix', 'PNG|png'), ('sha', 'hash'),
    ('dimensions', 'dimensions'), ('png-content', 'PNG|png')])
def test_later_image_error_preflights_every_row_without_filesystem_effects(tmp_path, monkeypatch, fault, match):
    folder, rows = prepared(tmp_path)
    row = rows[-1]
    if fault in ('suffix', 'png-content'):
        pixels = np.full((24, 32, 3), 90, np.uint8)
        raw = cv2.imencode('.jpg', pixels)[1].tobytes()
        path = folder / row['image']
        if fault == 'suffix':
            row['image'] = str(Path(row['image']).with_suffix('.jpg'))
            path = folder / row['image']
        path.write_bytes(raw)
        row['image_sha256'] = sha(raw)
        assert cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (24, 32)
    elif fault == 'sha':
        row['image_sha256'] = '0' * 64
    else:
        row['width'] += 1
    write_catalog(folder, rows)
    monkeypatch.chdir(folder)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    with pytest.raises(ValueError, match=match):
        import_relative(store, folder)
    assert snapshot(store) == before
    if fault == 'png-content':
        # Correct SHA/dimensions and a real JPEG decode remain allowed without the opt-in.
        assert review_ingest.import_frames(store, {'path': str(folder)})['added'] == 2


@pytest.mark.parametrize('fault', ['mcap', 'indexed-mask', 'zip-mask', 'objects'])
def test_unsupported_later_mode_is_rejected_before_prover_draft_or_image_io(tmp_path, monkeypatch, fault):
    folder, rows = prepared(tmp_path)
    if fault == 'mcap':
        rows[-1]['source_kind'] = 'mcap'
    elif fault == 'objects':
        rows[-1]['objects'] = [{'label': None, 'bbox_xyxy': [0, 0, 10, 10],
                                'review_status': 'pending_human'}]
    elif fault == 'indexed-mask':
        rows[-1]['mask'] = dict(indexed_png='draft.png', sha256='1' * 64, classes_sha256='2' * 64)
    else:
        rows[-1]['mask'] = dict(zip='draft.zip', entry='draft.png', sha256='1' * 64)
    write_catalog(folder, rows)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported mode reached prover/class inference/image/ZIP')
    monkeypatch.setattr(review_ingest, 'prove_frames', forbidden)
    monkeypatch.setattr(review_ingest.build, 'load_classes', forbidden)
    monkeypatch.setattr(review_ingest, 'image', forbidden)
    monkeypatch.setattr(review_ingest.zipfile, 'ZipFile', forbidden)
    with pytest.raises(ValueError, match='catalog.relative|unsupported|draft.free'):
        import_relative(store, folder)
    assert snapshot(store) == before


@pytest.mark.parametrize('mode', ['indexed-mask', 'zip-mask', 'objects'])
def test_otherwise_valid_draft_and_object_modes_keep_unflagged_control(tmp_path, monkeypatch, mode):
    import zipfile
    folder, rows = prepared(tmp_path)
    row = rows[-1]
    if mode == 'objects':
        row['objects'] = [{'label': None, 'bbox_xyxy': [0, 0, 10, 10]}]
    elif mode == 'indexed-mask':
        raw = review_masks.encode(np.full((24, 32), 255, np.uint8))
        (folder / 'draft.png').write_bytes(raw)
        row['mask'] = dict(indexed_png='draft.png', sha256=sha(raw),
                           classes_sha256=sha((folder / 'classes.yaml').read_bytes()))
    else:
        raw = cv2.imencode('.png', np.full((24, 32, 3), 90, np.uint8))[1].tobytes()
        archive = folder / 'drafts.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('labelmap.txt', 'background:90,90,90::\n')
            output.writestr('mask.png', raw)
        row['mask'] = dict(zip=str(archive), entry='mask.png', sha256=sha(raw))
    write_catalog(folder, rows)
    monkeypatch.chdir(folder)
    control = ReviewStore(tmp_path / 'control', empty_training=True)
    assert review_ingest.import_frames(control, {'path': str(folder)})['added'] == 2
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    with pytest.raises(ValueError, match='catalog.relative|unsupported|draft.free'):
        import_relative(store, folder)
    assert snapshot(store) == before


def test_otherwise_valid_mcap_control_is_rejected_by_new_mode_before_prover(tmp_path, monkeypatch):
    # This control must run in the required pinky-raw check; default CI may lack MCAP tools.
    pytest.importorskip('mcap_ros2')
    from test_mcap_review_import import _catalog
    catalog, classes = _catalog(tmp_path)
    control = ReviewStore(tmp_path / 'evaluation-control', empty_eval=True)
    assert review_ingest.import_frames(control, dict(path=str(catalog), classes=str(classes)))['added'] == 1
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    def forbidden(*args, **kwargs):
        pytest.fail('MCAP opt-in reached the real prover')
    monkeypatch.setattr(review_ingest, 'prove_frames', forbidden)
    with pytest.raises(ValueError, match='catalog.relative|unsupported|draft.free'):
        import_relative(store, catalog, classes=str(classes))
    assert snapshot(store) == before


def test_empty_objects_and_explicit_operator_classes_preserve_path_semantics(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    for row in rows:
        row['objects'] = []
    write_catalog(folder, rows)
    operator = tmp_path / 'operator'
    operator.mkdir()
    classes = operator / 'selected.yaml'
    classes.write_bytes((folder / 'classes.yaml').read_bytes())
    (folder / 'classes.yaml').write_bytes(b'invalid adjacent classes are not selected')
    monkeypatch.chdir(operator)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    assert import_relative(store, folder, classes='selected.yaml')['added'] == 2
    assert review_masks.classes(store)['sha256'] == sha(classes.read_bytes())


def test_bound_workspace_ignores_unrequested_adjacent_classes_but_rejects_explicit_conflict(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    review_masks.bind_classes(store, (folder / 'classes.yaml').read_bytes())
    (folder / 'classes.yaml').write_bytes(b'invalid unrequested adjacent classes')
    monkeypatch.chdir(folder)
    assert import_relative(store, folder)['added'] == 2
    (folder / 'classes.yaml').write_bytes(b'classes:\n- {index: 0, name: other, role: background, color: [1, 2, 3]}\n')
    before = snapshot(store)
    with pytest.raises(ValueError, match='classes differ'):
        import_relative(store, folder, classes=str(folder / 'classes.yaml'))
    assert snapshot(store) == before
