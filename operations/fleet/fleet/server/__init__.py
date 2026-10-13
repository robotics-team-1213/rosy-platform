"""관제 PC의 Fleet 서버 — 사이트 오케스트레이터 역할 (D-59 §2).

`console.py` 는 모으고 흩뿌리는 규칙이고, `app.py` 는 그것을 HTTP 로 낸다.
"""


from pathlib import Path
from fleet._source_layout import SERVER_HOLDERS

__path__.extend(str(Path(__file__).parent / name) for name in SERVER_HOLDERS
                if (Path(__file__).parent / name).is_dir())
