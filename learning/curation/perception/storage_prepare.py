"""Bounded source discovery and preparation inside registered export locations."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from storage_files import SOURCE, parts
from storage_inventory import open_root


class StoragePrepare:
    def __init__(self, setup, sim_runs=None):
        self.setup, self.sim_runs = setup, sim_runs

    def sources(self, actor):
        self.setup._manager(actor)
        _, config = self.setup.configuration()
        folders = []
        for root in config['roots']:
            if root['role'] == 'cache': continue
            try:
                fd = open_root(root['path'])
                try:
                    with os.scandir(fd) as entries:
                        for count, entry in enumerate(entries):
                            if count >= 1000 or len(folders) >= 200: break
                            if entry.name.startswith('.') or not entry.is_dir(follow_symlinks=False): continue
                            try:
                                parts(entry.name)
                                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                                try: prepared = stat.S_ISREG(os.stat(SOURCE, dir_fd=child, follow_symlinks=False).st_mode)
                                except FileNotFoundError: prepared = False
                                finally: os.close(child)
                            except (ValueError, OSError): continue
                            folders.append(dict(source_id=root['id'], artifact_id=entry.name,
                                                prepared=prepared, can_prepare=root['id'] == 'exports'))
                finally: os.close(fd)
            except OSError: continue
        return dict(folders=folders, sim_configured=self.sim_runs is not None)

    def sim_sources(self, actor):
        self.setup._manager(actor)
        if self.sim_runs is None: return dict(configured=False, runs=[])
        rows = self.sim_runs.call(dict(action='list'))
        return dict(configured=True, runs=[{key: row.get(key) for key in ('run_id', 'status', 'scenario_id')}
            for row in rows[:100] if row.get('snapshot') == 'FINAL'
            and row.get('result', {}).get('cleanup') in ('OWNED_PROCESSES_EXITED_GPU_RELEASED', 'SDK_NOT_STARTED')])

    def validate(self, body):
        common = {'kind', 'confirm_completed', 'archive'}
        if not isinstance(body, dict) or body.get('confirm_completed') is not True or type(body.get('archive')) is not bool:
            raise ValueError('confirm completed input and choose whether to archive')
        if body.get('kind') == 'folder':
            if set(body) != common | {'artifact_id', 'profile', 'provenance'}:
                raise ValueError('explicit export folder, profile and provenance required')
            parts(body['artifact_id'])
            if body['profile'] not in ('dataset', 'model', 'isaac') or not isinstance(body['provenance'], dict):
                raise ValueError('invalid source profile or provenance')
            if len(json.dumps(body['provenance'], allow_nan=False).encode()) > 65536:
                raise ValueError('source provenance is too large')
        elif body.get('kind') == 'isaac':
            if set(body) != common | {'run_id'} or not isinstance(body['run_id'], str) or not re.fullmatch('[0-9a-f]{32}', body['run_id']):
                raise ValueError('completed Isaac run required')
            if self.sim_runs is None: raise ValueError('SIM owner is not configured')
        else: raise ValueError('unknown source preparation')

    def prepare(self, actor, body):
        self.setup._manager(actor); self.validate(body)
        from storage_source import seal, export_isaac_snapshot
        service = self.setup.jobs()
        _, config = self.setup.configuration()
        if body['archive'] and not config['pool']['enabled']: raise ValueError('activate storage before new archive assignments')
        root = next(row for row in config['roots'] if row['id'] == 'exports')
        name = body['artifact_id'] if body['kind'] == 'folder' else 'isaac-' + body['run_id']
        location = dict(root_id='exports', relative=name)
        path = Path(root['path']).joinpath(*parts(name))
        if body['kind'] == 'folder':
            with service.files.open(location) as fd:
                try: os.stat(SOURCE, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError: seal(path, body['profile'], body['provenance'])
            profile = body['profile']
        else:
            run_id = body['run_id']
            def get(): return self.sim_runs.call(dict(action='status', run_id=run_id))
            def artifact(item_id):
                blob = self.sim_runs.call(dict(action='artifact', run_id=run_id, artifact_id=item_id))
                if type(blob.get('bytes')) is not int or not 0 <= blob['bytes'] <= 1048576:
                    raise ValueError('Isaac owner artifact exceeds the review bridge limit')
                raw = base64.b64decode(blob['data_base64'], validate=True)
                if len(raw) != blob['bytes'] or hashlib.sha256(raw).hexdigest() != blob['sha256']:
                    raise ValueError('Isaac owner artifact changed')
                return dict(data=raw)
            if not (path / SOURCE).is_file(): export_isaac_snapshot(get, artifact, run_id, path)
            profile = 'isaac'
        manifest = service.files.manifest(location, profile)
        if not body['archive']: return dict(status='prepared', artifact_id=name, profile=profile)
        key = hashlib.sha256(json.dumps([name, manifest['identity'], manifest['files']], sort_keys=True).encode()).hexdigest()
        job = service.create(actor, dict(source_id='exports', artifact_id=name, profile=profile), source_key=key)
        return service.run(actor, job['id'])
