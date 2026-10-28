"""D-792 S3: shadow camera setup checks for real OMX episodes, run on the model PC at intake.

The recording host never sees the references (they live in the review app state), so each
selected episode is checked here from its own first (before) and last (after) recorded frame.
Shadow only: the result is evidence beside the dataset and never blocks intake or training.
"""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_ROOT / 'learning/curation/perception'), str(_ROOT / 'contracts/learning/src')]
import camera_setup  # noqa: E402
from rosy.contracts.learning.camera_setup import validate_reference, validate_setup  # noqa: E402
from rosy.contracts.learning.omx import WRIST, camera_role  # noqa: E402

SCHEMA = 'rosy.omx-camera-setup-intake/1'


def load_reference(path):
    """A reference JSON with its same-named still (as stored by the review app); both bytes are verified."""
    path = Path(path)
    doc = validate_reference(json.loads(path.read_text(encoding='utf-8')))
    raw = path.with_suffix('.jpg').read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc['reference_still']:
        raise ValueError('reference still does not match its reference')
    still = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if still is None:
        raise ValueError('reference still could not be decoded')
    return doc, still


def camera_info_fingerprints(blobs):
    """Role -> sha256 of a model that stays unchanged throughout the recording.

    Copy this value into a reference's ``camera_info_sha256`` so later checks can match it."""
    text = blobs.get('camera_info.jsonl', b'').decode('utf-8')
    models = [json.loads(line)['cameras'] for line in text.splitlines() if line.strip()]
    first = models[0] if models else {}
    # shortcut: changed calibration is unmeasurable session-wide; select by frame time if per-episode models are needed.
    return {role: hashlib.sha256(json.dumps(model, sort_keys=True, allow_nan=False).encode()).hexdigest()
            for role, model in first.items() if all(other.get(role) == model for other in models)}


def _check(frame, reference, still, fingerprint, joints):
    try:
        return camera_setup.check(frame, reference, fingerprint, still, joints)
    except ValueError:  # e.g. a wrist reference with no recorded joint readback
        return camera_setup.unmeasurable(reference['method'], 0)


def episode_checks(record, episode, references, joint_names):
    """Role -> validated shadow setup record for one selected episode of a validated session."""
    rows = record['samples'][episode['episode_index']]
    shapes = record['manifest']['camera_shapes']
    fingerprints = camera_info_fingerprints(record['blobs'])
    result = {}
    for role, (reference, still) in references.items():
        if role not in shapes:
            raise ValueError(f'reference role {role} is not a recorded camera')
        if camera_role(reference['camera_role']) != camera_role(role):
            raise ValueError('reference camera role differs from the recorded camera')
        if camera_role(role) == WRIST and reference['check_pose'] is None:
            raise ValueError('wrist reference requires a check pose')

        def measure(row):
            rgb = np.frombuffer(record['blobs'][row['images'][role]['path']], np.uint8).reshape(shapes[role])
            positions = row.get('joint_positions_rad')
            joints = dict(zip(joint_names, positions)) if positions is not None else None
            return _check(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), reference, still, fingerprints.get(role), joints)

        result[role] = validate_setup(dict(reference_revision=reference['revision'], before=measure(rows[0]),
                                           after=measure(rows[-1]), mode='shadow'))
    return result


def report(records, episodes, references):
    """The ``camera-setup.json`` document: one reference revision per role for the whole prepared set."""
    first = records[0]['blobs']
    profile = json.loads(first['profile.json'])
    return dict(schema=SCHEMA, mode='shadow',
                references={role: doc['revision'] for role, (doc, _) in references.items()},
                camera_info_sha256=camera_info_fingerprints(first),
                episodes=[dict(episode_index=i, session_id=r['manifest']['session_id'],
                               checks=episode_checks(r, e, references, profile.get('joint_names', [])))
                          for i, (r, e) in enumerate(episodes)])
