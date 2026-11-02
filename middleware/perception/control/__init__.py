"""Perception distribution identity with declared legacy Drive ROS adapters."""

from pathlib import Path

if (Path(__file__).resolve().parents[1] / 'package.xml').is_file():
    import sys
    from ._source_layout import CONTROL_ROOTS, PERCEPTION_RUNTIME_ROOT
    __path__.extend(str(folder) for folder in CONTROL_ROOTS)
    # Source tree only: colcon installs perception_runtime as its own package beside control.
    if str(PERCEPTION_RUNTIME_ROOT) not in sys.path:
        sys.path.append(str(PERCEPTION_RUNTIME_ROOT))
