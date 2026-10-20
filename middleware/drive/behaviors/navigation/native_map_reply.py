"""Bounded robot-internal native map values; never admission or a stability lease."""
from dataclasses import dataclass, fields
import math
import struct

from core_features.navigation.map_evidence import MAX_CELLS


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def real(value):
    return type(value) in (int, float) and (finite(value) or finite(-value))


def text(value, limit):
    try:
        return type(value) is str and len(value) <= limit and len(value.encode('utf-8')) <= limit
    except UnicodeError:
        return False


def digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def fixed(value, count, format):
    if type(value) in (list, tuple):
        if len(value) != count:
            raise ValueError('invalid fixed native array length')
        result = tuple(value)
    else:
        try:
            view = memoryview(value)
        except TypeError as error:
            raise ValueError('invalid fixed native array') from error
        if view.ndim != 1 or not view.c_contiguous or len(view) != count or view.format != format:
            raise ValueError('invalid fixed native array shape/type')
        result = tuple(view)  # ndarray scalars become exact Python primitives.
    if format == 'B' and any(type(v) is not int or not 0 <= v <= 255 for v in result):
        raise ValueError('invalid native byte values')
    return result


@dataclass(frozen=True, eq=False)
class Consumer:
    role: str
    node_fqn: str
    build_id: str
    config_digest: str
    provider: object

    def __post_init__(self):
        if (type(self.role) is not str or self.role not in ('amcl', 'static_layer')
                or not text(self.node_fqn, 256) or len(self.node_fqn) <= 1
                or not self.node_fqn.startswith('/') or self.node_fqn != self.node_fqn.strip()
                or not digest(self.build_id) or not digest(self.config_digest) or self.provider is None):
            raise ValueError('exact native consumer profile/provider required')


@dataclass(frozen=True, eq=False)
class NativeReply:
    contract_version: int
    challenge: bytes
    instance_id: bytes
    generation: int
    active: bool
    adopted: bool
    reason: str
    role: str
    node_fqn: str
    build_id: str
    config_digest: str
    grid_digest: str
    frame_id: str
    width: int
    height: int
    resolution: float
    origin: tuple
    source_stamp_ns: int
    map_load_time_ns: int

    @classmethod
    def capture(cls, message):
        """Copy generated-message primitives outside the owner's lock, bounded first."""
        values = {field.name: getattr(message, field.name) for field in fields(cls)}
        for name in ('challenge', 'instance_id'):
            values[name] = bytes(fixed(values[name], 16, 'B'))
        values['origin'] = fixed(values['origin'], 7, 'd')
        result = cls(**values)
        if not result.bounded():
            raise ValueError('invalid native readback shape')
        return result

    def bounded(self):
        strings = ((self.reason, 64), (self.role, 32), (self.node_fqn, 256),
            (self.build_id, 64), (self.config_digest, 64), (self.grid_digest, 64), (self.frame_id, 128))
        return (all(text(v, limit) for v, limit in strings)
            and type(self.contract_version) is int and 0 <= self.contract_version < 2**16
            and all(type(v) is bytes and len(v) == 16 for v in (self.challenge, self.instance_id))
            and type(self.generation) is int and 0 <= self.generation < 2**64
            and type(self.active) is bool and type(self.adopted) is bool
            and all(type(v) is int and 0 <= v < 2**32 for v in (self.width, self.height))
            and real(self.resolution)
            and type(self.origin) is tuple and len(self.origin) == 7
            and all(real(v) for v in self.origin)
            and all(type(v) is int and 0 <= v < 2**64 for v in (self.source_stamp_ns, self.map_load_time_ns)))

    def matches(self, consumer, nonce, original):
        return (self.bounded() and self.contract_version == 1 and self.challenge == nonce
            and self.active and self.adopted and self.reason == 'adopted' and any(self.instance_id)
            and self.generation > 0 and self.role == consumer.role and self.node_fqn == consumer.node_fqn
            and self.build_id == consumer.build_id and self.config_digest == consumer.config_digest
            and self.grid_digest == original.digest and digest(self.grid_digest)
            and self.frame_id == original.frame == 'map'
            and (self.width, self.height) == (original.width, original.height)
            and 0 < self.width*self.height <= MAX_CELLS and self.resolution > 0
            and self.origin[2:6] == (0., 0., 0., 0.) and self.origin[6] in (-1., 1.)
            and struct.pack('<8d', self.resolution, *self.origin)
                == struct.pack('<8d', original.resolution, *original.origin)
            and (self.source_stamp_ns, self.map_load_time_ns) == (original.stamp_ns, original.load_time_ns))

    @property
    def signature(self):
        return (self.role, self.node_fqn, self.instance_id, self.generation, self.build_id, self.config_digest)
