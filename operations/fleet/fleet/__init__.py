"""fleet — Fleet 쪽 씨앗: 대형 기하·슬롯 배정·참조 스트림 릴레이·FOR-004 세션.

Fleet 서버 본체(Phase 4)는 아직 없다. 여기 있는 것은 로봇 계약(API Ref)만
소비하며 `core` 는 스키마 재사용을 위해서만 import 한다(D-18).
"""

__version__ = "0.1.0"

# Source checkouts load the canonical Decision namespace from its holder.
# Installed Fleet distributions include rosy.decision directly.
from pathlib import Path as _Path

if (_Path(__file__).resolve().parents[1] / "package.xml").is_file():
    from ._source_layout import bootstrap_decision as _bootstrap_decision

    _bootstrap_decision()
    del _bootstrap_decision
del _Path
