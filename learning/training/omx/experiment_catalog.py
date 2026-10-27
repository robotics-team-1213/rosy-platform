"""Owned uploads and immutable registered datasets, without process execution."""
import base64
import json
import os
import re
import shutil
from pathlib import Path

from experiment_dataset import load_dataset
from experiment_io import identifier, read_json, sync_directory


class Catalog:
    def __init__(self, root, connect, lock):
        self.root, self.connect, self.lock = root, connect, lock

    def upload(self, body):
        if set(body) != {'upload_id', 'name', 'offset', 'data'}:
            raise ValueError('upload fields differ from schema')
        uid = identifier(body['upload_id'])
        name = body['name']
        if not isinstance(name, str) or not re.fullmatch(r'((dataset|native-split-receipt|conversion-receipt)\.json|[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.npz)', name):
            raise ValueError('flat dataset.json or episode .npz filename required')
        offset = body['offset']
        if type(offset) is not int or offset < 0:
            raise ValueError('nonnegative integer offset required')
        try:
            chunk = base64.b64decode(body['data'], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('base64 upload chunk required') from exc
        if not 0 < len(chunk) <= 256 * 1024:
            raise ValueError('upload chunk must contain 1..262144 bytes')
        with self.lock:
            published = self.root / 'datasets' / uid
            sealed = published.exists()
            root = published if sealed else self.root / 'uploads' / uid
            if root.is_symlink():
                raise ValueError('regular owned upload directory required')
            if not sealed:
                root.mkdir(exist_ok=True)
            file = root / name
            size = file.stat().st_size if file.exists() else 0
            if file.is_symlink() or offset > size:
                raise ValueError('upload offset mismatch')
            overlap = min(len(chunk), size - offset)
            if overlap:
                with file.open('rb') as stream:
                    stream.seek(offset)
                    if stream.read(overlap) != chunk[:overlap]:
                        raise ValueError('upload retry bytes differ')
            if sealed and offset + len(chunk) > size:
                raise ValueError('published dataset is immutable')
            if overlap == len(chunk):
                if not sealed:
                    with file.open('rb') as stream:
                        os.fsync(stream.fileno())
                    sync_directory(root)
                    sync_directory(root.parent)
                return {'upload_id': uid, 'name': name, 'offset': offset + len(chunk)}
            remaining = chunk[overlap:]
            total = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
            if shutil.disk_usage(self.root).free < len(remaining) + 1024 * 1024 * 1024:
                raise ValueError('upload requires 1 GiB of remaining free disk space')
            if total + len(remaining) > 512 * 1024 * 1024 or len(list(root.iterdir())) + (not file.exists()) > 1000:
                raise ValueError('dataset upload exceeds 512 MiB or 1000 files')
            with file.open('ab') as stream:
                stream.write(remaining)
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(root)
            sync_directory(root.parent)
            return {'upload_id': uid, 'name': name, 'offset': offset + len(chunk)}

    def publish(self, body):
        if set(body) != {'upload_id', 'name'} or not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 128:
            raise ValueError('dataset display name required')
        uid = identifier(body['upload_id'])
        with self.lock, self.connect() as db:
            prior = db.execute('SELECT document FROM datasets WHERE id=?', (uid,)).fetchone()
            if prior:
                destination = self.root / 'datasets' / uid
                if destination.is_symlink() or not destination.is_dir():
                    raise ValueError('registered dataset files missing')
                return json.loads(prior[0])
            source = self.root / 'uploads' / uid
            destination = self.root / 'datasets' / uid
            if source.exists() and destination.exists():
                raise ValueError('ambiguous upload and published dataset directories')
            root = destination if destination.exists() else source
            if root.is_symlink():
                raise ValueError('regular owned dataset directory required')
            dataset = load_dataset(root)
            document = dict(id=uid, name=body['name'].strip(), source=dataset.source,
                profile=dataset.profile, revision=dataset.revision,
                counts={s: len(dataset.split(s)) for s in ('train', 'eval', 'test')})
            if root == source:
                source.rename(destination)
            sync_directory(source.parent)
            sync_directory(destination.parent)
            db.execute('INSERT INTO datasets VALUES (?,?)', (uid, json.dumps(document)))
            return document

    def exported(self, db, row, output):
        """Recover a move-before-commit safely, then register the verified converter result."""
        uid = identifier(row['id'])
        destination = self.root / 'datasets' / uid
        source = output / 'export/dataset'
        folder = destination if destination.exists() else source
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('completed export dataset missing')
        files = list(folder.iterdir())
        if (any(file.is_symlink() or not file.is_file() for file in files) or len(files) > 1000
                or sum(file.stat().st_size for file in files) > 512 * 1024 * 1024):
            raise ValueError('export dataset exceeds flat regular file limits')
        dataset = load_dataset(folder, method='act')
        converted = read_json(folder / 'conversion-receipt.json')
        if (not isinstance(converted, dict) or not isinstance(row['result'], dict)
                or dataset.source != 'reviewed_demonstration' or row['result'].get('act_only') is not True
                or dataset.revision != row['result'].get('dataset_revision')
                or converted.get('dataset_revision') != dataset.revision):
            raise ValueError('completed export revision differs from verified dataset')
        document = dict(id=uid, name=row['name'], source=dataset.source, profile=dataset.profile,
                        revision=dataset.revision,
                        counts={s: len(dataset.split(s)) for s in ('train', 'eval', 'test')})
        if folder == source:
            source.rename(destination)
        prior = db.execute('SELECT document FROM datasets WHERE id=?', (uid,)).fetchone()
        if prior and json.loads(prior[0]) != document:
            raise ValueError('registered export dataset identity changed')
        db.execute('INSERT OR IGNORE INTO datasets VALUES (?,?)', (uid, json.dumps(document)))
        return uid

    def archive_sources(self, project_id):
        """List already registered data without refreshing jobs or moving files."""
        with self.lock, self.connect() as db:
            self._archive_project(db, project_id)
            return [{key: row[key] for key in ('id', 'name', 'revision', 'source')}
                    for (raw,) in db.execute('SELECT document FROM datasets ORDER BY rowid DESC')
                    for row in [json.loads(raw)]]

    @staticmethod
    def _archive_project(db, project_id):
        binding = db.execute('SELECT project_id FROM workspace_binding WHERE singleton=1').fetchone()
        if not binding or binding[0] != project_id:
            raise ValueError('learning archive source belongs to a different project')

    def archive_source(self, dataset_id, revision, project_id):
        """Return a server-only snapshot of bounded, registered dataset bytes."""
        from storage_inventory import open_root
        from storage_files import entry, file_open, names
        uid = identifier(dataset_id)
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise ValueError('fixed dataset revision required')
        with self.lock, self.connect() as db:
            self._archive_project(db, project_id)
            found = db.execute('SELECT document FROM datasets WHERE id=?', (uid,)).fetchone()
            if not found or json.loads(found[0])['revision'] != revision:
                raise ValueError('registered dataset and matching revision required')
            row = json.loads(found[0])
            root = self.root / 'datasets' / uid
            fd = open_root(str(root))
            try:
                present = names(fd)
                with file_open(fd, 'dataset.json') as stream: raw = stream.read(1024 ** 2 + 1)
                if len(raw) > 1024 ** 2: raise ValueError('dataset description exceeds 1 MiB')
                document = json.loads(raw)
                declared = {'dataset.json', *(item['file'] for item in document['episodes'])}
                receipts = present & {'native-split-receipt.json', 'conversion-receipt.json'}
                if (present != declared | receipts or len(present) > 1000
                        or any('/' in name or not re.fullmatch(
                            r'((dataset|native-split-receipt|conversion-receipt)\.json|[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.npz)', name)
                            for name in present)):
                    raise ValueError('only registered flat dataset files and receipts may be archived')
                files = {name: entry(fd, name) for name in sorted(present)}
                if sum(item['bytes'] for item in files.values()) > 512 * 1024 ** 2:
                    raise ValueError('dataset archive exceeds 512 MiB')
                checked = load_dataset(root)
                if checked.revision != revision or checked.source != row['source']:
                    raise ValueError('registered dataset bytes changed')
                if names(fd) != present or any(entry(fd, name) != value for name, value in files.items()):
                    raise ValueError('dataset changed during archive validation')
                info = os.fstat(fd)
                return dict(path=root, identity=[info.st_dev, info.st_ino], files=files,
                    provenance=dict(dataset_id=uid, source_revision=revision, source=checked.source,
                                    format='rosy.omx.experiment-dataset'))
            finally: os.close(fd)
