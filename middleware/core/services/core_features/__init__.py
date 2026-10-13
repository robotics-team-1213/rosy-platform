"""CORE library identity with declared Drive source holders in a checkout."""

from pathlib import Path

if (Path(__file__).resolve().parents[1] / 'package.xml').is_file():
    from ._source_layout import BEHAVIOR_ROOT
    __path__.append(str(BEHAVIOR_ROOT))
