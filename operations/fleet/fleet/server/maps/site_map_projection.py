"""Bounded STL background projection (D-825); no road or robot-frame inference."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys

from core_common.protocol.site_drawing import DrawingTransform

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TRIANGLES = 200_000
MAX_SEGMENTS = 50_000
MAX_PROJECTION_BYTES = 8 * 1024 * 1024
CONVERTER_VERSION = 'rosy.stl_projection/1'


class DrawingLimitError(ValueError):
    """A valid-looking input exceeds the explicit conversion budget."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _finite(values):
    if not all(math.isfinite(v) for v in values):
        raise ValueError('STL coordinates and normals must be finite')
    return values


def _ascii_triangles(data):
    # STL grammar: https://www.loc.gov/preservation/digital/formats/fdd/fdd000506.shtml
    try:
        lines = iter(line.strip().split() for line in data.decode('ascii').splitlines() if line.strip())
        count = 0
        while (line := next(lines, None)) is not None:
            if line[0] != 'solid':
                raise ValueError('expected solid')
            while True:
                line = next(lines)
                if line[0] == 'endsolid':
                    break
                if len(line) != 5 or line[:2] != ['facet', 'normal']:
                    raise ValueError('expected facet normal')
                _finite(tuple(map(float, line[2:])))
                if next(lines) != ['outer', 'loop']:
                    raise ValueError('expected outer loop')
                points = []
                for _ in range(3):
                    vertex = next(lines)
                    if len(vertex) != 4 or vertex[0] != 'vertex':
                        raise ValueError('expected vertex')
                    points.append(_finite(tuple(map(float, vertex[1:]))))
                if next(lines) != ['endloop'] or next(lines) != ['endfacet']:
                    raise ValueError('expected endloop/endfacet')
                count += 1
                if count > MAX_TRIANGLES:
                    raise DrawingLimitError('too many STL triangles')
                yield points
        if not count:
            raise ValueError('STL contains no triangles')
    except (UnicodeError, StopIteration, OverflowError) as exc:
        raise ValueError('incomplete ASCII STL') from exc


def _triangles(data):
    count = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else 0
    if len(data) >= 84 and len(data) == 84 + 50 * count:
        if count > MAX_TRIANGLES:
            raise DrawingLimitError('too many STL triangles')
        if not count:
            raise ValueError('STL contains no triangles')
        def binary():
            for offset in range(84, len(data), 50):
                values = _finite(struct.unpack_from('<12fH', data, offset)[:12])
                yield [values[3:6], values[6:9], values[9:12]]
        return 'binary_stl', binary()
    return 'ascii_stl', _ascii_triangles(data)


def _read(path):
    with Path(path).open('rb') as source:
        data = source.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise DrawingLimitError('STL source exceeds 16 MiB')
    return data


def _bounds(points, dimensions):
    low, high = [math.inf] * dimensions, [-math.inf] * dimensions
    for point in points:
        for axis in range(dimensions):
            low[axis], high[axis] = min(low[axis], point[axis]), max(high[axis], point[axis])
    return [low, high]


def inspect_stl(path: Path) -> dict:
    data = _read(path)
    format_name, triangles = _triangles(data)
    count = 0
    def points():
        nonlocal count
        for triangle in triangles:
            count += 1
            yield from triangle
    bounds = _bounds(points(), 3)
    return {'asset_sha256': hashlib.sha256(data).hexdigest(), 'format': format_name,
            'triangle_count': count, 'bounds_3d': bounds}


def project_stl(path: Path, transform: DrawingTransform) -> dict:
    data = _read(path)
    _, triangles = _triangles(data)
    axes = {'xy': (0, 1), 'xz': (0, 2), 'yz': (1, 2)}[transform.plane]
    scale = {'m': 1, 'cm': .01, 'mm': .001}[transform.unit] * transform.scale
    cosine, sine = math.cos(transform.heading_rad), math.sin(transform.heading_rad)
    def project(point):
        x = (point[axes[0]] - transform.source_origin[0]) * scale
        y = (point[axes[1]] - transform.source_origin[1]) * scale
        result = (transform.map_origin_m[0] + cosine * x - sine * y,
                  transform.map_origin_m[1] + sine * x + cosine * y)
        if any(not math.isfinite(v) or abs(v) > 1000 for v in result):
            raise ValueError('projected coordinates exceed the site map bounds')
        return tuple(0.0 if v == 0 else v for v in result)
    segments = set()
    for triangle in triangles:
        a, b, c = map(project, triangle)
        for start, end in ((a, b), (b, c), (c, a)):
            if start != end:
                segments.add(tuple(sorted((start, end))))
            if len(segments) > MAX_SEGMENTS:
                raise DrawingLimitError('too many projected segments')
    if not segments:
        raise ValueError('projection contains no visible segments')
    ordered = sorted(segments)
    result = {'asset_sha256': hashlib.sha256(data).hexdigest(),
              'transform': transform.model_dump(mode='json'),
              'bounds_m': _bounds((p for s in ordered for p in s), 2),
              'segments': [[list(a), list(b)] for a, b in ordered]}
    payload = canonical({'version': CONVERTER_VERSION, **result})
    if len(payload) > MAX_PROJECTION_BYTES - 100:
        raise DrawingLimitError('projection JSON exceeds 8 MiB')
    return {'projection_sha256': hashlib.sha256(payload).hexdigest(), **result}


def main():
    """One request per worker; the parent owns wall timeout and process cleanup."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
        request = json.load(sys.stdin)
        path = Path(request['path'])
        result = (inspect_stl(path) if request['operation'] == 'inspect' else
                  project_stl(path, DrawingTransform.model_validate(request['transform'])))
        sys.stdout.buffer.write(canonical({'result': result}))
    except DrawingLimitError as exc:
        sys.stdout.buffer.write(canonical({'error': 'limit', 'detail': str(exc)}))
    except (ValueError, OSError, KeyError, MemoryError) as exc:
        sys.stdout.buffer.write(canonical({'error': 'invalid', 'detail': str(exc)}))


if __name__ == '__main__':
    main()
