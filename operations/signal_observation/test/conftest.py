"""signal/observer 의 시험 — 이 디렉터리를 import 경로로 올린다.

주의: `signal/` 자체를 sys.path 에 올리면 표준 라이브러리 `signal` 을 가린다.
올리는 것은 `signal/observer/` 디렉터리뿐이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # signal/observer/test
OBSERVER = HERE.parent                          # signal/observer

for entry in (str(OBSERVER),):
    if entry not in sys.path:
        sys.path.insert(0, entry)
