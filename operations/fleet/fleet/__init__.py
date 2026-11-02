"""fleet — ROSY Platform의 현장 조정 서비스(Rosy Fleet의 서버).

현장 로봇을 모아 보고, 누가 어디로 언제 갈지 정해 원장에 받아들이고, 각 로봇 CORE에 요청한다.
최종 주행 명령과 안전 래치는 CORE의 몫이다. 패키지별 역할은 `AGENTS.md`. 로봇 계약(API Ref)만
소비하며 `core` 는 스키마 재사용을 위해서만 import 한다(D-18).
"""

__version__ = "0.1.4"

# Source checkouts load canonical Decision, assessment and execution holders.
# Installed Fleet includes Decision/assessment and depends on the execution wheel.
from pathlib import Path as _Path

if (_Path(__file__).resolve().parents[1] / "package.xml").is_file():
    from ._source_layout import bootstrap_sources as _bootstrap_sources

    _bootstrap_sources()
    del _bootstrap_sources
del _Path
