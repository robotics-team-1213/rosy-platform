"""colcon install 없이 pytest를 돌린다 (Windows/CI)."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
TEST = Path(__file__).resolve().parent
entry = str(SRC / "games")
if entry not in sys.path:
    sys.path.insert(0, entry)
if str(TEST) not in sys.path:
    sys.path.insert(0, str(TEST))

# test 파일명은 fleet/test 와 겹치지 않게 유일해야 한다 (test_games_cli,
# test_host_session, test_host_transport, fake_host). 같은 basename 이면
# 합쳐 돌리는 pytest 수집에서 import file mismatch 가 난다.
