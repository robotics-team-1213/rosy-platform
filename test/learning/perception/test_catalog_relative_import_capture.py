"""Actual descriptor witnesses for contained, finite, stable catalog capture."""
import os
import multiprocessing
from pathlib import Path

import pytest

import review_ingest
from review_app import ReviewStore
from test_catalog_relative_import import prepared, write_catalog, import_relative, snapshot, sha


def identity(stat):
    return stat.st_dev, stat.st_ino


def fd_count():
    return len(list(Path('/proc/self/fd').iterdir()))


def fd_snapshot():
    descriptors = {}
    for path in list(Path('/proc/self/fd').iterdir()):
        try:
            descriptors[path.name] = os.readlink(path)
        except FileNotFoundError:
            continue
    return descriptors


def _fifo_import_worker(sender, store, folder):
    """Run the genuine importer; report both refusal and owned-FD cleanup."""
    baseline = fd_count()
    try:
        import_relative(store, folder)
    except ValueError as exc:
        result = ('refused', str(exc), fd_count() - baseline)
    except BaseException as exc:
        result = ('unexpected', repr(exc), fd_count() - baseline)
    else:
        result = ('accepted', '', fd_count() - baseline)
    try:
        sender.send(result)
    finally:
        sender.close()


def bounded_fifo_import(store, folder):
    """An unsafe old importer must fail this test without hanging native pytest."""
    context = multiprocessing.get_context('fork')
    baseline = fd_count()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_fifo_import_worker, args=(sender, store, folder))
    result = None
    try:
        process.start()
        sender.close()
        process.join(timeout=5)
        if process.is_alive():
            result = ('blocked', 'FIFO import did not refuse within 5 seconds', None)
        elif receiver.poll():
            result = receiver.recv()
        else:
            result = ('unexpected', f'import worker exited {process.exitcode} without result', None)
    finally:
        # Reap only our own child, including the deliberately blocked baseline.
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            assert not process.is_alive(), 'FIFO import worker could not be reaped'
            process.close()
        receiver.close()
        sender.close()
    assert fd_count() == baseline, 'FIFO watchdog leaked parent descriptors'
    return result


@pytest.mark.parametrize('target', ['catalog', 'selected-directory', 'selected-ancestor',
    'implicit-classes', 'explicit-classes', 'image-leaf', 'image-parent', 'video-leaf', 'video-parent'])
@pytest.mark.parametrize('outside', [False, True])
def test_selected_or_internal_links_never_read_target_bytes(tmp_path, monkeypatch, target, outside):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    body = dict(path=str(folder), catalog_relative=True)
    if target == 'catalog':
        chosen = folder / 'verified-inputs.jsonl'
    elif target in ('selected-directory', 'selected-ancestor'):
        chosen = folder
    elif target in ('implicit-classes', 'explicit-classes'):
        chosen = folder / 'classes.yaml'
        if target == 'explicit-classes':
            body['classes'] = str(chosen)
    elif target.startswith('image'):
        chosen = folder / rows[-1]['image']
        if target.endswith('parent'):
            chosen = chosen.parent
    else:
        chosen = folder / rows[-1]['source_video']
        if target.endswith('parent'):
            chosen = chosen.parent
    moved = (tmp_path if outside else chosen.parent) / ('linked-target-' + chosen.name)
    chosen.rename(moved)
    chosen.symlink_to(moved, target_is_directory=moved.is_dir())
    # The ancestry case selects an ordinary child of the linked directory.
    if target == 'selected-ancestor':
        body['path'] = str(chosen / 'verified-inputs.jsonl')
    protected = {identity(p.stat()) for p in ([moved] if moved.is_file() else moved.rglob('*'))
                 if p.is_file()}
    real_read, real_fstat = os.read, os.fstat
    reads = []
    def observe(fd, count):
        raw = real_read(fd, count)
        if identity(real_fstat(fd)) in protected:
            reads.append(len(raw))
        return raw
    before, baseline = snapshot(store), fd_snapshot()
    monkeypatch.setattr(os, 'read', observe)
    with pytest.raises(ValueError, match='link|path|regular|catalog|directory|capture'):
        review_ingest.import_frames(store, body)
    assert not reads, 'linked selected content was read through an actual target FD'
    assert snapshot(store) == before
    current = fd_snapshot()
    assert current == baseline, dict(before=baseline, after=current)


