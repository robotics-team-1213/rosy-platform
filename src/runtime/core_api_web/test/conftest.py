"""호스트 pytest가 colcon 설치 없이 core_api_web 을 임포트하게 한다(D-61 선례)."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]  # .../src

for name in ("core_api_web", "core_common", "core_events", "core_features"):
    path = SRC / "core" / name
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
