"""D-792 S3 first slice: approved camera-setup references at OMX intake are checked and recorded by revision.

Frames are not compared yet. Only ``{role: revision}`` leaves this module: ``camera_identity`` may hold
a device serial and reference paths are site data.
"""
import json
from pathlib import Path
import re
import sys

PREFIX = 'observation.images.'


def parse(values):
    """Repeated ``ROLE=PATH`` CLI values -> ``{role: Path}``; a role given twice is refused."""
    references = {}
    for value in values or ():
        role, separator, path = value.partition('=')
        if not separator or not role or not path:
            raise ValueError('--camera-reference takes ROLE=PATH')
        if role in references:
            raise ValueError(f'camera role given twice: {role}')
        references[role] = Path(path)
    return references


def load(references):
    """``{role: path}`` -> ``{role: sealed reference}``; the file stem must equal its revision."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'contracts/learning/src'))
    from rosy.contracts.learning.camera_setup import validate_reference
    documents = {}
    for role, path in sorted(references.items()):
        document = validate_reference(json.loads(Path(path).read_text(encoding='utf-8')))
        if Path(path).stem != document['revision']:
            raise ValueError(f'camera reference {role}: file name differs from its revision')
        if document['camera_role'] != role:
            raise ValueError(f'camera reference {role}: reference is for role {document["camera_role"]}')
        documents[role] = document
    return documents


def bind(documents, info):
    """Sealed references against the dataset's meta/info.json -> ``{role: revision}``."""
    features = {key[len(PREFIX):]: value for key, value in info.get('features', {}).items() if key.startswith(PREFIX)}
    if set(documents) != set(features):
        raise ValueError(f'camera references {sorted(documents)} differ from dataset cameras {sorted(features)}')
    for role, document in documents.items():
        names, shape = features[role].get('names'), features[role].get('shape')
        # LeRobot names the axes (height, width, channels); read them by name, not by position.
        if (not isinstance(names, list) or not isinstance(shape, list) or len(names) != len(shape)
                or not {'height', 'width'} <= set(names)):
            raise ValueError(f'dataset camera {role} has no named height and width')
        actual = (shape[names.index('width')], shape[names.index('height')], info.get('fps'))
        if actual != (document['width'], document['height'], document['fps']):
            raise ValueError(f'camera reference {role} differs from the dataset width, height or fps')
    return {role: documents[role]['revision'] for role in sorted(documents)}


def recorded(value, camera_keys):
    """A recorded ``{role: revision}`` must name exactly the dataset cameras."""
    if (not isinstance(value, dict) or sorted(PREFIX + role for role in value) != sorted(camera_keys)
            or not all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in value.values())):
        raise ValueError('camera_setup must map every dataset camera to one sha256 revision')
    return dict(sorted(value.items()))
