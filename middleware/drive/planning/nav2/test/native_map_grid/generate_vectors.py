"""Run on the ROS test host; use the original CORE Python byte contract."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import struct
import sys


def main():
    root = Path(__file__).resolve().parents[6]
    source = root / 'middleware/drive/behaviors/navigation/map_evidence.py'
    spec = importlib.util.spec_from_file_location('original_map_evidence', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # OccupancyGrid resolution is float32, promoted before canonical double packing.
    resolution = struct.unpack('<f', struct.pack('<f', .05))[0]
    base = module.GridContent('map', 3, 2, resolution,
                              (-1.25, 2.5, 0., 0., 0., 0., 1.),
                              (-1, 0, 1, 49, 100, -1), 20, 10)
    vectors = {
        'base': base,
        'signed_zero': replace(base, origin=(-0., 2.5, 0., 0., 0., 0., 1.)),
        'positive_zero': replace(base, origin=(0., 2.5, 0., 0., 0., 0., 1.)),
        'quaternion_sign': replace(base, origin=(*base.origin[:6], -1.)),
        'equal_conversion': replace(base, data=(-1, 0, 49, 49, 100, -1)),
        'time_only': replace(base, stamp_ns=21),
        'static_zero_time': replace(base, stamp_ns=0, load_time_ns=0),
    }
    for name, content in vectors.items():
        print(name, module.content_digest(content), sep='\t')


if __name__ == '__main__':
    main()
