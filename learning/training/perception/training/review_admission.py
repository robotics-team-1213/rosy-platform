"""D-464 owner-injected indexed admission; never a portable receipt or CLI grant.

The owner supplies the existing transport's trusted workspace/highwater and the
original sealed export. Reconstruct against source pixels and all active evals,
then require exact stored content equality. No actual store publication occurs.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from job_state import JobError
from store import Store, content_sha, file_hashes, parse_dataset_ref
from review_dataset import build_dataset, _delivery, _stable_bytes, _capture_proofs, validate_eval_companions


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _extended_path(path):
    path = Path(path)
    if os.name != 'nt':
        return path
    value = str(path.absolute())
    if value.startswith('\\\\?\\'):
        return path
    if value.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + value[2:])
    return Path('\\\\?\\' + value)


def _snapshot(root, target):
    """Capture only verified hashed bytes, rejecting links and copy-time changes."""
    root = Path(root)
    target = Path(target)
    if os.name == 'nt':
        # Captured companion evidence nests content hashes under a private
        # snapshot. Preserve every file through Win32's extended path form;
        # never shorten/drop evidence or relax the content check.
        root, target = _extended_path(root), _extended_path(target)
    expected = file_hashes(root)
    target.mkdir(parents=True)
    for relative, digest in expected.items():
        raw = _stable_bytes(root / relative)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise JobError('indexed input changed during snapshot')
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    if content_sha(target) != root.name or file_hashes(root) != expected:
        raise JobError('indexed snapshot content differs from version')
    return target


class _AuditStore(Store):
    """Use the real store eval inventory but keep reconstruction in scratch."""
    def __init__(self, root, expected_name, expected_sha):
        super().__init__(root)
        self.expected_name, self.expected_sha = expected_name, expected_sha

    def put_dataset(self, source, name):
        digest = content_sha(source)
        if name != self.expected_name or digest != self.expected_sha:
            raise ValueError('reconstructed indexed content differs from stored dataset')
        return Path(source), digest


class IndexedReview:
    """Trusted owner context, not deserialized from a training config or receipt.

    previous_authority must come from the transport's persisted trusted ledger,
    not an empty new Job state. The default train_job CLI never creates this.
    """
    def __init__(self, *, export_root, fetch_current, workspace_id, source_proof_files,
                 staging_parent, previous_authority, authority_max_age_s=90, now=time.time,
                 eval_companion_files=()):
        self.export_root = Path(export_root)
        self.fetch_current = fetch_current
        self.workspace_id = workspace_id
        self.source_proof_files = tuple(source_proof_files)
        self.eval_companion_files = tuple(eval_companion_files)
        self.staging_parent = Path(staging_parent)
        self.previous_authority = copy.deepcopy(previous_authority)
        self.authority_max_age_s = authority_max_age_s
        self.now = now

    @contextmanager
    def open(self, config, dataset, evaluation, source_files, *, expected_file_hashes=None):
        """Verify before Job and supply private captured train/intake inputs."""
        if (not isinstance(self.previous_authority, dict)
                or set(self.previous_authority) != {'workspace_id', 'generation', 'decision_sha256'}):
            raise JobError('persisted trusted authority highwater required')
        if (type(self.authority_max_age_s) not in (int, float)
                or not math.isfinite(self.authority_max_age_s)
                or not 0 < self.authority_max_age_s <= 90):
            raise JobError('bounded indexed admission freshness required')
        session = _Session(self, config, Path(dataset), Path(evaluation), source_files, expected_file_hashes)
        session.check()
        # Reconstruction validates configured scratch placement/links first.
        with tempfile.TemporaryDirectory(prefix='indexed-admission-', dir=_extended_path(self.staging_parent)) as temp:
            root = Path(temp)
            session.dataset = _snapshot(dataset, root / 'datasets' / Path(dataset).name)
            evaluations = {path: _snapshot(path, root / 'evalsets' / path.parent.name / path.name)
                           for path in session.eval_folders}
            gate = json.loads(json.dumps(session.gate_doc))
            gate['eval_set'] = str(evaluations[session.evaluation])
            session.gate_path = root / 'gate.json'
            session.gate_path.write_text(json.dumps(gate, sort_keys=True), encoding='utf-8')
            session._snapshot_gate_sha = hashlib.sha256(session.gate_path.read_bytes()).hexdigest()
            session._eval_snapshots = evaluations
            session.check()  # copy/decode duration may expire or revoke authority
            yield session


class _Session:
    def __init__(self, owner, config, dataset, evaluation, source_files, expected_file_hashes):
        import yaml
        self.owner, self.config = owner, config
        self.original_dataset = dataset.absolute()
        self.evaluation = evaluation.absolute()
        self.dataset, self.gate_path = None, None
        self._eval_snapshots = {}
        self.config_sha = _hash(config)
        self.paths = [Path(config['gate']).resolve(), Path(config['camera_profile']).resolve(),
                      *(Path(path).resolve() for path in source_files)]
        self.bindings = {path: _stable_bytes(path) for path in self.paths}
        if expected_file_hashes is not None:
            expected = {Path(path).resolve(): digest for path, digest in expected_file_hashes.items()}
            if {path: hashlib.sha256(raw).hexdigest() for path, raw in self.bindings.items()} != expected:
                raise JobError('validated gate/camera/trainer bytes changed before admission capture')
        self.gate_doc = yaml.safe_load(self.bindings[Path(config['gate']).resolve()])
        from intake_eval_gate import _eval_gate_error
        if self.gate_doc.get('require_eval') is not True or _eval_gate_error(self.gate_doc):
            raise JobError('valid required evaluation gate needed for admission')
        self.name, self.dataset_sha = parse_dataset_ref(config['dataset'])
        self.store = _AuditStore(config['store'], self.name, self.dataset_sha)
        self.eval_folders = tuple(sorted(self.store.evalset_path(name, digest).absolute()
            for name, versions in self.store.evalsets().items() for digest in versions))
        if self.evaluation not in self.eval_folders:
            raise JobError('gate evaluation must be in the complete actual store inventory')
        self.gate_refs = [dict(name=self.evaluation.parent.name, content_sha=self.evaluation.name)]
        try:
            _, observed = _capture_proofs(owner.source_proof_files)
            self.review_input_hashes = {path: hashlib.sha256(raw).hexdigest()
                                       for path,raw in observed.items()}
            if owner.eval_companion_files:
                companion = validate_eval_companions(self.eval_folders,owner.eval_companion_files)
                self.review_input_hashes.update({path:hashlib.sha256(raw).hexdigest()
                    for path,raw in companion['observed'].items()})
        except (ValueError,OSError,KeyError,TypeError) as exc:
            raise JobError('indexed source/eval capture denied: '+str(exc)) from exc
        self.bound_authority = None

    @property
    def evidence(self):
        return dict(dataset_sha=self.dataset_sha, authority=copy.deepcopy(self.bound_authority),
                    config_sha=self.config_sha, eval_refs=[dict(name=p.parent.name, content_sha=p.name)
                    for p in self.eval_folders])

    def _check_inputs(self):
        if _hash(self.config) != self.config_sha:
            raise ValueError('training config/recipe changed after admission')
        if any(_stable_bytes(path) != raw for path, raw in self.bindings.items()):
            raise ValueError('gate/camera/trainer source changed after admission')
        if any(hashlib.sha256(_stable_bytes(path)).hexdigest()!=digest
               for path,digest in self.review_input_hashes.items()):
            raise ValueError('source/eval proof artifacts changed after admission')
        if content_sha(self.original_dataset) != self.dataset_sha:
            raise ValueError('stored dataset changed after admission')
        actual_evals = tuple(sorted(self.store.evalset_path(name, digest).absolute()
            for name, versions in self.store.evalsets().items() for digest in versions))
        if actual_evals != self.eval_folders or any(content_sha(path) != path.name for path in actual_evals):
            raise ValueError('active evaluation inventory/content changed after admission')
        if self.dataset is not None and content_sha(self.dataset) != self.dataset_sha:
            raise ValueError('captured training dataset changed after admission')
        if self.gate_path is not None and hashlib.sha256(_stable_bytes(self.gate_path)).hexdigest() != self._snapshot_gate_sha:
            raise ValueError('captured gate changed after admission')
        if any(content_sha(path) != original.name for original, path in self._eval_snapshots.items()):
            raise ValueError('captured evaluation changed after admission')

    def check(self):
        """No cached boolean grant: reconstruct and recheck freshness each time."""
        try:
            self._check_inputs()
            current, revision = _delivery(self.owner.fetch_current, self.owner.workspace_id,
                self.owner.previous_authority, self.owner.authority_max_age_s, self.owner.now)
            # Retain highwater even if a later reconstruction fails.
            self.owner.previous_authority = copy.deepcopy(revision)
            if self.bound_authority is not None and revision != self.bound_authority:
                raise ValueError('authority changed after trainer admission')
            report = build_dataset(self.owner.export_root, fetch_current=self.owner.fetch_current,
                workspace_id=self.owner.workspace_id, previous_authority=revision,
                authority_max_age_s=self.owner.authority_max_age_s, now=self.owner.now,
                eval_folders=self.eval_folders, gate_eval_refs=self.gate_refs,
                source_proof_files=self.owner.source_proof_files, store=self.store, name=self.name,
                staging_parent=self.owner.staging_parent,
                eval_companion_files=self.owner.eval_companion_files)
            if (report.get('status') != 'PUBLISHED_CONTENT_NOT_ADMITTED'
                    or report.get('dataset_revision') != self.dataset_sha
                    or report.get('authority') != revision):
                raise ValueError('indexed reconstruction denied: ' + '; '.join(report.get('blockers', [])))
            final_receipt = []
            def final_fetch():
                value = self.owner.fetch_current()
                final_receipt.append(copy.deepcopy(value))
                return value
            latest, final = _delivery(final_fetch, self.owner.workspace_id,
                revision, self.owner.authority_max_age_s, self.owner.now)
            self.owner.previous_authority = copy.deepcopy(final)
            if latest != current:
                raise ValueError('authority changed or expired after slow source verification')
            self._check_inputs()
            # Hash/copy verification may itself take longer than the TTL.
            age = self.owner.now() - final_receipt[-1]['checked_at_unix']
            if not -5 <= age <= self.owner.authority_max_age_s:
                raise ValueError('authority expired during final input verification')
            self.bound_authority = copy.deepcopy(revision)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise JobError('independent indexed review training admission denied: ' + str(exc)) from exc
