"""edge_capture.merge_v3: drop lane-model lane, fill 255 with floor/wall, SAM line over non-wall."""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

import edge_capture
from labels import FLOOR, IGNORE_INDEX, LANE, WALL


def _m(shape, *cells):
    m = np.zeros(shape, bool)
    for c in cells:
        m[c] = True
    return m


def test_merge_rule():
    draft = np.array([[LANE, IGNORE_INDEX, IGNORE_INDEX, WALL, FLOOR, IGNORE_INDEX]], np.uint8)
    shape = draft.shape
    floor = _m(shape, (0, 1), (0, 2), (0, 3))
    wall = _m(shape, (0, 2), (0, 4))
    line = _m(shape, (0, 3), (0, 4))
    d = edge_capture.merge_v3(draft, line=line, floor=floor, wall=wall)
    # lane-model lane -> 255 (nothing fills it); 255 -> floor first; LiDAR wall keeps the line out;
    # SAM line paints over LiDAR floor; untouched 255 stays 255.
    assert d.tolist() == [[IGNORE_INDEX, FLOOR, FLOOR, WALL, LANE, IGNORE_INDEX]]
    assert draft[0, 0] == LANE      # input untouched


def test_sam_wall_fill_blocks_the_line():
    draft = np.full((1, 2), IGNORE_INDEX, np.uint8)
    wall, line = _m((1, 2), (0, 0)), _m((1, 2), (0, 0), (0, 1))
    d = edge_capture.merge_v3(draft, line=line, floor=np.zeros((1, 2), bool), wall=wall)
    assert d.tolist() == [[WALL, LANE]]


def test_import_does_not_need_torch_or_sam():
    here = Path(edge_capture.__file__).parent
    code = ("import sys; sys.modules['torch'] = None; sys.modules['sam3'] = None; "
            "import edge_capture; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=here, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(here)}, check=False)
    assert r.stdout.strip() == "ok", r.stderr
