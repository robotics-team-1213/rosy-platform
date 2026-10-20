"""Same-SHA generated deserialize -> domain capture. Synthetic data, not native ACK."""
from pathlib import Path
import hashlib
from uuid import uuid4

import numpy as np
from interfaces.srv import MapAdoption
from rclpy.serialization import deserialize_message, serialize_message

from core_features.navigation import native_map_reply
from core_features.navigation.map_evidence import MapEvidence, GridContent
from core_features.navigation.native_map_adoption import Consumer, NativeMapEvidence
from core_features.navigation.native_map_reply import NativeReply


def main():
    root = Path.cwd()
    source = root / 'middleware/drive/behaviors/navigation/native_map_reply.py'
    loaded = Path(native_map_reply.__file__).resolve()
    assert loaded == source.resolve()
    print('same-SHA domain converter:', loaded, hashlib.sha256(loaded.read_bytes()).hexdigest())
    raw = MapEvidence(robot_id='wire-only', boot_id=uuid4())
    token = raw.begin(20, 10)
    assert raw.complete(token, GridContent('map', 2, 1, .05,
        (-1., 2., 0., 0., 0., 0., 1.), (0, 100), 20, 10))
    observation = raw.snapshot()
    parent, stopped = object(), []
    consumers = tuple(Consumer(role, '/wire/' + role, 'a'*64, 'b'*64, object())
        for role in ('amcl', 'static_layer'))
    owner = NativeMapEvidence(source=lambda: raw, parent=lambda: parent,
        consumers=consumers, clock=lambda: 10., stop=stopped.append)
    round_ = owner.begin()
    for index, consumer in enumerate(consumers, start=1):
        ticket = owner.issue(round_, consumer.role, consumer.provider, bytes([index])*16)
        response = MapAdoption.Response(contract_version=1, challenge=list(ticket.nonce),
            instance_id=[index]*16, generation=1, active=True, adopted=True, reason='adopted',
            role=consumer.role, node_fqn=consumer.node_fqn, build_id=consumer.build_id,
            config_digest=consumer.config_digest, grid_digest=observation.digest,
            frame_id='map', width=2, height=1, resolution=.05, origin=list(observation.origin),
            source_stamp_ns=20, map_load_time_ns=10)
        decoded = deserialize_message(serialize_message(response), MapAdoption.Response)
        for name, dtype, shape in (('challenge', np.uint8, (16,)), ('instance_id', np.uint8, (16,)),
                                  ('origin', np.float64, (7,))):
            field = getattr(decoded, name)
            assert type(field) is np.ndarray and field.dtype == dtype and field.shape == shape
        captured = NativeReply.capture(decoded)
        assert type(captured.challenge) is bytes and type(captured.origin) is tuple
        assert all(type(value) is float for value in captured.origin)
        decoded.challenge[0], decoded.origin[0] = 99, 99.
        assert captured.challenge == ticket.nonce and captured.origin == observation.origin
        assert owner.reply(ticket, consumer.provider, captured)
    assert owner.sample(parent) is not None and not stopped
    closed = MapAdoption.Response(contract_version=1, active=False, adopted=False,
        reason='wire_fixture_not_native_adoption')
    decoded = deserialize_message(serialize_message(closed), MapAdoption.Response)
    assert not NativeReply.capture(decoded).matches(consumers[0], bytes([1])*16, observation)
    print('native_map_capture: two generated response round trips/copies and closed response passed; '
          'synthetic values, no native consumer or motion authority')


if __name__ == '__main__':
    main()
