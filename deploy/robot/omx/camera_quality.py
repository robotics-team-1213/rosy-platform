"""Compatibility shim: the implementation moved to core_common.camera_quality (SRP W3).

Flat `import camera_quality` keeps working on cell PCs; the sys.path line covers a unit whose
PYTHONPATH lacks contracts/foundation (rosy-omx-camera-readiness.service)."""
import sys
from pathlib import Path

_FOUNDATION = Path(__file__).resolve().parents[3] / 'contracts' / 'foundation'
if _FOUNDATION.is_dir() and str(_FOUNDATION) not in sys.path:
    sys.path.append(str(_FOUNDATION))

from core_common.camera_quality import *  # noqa: E402,F401,F403
from core_common.camera_quality import POLICY, Readiness, advancing_frame, frame_quality, same_fresh_frame  # noqa: E402,F401