def test_directory_replacement_after_parent_open_never_reads_outside_and_rejects_stale_binding(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    original = folder / 'images'
    saved = folder / 'images-pinned'
    outside = tmp_path / 'attacker'
    outside.mkdir()
    for row in rows:
        (outside / Path(row['image']).name).write_bytes((folder / row['image']).read_bytes())
    outside_ids = {identity(p.stat()) for p in outside.iterdir()}
    real_open, real_read, real_fstat = os.open, os.read, os.fstat
    fired, outside_bytes, original_bytes = [], [], []
    original_ids = {identity((folder / row['image']).stat()) for row in rows}
    def replace_after_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if not fired and identity(real_fstat(fd)) == identity(original.stat()):
            assert flags & os.O_DIRECTORY
            original.rename(saved)
            original.symlink_to(outside, target_is_directory=True)
            fired.append(fd)
        return fd
    def witness(fd, count):
        raw = real_read(fd, count)
        inode = identity(real_fstat(fd))
        if inode in outside_ids:
            outside_bytes.append(len(raw))
        if inode in original_ids:
            original_bytes.append(len(raw))
        return raw
    before, baseline = snapshot(store), fd_count()
    monkeypatch.setattr(os, 'open', replace_after_open)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {replace_after_open})
    monkeypatch.setattr(os, 'read', witness)
    with pytest.raises(ValueError, match='changed|binding|link|stale|path'):
        import_relative(store, folder)
    assert fired, 'race must occur after the genuine directory descriptor was acquired'
    assert sum(outside_bytes) == 0, 'outside target inode supplied content'
    assert snapshot(store) == before and fd_count() == baseline


@pytest.mark.parametrize('replace', ['root', 'catalog', 'classes', 'image'])
def test_namespace_rebinding_after_capture_is_rejected_before_persistence(tmp_path, monkeypatch, replace):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    last_image = folder / rows[-1]['image']
    trigger = identity(last_image.stat())
    real_read, real_fstat = os.read, os.fstat
    fired = []
    def rebind(fd, count):
        raw = real_read(fd, count)
        if raw and not fired and identity(real_fstat(fd)) == trigger:
            fired.append(fd)
            selected = {'root': folder, 'catalog': folder / 'verified-inputs.jsonl',
                        'classes': folder / 'classes.yaml', 'image': last_image}[replace]
            saved = selected.with_name(selected.name + '-original')
            selected.rename(saved)
            if saved.is_dir():
                selected.mkdir()
            else:
                selected.write_bytes(saved.read_bytes())
        return raw
    before, baseline = snapshot(store), fd_count()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, 'read', rebind)
    with pytest.raises(ValueError, match='changed|binding|stale|capture|namespace'):
        import_relative(store, folder)
    assert fired, 'must replace a captured binding, not fail an earlier guard'
    assert snapshot(store) == before and fd_count() == baseline


def test_lexical_parent_escape_is_refused_before_actual_outside_read(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    raw = (folder / rows[-1]['image']).read_bytes()
    outside = tmp_path / 'outside.png'
    outside.write_bytes(raw)
    rows[-1].update(image='../outside.png', image_sha256=sha(raw))
    write_catalog(folder, rows)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    real_read, real_fstat = os.read, os.fstat
    outside_id, reads = identity(outside.stat()), []
    def witness(fd, count):
        raw = real_read(fd, count)
        if identity(real_fstat(fd)) == outside_id:
            reads.append(len(raw))
        return raw
    before, baseline = snapshot(store), fd_count()
    monkeypatch.chdir(folder)
    monkeypatch.setattr(os, 'read', witness)
    with pytest.raises(ValueError, match='relative|portable|path|reference'):
        import_relative(store, folder)
    assert sum(reads) == 0
    assert snapshot(store) == before and fd_count() == baseline


@pytest.mark.parametrize('fault', ['growth', 'same-size-change'])
@pytest.mark.parametrize('selected,limit', [('catalog', 32 * 1024**2), ('classes', 1024**2),
                                           ('image', 32 * 1024**2)])
def test_same_handle_capture_bounds_growth_and_rejects_metadata_change(tmp_path, monkeypatch, fault, selected, limit):
    folder, rows = prepared(tmp_path)
    path = {'catalog': folder / 'verified-inputs.jsonl', 'classes': folder / 'classes.yaml',
            'image': folder / rows[-1]['image']}[selected]
    target = identity(path.stat())
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    real_read, real_fstat = os.read, os.fstat
    requests, captured, fired = [], [], []
    def mutate(fd, count):
        if identity(real_fstat(fd)) != target:
            return real_read(fd, count)
        requests.append(count)
        assert 0 < count <= limit + 1, 'unbounded same-handle read request'
        if not fired:
            fired.append(fd)
            if fault == 'growth':
                with path.open('r+b') as changing:
                    changing.truncate(limit + 2)
            else:
                status = path.stat()
                os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000))
        raw = real_read(fd, count)
        captured.append(len(raw))
        return raw
    before, baseline = snapshot(store), fd_count()
    monkeypatch.chdir(folder)
    monkeypatch.setattr(os, 'read', mutate)
    with pytest.raises(ValueError, match='limit|bound|changed|stable|capture'):
        import_relative(store, folder)
    assert fired and requests, 'test must mutate the actual captured selected FD'
    assert sum(captured) <= limit + 1
    assert snapshot(store) == before and fd_count() == baseline


