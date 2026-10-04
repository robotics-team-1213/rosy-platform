"""Owner-side indexed build/request/admission wiring; no portable grant.

Construct this context explicitly in the trusted producer composition. The default
cycle CLI never obtains training permission from a receipt or a config boolean.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from job_state import JobError
from review_admission import IndexedReview
from review_authority import advance_revision, verify_bundle
from review_dataset import build_dataset, _delivery, _stable_bytes
from store import Store, parse_dataset_ref


def _signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class ReviewPipeline:
    """Private owner settings, persisted transport highwater and per-run checks."""
    def __init__(self, *, source_proof_files, staging_parent, dataset_name,
                 eval_companion_files=(), authority_max_age_s=90, now=time.time):
        self.source_proof_files = tuple(str(Path(p).absolute()) for p in source_proof_files)
        self.eval_companion_files = tuple(str(Path(p).absolute()) for p in eval_companion_files)
        self.staging_parent = str(Path(staging_parent).absolute())
        self.dataset_name = dataset_name
        self.authority_max_age_s = authority_max_age_s
        self.now = now
        self.signature = _signature(self._settings())

    def _settings(self):
        return dict(source_proof_files=self.source_proof_files,
                    eval_companion_files=self.eval_companion_files,
                    staging_parent=self.staging_parent, dataset_name=self.dataset_name,
                    authority_max_age_s=self.authority_max_age_s)

    def check_settings(self):
        if _signature(self._settings()) != self.signature:
            raise JobError('owner review pipeline settings changed')
        if (type(self.authority_max_age_s) not in (int,float)
                or not 0 < self.authority_max_age_s <= 90):
            raise JobError('bounded owner pipeline freshness required')

    def _transport(self, config, job):
        self.check_settings()
        config_sha = _signature(config)
        cfg = config.get('authority')
        if not isinstance(cfg,dict):
            raise JobError('owner pipeline requires pinned current transport')
        path = Path(cfg['path']).absolute()
        workspace = cfg['workspace_id']
        # Keep one parsed stable byte capture per fetch; never refresh its timestamp.
        def fetch():
            self.check_settings()
            if _signature(config) != config_sha:
                raise JobError('cycle config changed during review processing')
            return json.loads(_stable_bytes(path))
        receipt = fetch()
        highwater = receipt.get('revision')
        if (not isinstance(highwater,dict)
                or set(highwater) != {'workspace_id','generation','decision_sha256'}):
            raise JobError('persisted transport authority highwater required')
        current,revision = _delivery(lambda:receipt,workspace,highwater,
                                    self.authority_max_age_s,self.now)
        if revision != highwater:
            raise JobError('transport revision differs from current authority')
        advance_revision(current,workspace_id=workspace,
                         previous=job.state.get('review_pipeline_highwater'))
        job.state['review_pipeline_highwater'] = copy.deepcopy(revision)
        job._save()
        return fetch,current,revision

    def _context(self, config, job, export):
        fetch,current,previous = self._transport(config,job)
        verify_bundle(export,current,workspace_id=previous['workspace_id'])
        return IndexedReview(export_root=export,fetch_current=fetch,
            workspace_id=previous['workspace_id'],previous_authority=previous,
            source_proof_files=self.source_proof_files,staging_parent=self.staging_parent,
            authority_max_age_s=self.authority_max_age_s,now=self.now,
            eval_companion_files=self.eval_companion_files)

    def _evals(self, config):
        import yaml
        trainer=config['trainer']; store=Store(trainer['store'])
        gate=yaml.safe_load(_stable_bytes(Path(trainer['gate'])))
        evaluation=(Path(trainer['replay_root'])/gate['eval_set']).resolve()
        folders=tuple(sorted(store.evalset_path(name,digest).absolute()
            for name,versions in store.evalsets().items() for digest in versions))
        if evaluation not in folders:
            raise JobError('required gate evaluation missing from complete store inventory')
        return store,folders,evaluation

    def _logical_key(self, current, folders, bindings):
        # Authority generation and outer seal record delivery provenance, not
        # new GT or an authorization to reset recipe attempt budgets.
        decisions={key:value for key,value in current.items()
                   if key not in ('generation','decision_sha256')}
        return _signature(dict(decisions=decisions,owner_bindings=bindings,
            sources={path:hashlib.sha256(_stable_bytes(Path(path))).hexdigest()
                     for path in self.source_proof_files},
            companions={path:hashlib.sha256(_stable_bytes(Path(path)/'manifest.json')).hexdigest()
                        for path in self.eval_companion_files},
            evaluations=[{'name':path.parent.name,'sha256':path.name} for path in folders]))

    def cycle_key(self, config, job, dataset, recipe):
        logical=job.state.get('review_pipeline_dataset_keys',{}).get(dataset)
        if not isinstance(logical,str):
            raise JobError('indexed request lacks owner-bound logical input identity')
        return _signature(dict(review_inputs=logical,recipe=recipe))

    def prepare(self, config, job):
        """Fresh build and owner admission before exclusively publishing a request."""
        progress={'status':'held','blockers':[]}
        job.state['review_autobuild']=progress
        try:
            config_sha = _signature(config)
            binding_paths=[Path(config['trainer']['gate']).resolve(),
                           Path(config['trainer']['camera_profile']).resolve()]
            bindings={path:hashlib.sha256(_stable_bytes(path)).hexdigest() for path in binding_paths}
            previous_bindings=job.state.get('review_pipeline_input_bindings')
            encoded={str(path):value for path,value in bindings.items()}
            if previous_bindings is not None and previous_bindings != encoded:
                raise JobError('owner gate/camera bindings changed; explicit new cycle required')
            job.state['review_pipeline_input_bindings']=encoded
            job._save()
            fetch,current,revision=self._transport(config,job)
            if not any(row.get('mask_decision')=='approved' and row.get('frame_excluded') is not True
                       for row in current['frames']):
                raise JobError('no_approved_masks')
            candidates=[]
            for path in sorted(Path(config['reviews_dir']).glob('*')):
                if not path.is_dir() or path.name.startswith('.') or not (path/'AUTHORITY_COMPLETE').is_file():
                    continue
                try:verify_bundle(path,current,workspace_id=revision['workspace_id'])
                except (ValueError,OSError,KeyError,TypeError):continue
                candidates.append(path)
            if not candidates:raise JobError('no sealed export matches current authority')
            export=candidates[0]
            store,folders,evaluation=self._evals(config)
            logical=self._logical_key(current,folders,encoded)
            cycles=job.state.get('cycles',{})
            keys=[_signature(dict(review_inputs=logical,recipe=recipe)) for recipe in config['recipes']]
            if all(cycles.get(key,{}).get('status') in ('ready','rejected','gave_up') for key in keys):
                progress.update(status='already_completed',logical_input_sha256=logical,
                                authority=copy.deepcopy(revision),training_admission=False)
                job._save()
                return
            kwargs=dict(export_root=export,fetch_current=fetch,workspace_id=revision['workspace_id'],
                previous_authority=revision,authority_max_age_s=self.authority_max_age_s,now=self.now,
                eval_folders=folders,gate_eval_refs=[{'name':evaluation.parent.name,'content_sha':evaluation.name}],
                source_proof_files=self.source_proof_files,store=store,name=self.dataset_name,
                staging_parent=self.staging_parent)
            if self.eval_companion_files:kwargs['eval_companion_files']=self.eval_companion_files
            report=build_dataset(**kwargs)
            progress['build']=report
            if report.get('status') != 'PUBLISHED_CONTENT_NOT_ADMITTED':
                raise JobError('indexed build held: '+ '; '.join(report.get('blockers',[])))
            if _signature(config) != config_sha:
                raise JobError('cycle config changed during indexed build')
            if self._logical_key(current,folders,encoded)!=logical:
                raise JobError('logical source/eval inputs changed during indexed build')
            ref=self.dataset_name+'@'+report['dataset_revision']
            cfg={**config['trainer'],'dataset':ref,'training':config['recipes'][0]}
            owner=self._context(config,job,export)
            with owner.open(cfg,Path(report['dataset_path']),evaluation,[],
                            expected_file_hashes=bindings) as admitted:
                request={'dataset':ref,'purpose':'research'}
                raw=(json.dumps(request,sort_keys=True)+'\n').encode()
                target=Path(config['requests_dir'])/(_signature(request)+'.json')
                if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction())
                       for p in [target,*target.parents]):
                    raise JobError('request links refused')
                target.parent.mkdir(parents=True,exist_ok=True)
                # Cycle Job holds its writer lock. Hard-link publication is atomic
                # and exclusive, so an existing immutable request cannot be replaced.
                with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.request-',delete=False) as stream:
                    temporary=Path(stream.name)
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                try:
                    self.check_settings()
                    if _signature(config)!=config_sha:raise JobError('cycle config changed before request')
                    if self._logical_key(current,folders,encoded)!=logical:
                        raise JobError('logical source/eval inputs changed before request')
                    if temporary.read_bytes()!=raw:raise JobError('staged request changed')
                    admitted.check()
                    try:os.link(temporary,target)
                    except FileExistsError:
                        if _stable_bytes(target)!=raw:raise JobError('immutable request differs')
                finally:temporary.unlink(missing_ok=True)
            progress.update(status='request_published',request_path=str(target),dataset=ref,
                            authority=copy.deepcopy(revision),logical_input_sha256=logical,
                            training_admission=False)
            job.state.setdefault('review_pipeline_dataset_keys',{})[ref]=logical
        except (ValueError,OSError,KeyError,TypeError) as exc:
            progress.update(status='held',blockers=[str(exc)],training_admission=False)
        job._save()

    def for_dataset(self, config, job, ref):
        """Reconstruct matching sealed export context on every request/restart."""
        self.check_settings()
        bindings=job.state.get('review_pipeline_input_bindings')
        if (not isinstance(bindings,dict) or any(hashlib.sha256(_stable_bytes(Path(path))).hexdigest()!=digest
                for path,digest in bindings.items())):
            raise JobError('owner gate/camera bindings unavailable or changed')
        store=Store(config['trainer']['store'])
        manifest=json.loads(_stable_bytes(store.dataset_path(*parse_dataset_ref(ref))/'manifest.json'))
        sources=manifest.get('sources',[])
        if not isinstance(sources,list) or not sources:
            raise JobError('indexed dataset source binding required')
        seals={row.get('export_contract_sha256') for row in sources}
        if len(seals)!=1 or None in seals:
            raise JobError('indexed dataset export binding differs')
        for export in sorted(Path(config['reviews_dir']).glob('*')):
            seal=export/'AUTHORITY_COMPLETE'
            if seal.is_file() and _stable_bytes(seal).decode().strip() in seals:
                return self._context(config,job,export)
        raise JobError('indexed dataset original sealed export unavailable')


def main():
    """Explicit trusted-owner entrypoint, separate from the default cycle CLI."""
    import argparse
    from learning_cycle import run_once
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    parser.add_argument('--out',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    config=json.loads(_stable_bytes(args.config))
    if set(config)!={'cycle','review'} or not isinstance(config['review'],dict):
        raise JobError('trusted owner config needs cycle and review sections')
    settings=config['review']
    required={'source_proof_files','staging_parent','dataset_name'}
    if not required <= set(settings) or set(settings)-required-{'eval_companion_files','authority_max_age_s'}:
        raise JobError('explicit owner source/staging/name settings required')
    owner=ReviewPipeline(**settings)
    while True:
        state=run_once(config['cycle'],args.out,review_pipeline=owner)
        print(json.dumps({'review_autobuild':state.get('review_autobuild'),
                          'cycles':{k:v['status'] for k,v in state.get('cycles',{}).items()}}),flush=True)
        if args.once:return
        time.sleep(config['cycle']['interval_s'])


if __name__=='__main__':main()
