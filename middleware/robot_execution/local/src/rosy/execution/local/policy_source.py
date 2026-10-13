"""Capture installed file bytes; no inference-consumption or execution grant."""
from dataclasses import fields
import hashlib
import inspect
import json

from omx_adapter.command_owner import ArmCommandOwner
from .policy_journal import _json


def capture_source(policy, owner):
    doc = policy.recheck()
    payloads = {'policy/policy-artifact.json': policy._manifest}
    references = doc['files'] + [doc['normalization']] + doc['evaluations']
    for ref in references:
        key = 'policy/' + ref['path']
        raw = (policy.root / ref['path']).read_bytes()
        if len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('installed file changed while capturing source')
        if key in payloads and payloads[key] != raw:
            raise ValueError('conflicting installed source references')
        payloads[key] = raw
    source_path = inspect.getfile(ArmCommandOwner)
    from pathlib import Path
    controller = Path(source_path).read_bytes()
    config = _json(owner.config).encode('utf-8')
    expected_owner = dict(kind='omx_local_controller',
                          controller_revision='sha256:' + hashlib.sha256(controller).hexdigest(),
                          envelope_revision='sha256:' + hashlib.sha256(config).hexdigest())
    if doc['owner'] != expected_owner:
        raise ValueError('captured controller/config differs from installed binding')
    binding = {f.name: getattr(policy.binding, f.name) for f in fields(policy.binding)
               if not f.name.startswith('_')}
    binding.update(owner=policy.binding.owner, cameras=policy.binding.cameras, timing=policy.binding.timing)
    payloads.update({'owner/controller.py': controller, 'owner/config.json': config,
                     'installed/binding.json': _json(binding).encode('utf-8')})
    if (policy.recheck() != doc or Path(source_path).read_bytes() != controller
            or _json(owner.config).encode('utf-8') != config):
        raise ValueError('installed source changed during capture')
    header = dict(policy_revision=doc['revision'], owner=doc['owner'], environment='sim',
                  scope='installed file snapshot; resident bytecode and inference consumption not proven',
                  files=[dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                         for path, raw in sorted(payloads.items())])
    return header, payloads
