"""Copy one registered Center dataset into the existing managed archive workflow."""
import hashlib
import json
import os
from pathlib import Path

from storage_files import SOURCE, claim, file_open, names
from storage_inventory import free_space, open_root
import storage_source


def export_dataset(catalog, project_id, dataset_id, revision, output, checkpoint):
    snapshot = catalog.archive_source(dataset_id, revision, project_id)
    output = Path(output).absolute()
    if output.is_relative_to(snapshot['path']) or snapshot['path'].is_relative_to(output):
        raise ValueError('archive copy must be separate from the learning dataset')
    parent = open_root(str(output.parent))
    try:
        if free_space(parent) < sum(row['bytes'] for row in snapshot['files'].values()) + 1024 ** 3:
            raise ValueError('insufficient space for learning archive copy')
        try: os.mkdir(output.name, 0o700, dir_fd=parent)
        except FileExistsError: pass
    finally: os.close(parent)
    source, destination = open_root(str(snapshot['path'])), None
    try:
        destination = open_root(str(output))
        info = os.fstat(source)
        if snapshot['identity'] != [info.st_dev, info.st_ino]:
            raise ValueError('learning source directory changed')
        with claim(destination, exclusive=True):
            checkpoint()
            finalized = storage_source._finish_publication(destination)
            if finalized:
                with file_open(destination, SOURCE) as stream: raw = stream.read(1024 ** 2 + 1)
                if len(raw) > 1024 ** 2: raise ValueError('source metadata exceeds 1 MiB')
                previous = json.loads(raw)
                if (previous['files'] != snapshot['files']
                        or previous['provenance'] != snapshot['provenance']):
                    raise ValueError('existing archive is bound to different learning bytes')
            else:
                if not names(destination) <= snapshot['files'].keys() | {storage_source.SOURCE_PENDING}:
                    raise ValueError('unregistered partial archive files are preserved')
                for name, expected in snapshot['files'].items():
                    checkpoint()
                    with file_open(source, name) as stream: raw = stream.read(expected['bytes'] + 1)
                    if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                        raise ValueError('learning bytes changed while copying')
                    storage_source._generated(destination, name, raw, resume=True)
            checkpoint()
            if catalog.archive_source(dataset_id, revision, project_id) != snapshot:
                raise ValueError('learning source changed during archive copy')
    finally:
        os.close(source)
        if destination is not None: os.close(destination)
    if not finalized:
        storage_source.seal(output, 'dataset', snapshot['provenance'], expected_files=snapshot['files'])
