"""Immutable DatasetManifest/Episode closure and OMX v1 body checks; no task certification."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'contracts/learning/src'))
from rosy.contracts.learning import validate_dataset, validate_episode  # noqa: E402
from rosy.contracts.learning.omx import validate_profile  # noqa: E402


def closure(root):
    root = Path(root).resolve()
    doc = validate_dataset(json.loads((root / 'dataset-manifest.json').read_text(encoding='utf-8')), root=root)
    files = {ref['path']: ref for ref in doc['files']}
    episodes = {}
    for relative in files:
        path = root / relative
        if path.suffix != '.json':
            continue
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema') != 'rosy.episode/1':
            continue
        episode = validate_episode(value, root=path.parent)
        if episode['revision'] in episodes:
            raise ValueError('duplicate Episode manifest')
        refs = episode['sources'] + list(episode['streams'].values()) + episode['outcome']['evidence']
        for ref in refs:
            name = (path.parent / ref['path']).relative_to(root).as_posix()
            if name not in files or any(files[name][key] != ref[key] for key in ('sha256', 'bytes')):
                raise ValueError('Episode file is outside declared dataset closure')
        if episode['profile'] != 'omx_demonstration_v1':
            raise ValueError('Episode body profile validator not implemented')
        validate_profile(episode, root=path.parent)
        episodes[episode['revision']] = episode
    if set(episodes) != set(doc['episodes']):
        raise ValueError('DatasetManifest Episode revisions differ from actual manifests')
    return doc


class DatasetStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if self.root.drive.upper() == 'F:':
            raise ValueError('dataset output belongs outside source drive F:')
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.root / 'datasets.sqlite3')) as db:
            db.execute('CREATE TABLE IF NOT EXISTS datasets (revision TEXT PRIMARY KEY)')

    def require(self, revisions):
        with closing(sqlite3.connect(self.root / 'datasets.sqlite3')) as db:
            registered = {row[0] for row in db.execute('SELECT revision FROM datasets')}
        for revision in revisions:
            if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
                raise ValueError('canonical dataset revision required')
            if revision not in registered:
                raise ValueError('policy dataset not registered')
            if closure(self.root / revision)['revision'] != revision:
                raise ValueError('registered dataset revision differs')
        return list(revisions)

    def register(self, source):
        source = Path(source).resolve()
        doc = closure(source)
        revision = doc['revision']
        db = sqlite3.connect(self.root / 'datasets.sqlite3', timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM datasets WHERE revision=?', (revision,)).fetchone():
                self.require([revision])
                return doc
            target = self.root / revision
            if not target.exists():
                with tempfile.TemporaryDirectory(prefix='.dataset-', dir=self.root) as scratch:
                    stage = Path(scratch) / 'files'
                    stage.mkdir()
                    for name in ['dataset-manifest.json'] + [ref['path'] for ref in doc['files']]:
                        destination = stage / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source / name, destination)
                        with destination.open('r+b') as stream:
                            os.fsync(stream.fileno())
                    if closure(stage) != doc:
                        raise ValueError('dataset changed while copying')
                    os.replace(stage, target)
            if closure(target) != doc:
                raise ValueError('existing dataset snapshot differs')
            db.execute('INSERT INTO datasets VALUES (?)', (revision,))
            db.commit()
            return doc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    doc = DatasetStore(args.root).register(args.source)
    print(json.dumps({'revision': doc['revision'], 'episodes': len(doc['episodes']), 'files': len(doc['files'])}))


if __name__ == '__main__':
    main()
