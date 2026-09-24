"""호스트 pytest가 colcon 설치 없이 core_common 을 임포트하게 한다(D-61 선례)."""

import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]  # .../src/core/core_common

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
