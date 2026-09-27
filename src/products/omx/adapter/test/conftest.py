"""colcon install 없이 pytest 를 돌린다 (Windows/CI).

`src/fleet/test/conftest.py` 와 같은 방식이다 — 소스 트리에서 패키지를
바로 찾도록 sys.path 를 잡는다. 이것이 없으면 `test_omx_profile.py` 가
`omx_adapter` 를 찾지 못해 collection 단계에서 전체가 중단되고,
AGENTS.md 의 조합 명령이 다른 패키지까지 같이 죽인다.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]

for path in (SRC / "adapter",):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
