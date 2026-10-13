"""Perception distribution identity with declared legacy Drive ROS adapters."""

from pathlib import Path

if (Path(__file__).resolve().parents[1] / 'package.xml').is_file():
    from ._source_layout import RUNTIME_ROOT
    __path__.append(str(RUNTIME_ROOT))
