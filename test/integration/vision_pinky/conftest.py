"""Vision + Pinky drive integration tests: perception (vision app) code driven together with the drive stack.

They moved out of middleware/perception/test (2026-11-20 app independence, split round 4) so the vision
suite imports no pinky drive module. They still use that suite's helpers (lane_sim, dock_scene, ...) and its
import paths, so those come in here.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
PERCEPTION_TEST = ROOT / "middleware" / "perception" / "test"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
# `control` resolves from here (pytest puts it on sys.path itself when perception/test is collected, as a package).
sys.path.insert(0, str(ROOT / "middleware" / "perception"))
sys.path.insert(0, str(PERCEPTION_TEST))
sys.path.append(str(ROOT / "integrations" / "perception" / "test"))
sys.path.insert(1, str(ROOT / "integrations" / "perception"))
sys.path.insert(0, str(ROOT / "contracts" / "foundation"))
