"""Bounded read-only review of verified stopped passive recordings."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading

import passive_recording as recording
from passive_recording_io import check_draft, verify

INDEX_BYTES=128*1024**2


class Review:
    @classmethod
    def build(cls,root,expected_profile_revision,*,cancelled=lambda:False):
        if (not isinstance(expected_profile_revision,str)
                or not re.fullmatch('[0-9a-f]{64}',expected_profile_revision)):
            raise ValueError('expected passive profile SHA256 revision required')
        root=Path(root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError('owned stopped recording directory required')
        if cancelled():
            raise ValueError('passive review cancelled')
        try:
            config=recording.read_json(root/'config.json')
        except OSError as exc:
            raise ValueError('passive review configuration is unavailable') from exc
        if not isinstance(config,dict) or config.get('profile_revision')!=expected_profile_revision:
            raise ValueError('review profile revision differs')
        result=cls()
        result.root=root.resolve()
        result.lock=threading.RLock()
        result.db=None
        try:
            result.db=sqlite3.connect(':memory:',check_same_thread=False)
            result.db.execute('PRAGMA page_size=4096')
            result.db.execute('PRAGMA max_page_count='+str(INDEX_BYTES//4096))
            result.db.execute('PRAGMA journal_mode=OFF')
            result.db.execute('CREATE TABLE frames (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            def index(row):
                if cancelled():
                    raise ValueError('passive review cancelled')
                result.db.execute('INSERT INTO frames VALUES (?,?)',
                    (row['frame_index'],recording.canonical(row).decode('utf-8')))
            summary=recording.read_json(root/'episode.json')
            if summary.get('status')=='kept':
                evidence=verify(root,on_frame=index,cancelled=cancelled)
                config=evidence['config']
            elif summary.get('status')=='draft':
                summary,config=check_draft(root,on_frame=index,cancelled=cancelled)
                evidence=recording.read_json(root/'draft.json')
            else:
                raise ValueError('only verified stopped draft/kept episodes can be reviewed')
            if cancelled():
                raise ValueError('passive review cancelled')
            if (config['profile_revision']!=expected_profile_revision
                    or not re.fullmatch('[0-9a-f]{64}',evidence['revision'])):
                raise ValueError('review evidence/profile revision changed')
            count=result.db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
            if count!=evidence['frames']:
                raise ValueError('review index does not cover complete verified grids')
            result.db.commit()
            result.files=dict(evidence['files'])
            result.cameras={camera['id']:copy.deepcopy(camera)
                            for camera in recording.retained(config['profile'])}
            result.metadata=dict(frames=count,fps=config['timing']['fps'],
                profile_revision=expected_profile_revision,evidence_revision=evidence['revision'],
                checked_at=datetime.now(timezone.utc).isoformat(),
                arms=copy.deepcopy(config['profile']['arms']),
                cameras=[{key:value for key,value in camera.items() if key!='source_identity'}
                         for camera in result.cameras.values()],
                task_outcome=summary['task_outcome'],scope='content_integrity_at_load',
                physical_learning_verified=False)
            result._check_metadata()
            return result
        except BaseException as exc:
            result.close()
            if isinstance(exc,(OSError,sqlite3.Error,KeyError,TypeError,IndexError)):
                raise ValueError('passive review evidence/index unavailable or exceeds 128 MiB') from exc
            raise

    def _path(self,name,limit):
        if not isinstance(name,str) or '\\' in name or ':' in name:
            raise ValueError('owned relative review evidence path required')
        relative=PurePosixPath(name)
        if relative.is_absolute() or str(relative)!=name or any(part in ('.','..') for part in relative.parts):
            raise ValueError('review evidence path escaped owned recording')
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError('review source directory changed')
        path=self.root
        for part in relative.parts:
            path=path/part
            if path.is_symlink():
                raise ValueError('review evidence links are forbidden')
        if not path.is_file() or path.stat().st_size>limit:
            raise ValueError('bounded regular review evidence required')
        return path

    def _check_metadata(self):
        for name in ('config.json','frames.jsonl'):
            path=self._path(name,recording.MAX_METADATA)
            with path.open('rb') as stream:
                actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=self.files.get(name):
                raise ValueError('review metadata bytes changed since verified load')

    def _row(self,index):
        if self.db is None:
            raise ValueError('passive review is closed')
        if type(index) is not int or not 0<=index<self.metadata['frames']:
            raise ValueError('review frame index outside verified episode')
        value=self.db.execute('SELECT body FROM frames WHERE id=?',(index,)).fetchone()
        if value is None:
            raise ValueError('verified review frame is missing')
        return json.loads(value[0])

    def summary(self):
        with self.lock:
            if self.db is None:
                raise ValueError('passive review is closed')
            return copy.deepcopy(self.metadata)

    def frame(self,index):
        with self.lock:
            if self.db is None:
                raise ValueError('passive review is closed')
            try:
                self._check_metadata()
                return self._row(index)
            except (OSError,sqlite3.Error) as exc:
                raise ValueError('verified review metadata/index unavailable') from exc

    def image(self,index,camera_id):
        with self.lock:
            try:
                row=self._row(index)
                if not isinstance(camera_id,str) or camera_id not in self.cameras:
                    raise ValueError('camera is not retained in this verified episode')
                event=row['cameras'][camera_id]
                path=self._path(event['path'],16*1024**2)
                with path.open('rb') as stream:
                    raw=stream.read(16*1024**2+1)
                if (len(raw)>16*1024**2 or event['sha256']!=self.files.get(event['path'])
                        or hashlib.sha256(raw).hexdigest()!=event['sha256']):
                    raise ValueError('review image bytes changed since verified load')
                recording.image_valid(raw,self.cameras[camera_id]['shape'])
                return raw
            except (OSError,sqlite3.Error) as exc:
                raise ValueError('verified review image unavailable') from exc

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db=None