@pytest.mark.parametrize('selected,limit', [('catalog', 32 * 1024**2), ('classes', 1024**2),
                                           ('image', 32 * 1024**2)])
def test_initial_oversize_is_refused_without_content_read(tmp_path, monkeypatch, selected, limit):
    folder, rows = prepared(tmp_path)
    path = {'catalog': folder / 'verified-inputs.jsonl', 'classes': folder / 'classes.yaml',
            'image': folder / rows[-1]['image']}[selected]
    with path.open('r+b') as stream:
        stream.truncate(limit + 1)
    target = identity(path.stat())
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    real_read, real_fstat = os.read, os.fstat
    reads = []
    def witness(fd, count):
        raw = real_read(fd, count)
        if identity(real_fstat(fd)) == target:
            reads.append(len(raw))
        return raw
    before, baseline = snapshot(store), fd_count()
    monkeypatch.setattr(os, 'read', witness)
    with pytest.raises(ValueError, match='limit|bound'):
        import_relative(store, folder)
    assert not reads and snapshot(store) == before and fd_count() == baseline


def test_success_reads_each_selected_content_once_and_never_reads_video(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    paths = [folder / 'verified-inputs.jsonl', folder / 'classes.yaml',
             *(folder / row['image'] for row in rows)]
    expected = {identity(p.stat()): p.read_bytes() for p in paths}
    video_id = identity((folder / rows[0]['source_video']).stat())
    captured = {key: bytearray() for key in expected}
    real_read, real_fstat = os.read, os.fstat
    def witness(fd, count):
        inode = identity(real_fstat(fd))
        assert inode != video_id, 'video reference permits metadata inspection only'
        raw = real_read(fd, count)
        if inode in captured:
            captured[inode].extend(raw)
        return raw
    monkeypatch.chdir(folder)
    baseline = fd_count()
    monkeypatch.setattr(os, 'read', witness)
    assert import_relative(store, folder)['added'] == 2
    assert {key: bytes(raw) for key, raw in captured.items()} == expected
    assert fd_count() == baseline


@pytest.mark.parametrize('field', ['image', 'source_video'])
@pytest.mark.parametrize('kind', ['directory', 'fifo'])
def test_nonregular_reference_refuses_without_blocking(tmp_path, monkeypatch, field, kind):
    folder, rows = prepared(tmp_path)
    chosen = folder / 'nonregular.png'
    if kind == 'directory':
        chosen.mkdir()
    else:
        os.mkfifo(chosen)
    rows[-1][field] = chosen.name
    write_catalog(folder, rows)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before, baseline = snapshot(store), fd_count()
    monkeypatch.chdir(folder)
    if kind == 'fifo':
        result, detail, fd_delta = bounded_fifo_import(store, folder)
        # Check effects even when a legacy importer blocks or accepts the FIFO.
        assert snapshot(store) == before and fd_count() == baseline
        assert result == 'refused', f'{result}: {detail}'
        assert fd_delta == 0, 'importer leaked descriptors in the actual child'
        assert any(word in detail for word in ('regular', 'file', 'reference')), detail
    else:
        with pytest.raises(ValueError, match='regular|file|reference'):
            import_relative(store, folder)
    assert snapshot(store) == before and fd_count() == baseline


def test_unavailable_nofollow_support_fails_closed_before_selected_content(tmp_path, monkeypatch):
    folder, rows = prepared(tmp_path)
    store = ReviewStore(tmp_path / 'state', empty_training=True)
    before = snapshot(store)
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported platform reached selected content')
    monkeypatch.delattr(os, 'O_NOFOLLOW')
    monkeypatch.setattr(os, 'read', forbidden)
    with pytest.raises(ValueError, match='POSIX|support|nofollow|platform'):
        import_relative(store, folder)
    assert snapshot(store) == before
