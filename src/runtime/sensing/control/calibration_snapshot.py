"""Read a context-bound calibration before constructing a ROS consumer.

Digest validation detects corruption; the caller supplies trusted device and
activation context. Parameter readback is not acknowledgement of motor policy.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .calibration_record import MAX_BYTES, decode_record, runtime_calibration_path
from .calibration_storage import _parameters


@dataclass(frozen=True)
class CalibrationSnapshot:
    revision: int
    digest: str
    _parameters_json: str

    def node_parameters(self, name):
        """Resolve device-local selectors; never infer a missing node owner."""
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('Calibration consumer requires a bare ROS node name')
        document = json.loads(self._parameters_json)
        owners = [key for key in (name, '/**/' + name) if key in document]
        if len(owners) != 1:
            raise ValueError('Calibration node is missing or has ambiguous selectors')
        values = dict(document.get('/**', {}).get('ros__parameters', {}))
        values.update(document[owners[0]]['ros__parameters'])
        if not values:
            raise ValueError('Calibration consumer has no parameters')
        return values

    def verify_parameters(self, node):
        """Check declared ROS values; return no policy-adoption acknowledgement."""
        values = self.node_parameters(node.get_name())
        for key, expected in values.items():
            if not node.has_parameter(key):
                raise ValueError('Calibration parameter was not declared: ' + key)
            actual = node.get_parameter(key).value
            if isinstance(expected, list):
                actual = list(actual) if actual is not None else None
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError('Calibration parameter readback mismatch: ' + key)


def load_calibration_snapshot(destination, expected_context, active_generation,
                              data_root='/var/lib/rosy'):
    """Load one bounded atomic-file snapshot from the current robot generation."""
    path = runtime_calibration_path(destination, expected_context, active_generation, data_root)
    with Path(path).open('rb') as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError('Calibration record exceeds size limit')
    metadata, document = decode_record(payload.decode('utf-8'), expected_context)
    _parameters(document)
    for selector, settings in document.items():
        if selector != '/**' and not re.fullmatch(r'(?:/\*\*/)?[A-Za-z_][A-Za-z0-9_]*', selector):
            raise ValueError('Unsupported device-local calibration selector')
        if set(settings) != {'ros__parameters'}:
            raise ValueError('Unsupported calibration node settings')
    return CalibrationSnapshot(metadata['revision'], metadata['digest'],
                               json.dumps(document, allow_nan=False))
