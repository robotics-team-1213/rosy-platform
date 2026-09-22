"""D-18: 스키마 원천·앱 표면·계약 문서의 버전 규칙이 하나의 답을 낸다.

통신·프로토콜 보고서(2026-09-22 §8-I)가 발견한 3원 불일치 — schemas.py
docstring("MINOR 상승" 약속) vs `PROTOCOL_VERSION = "1.0"` 동결 vs app.py
"(v1.2)" vs 문서 v1.15 — 를 계약 시험으로 못 박는다. 규칙(API Ref v1.8 노트):
envelope `protocol_version` 은 1.0 고정, additive 는 문서의 MINOR 로 기록.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = ROOT / "src/core/core_common/core_common/protocol/schemas.py"
API_APP = ROOT / "src/core/core_api_web/core_api_web/api/app.py"
DOC = ROOT / "docs/reference/ROSY API & Protocol Reference.md"


def _live_doc_version() -> str:
    match = re.search(r"\*\*Version:\*\* v(\d+\.\d+)", DOC.read_text(encoding="utf-8"))
    assert match, "API Ref 헤더에 Version 표기가 없다"
    return match.group(1)


def test_schemas_docstring_states_the_envelope_1_0_rule():
    text = SCHEMAS.read_text(encoding="utf-8")
    assert "protocol_version 은 1.0" in text
    assert "MINOR 상향" not in text, (
        "docstring이 envelope MINOR 상승을 약속하면 PROTOCOL_VERSION='1.0' 과 모순")


def test_app_description_names_the_live_contract_version():
    live = _live_doc_version()
    app_text = API_APP.read_text(encoding="utf-8")
    assert f"v{live}" in app_text, (
        f"FastAPI description이 계약 문서의 현재 버전(v{live})을 말해야 한다")


def test_changelog_has_a_row_for_the_live_version():
    live = _live_doc_version()
    doc = DOC.read_text(encoding="utf-8")
    assert f"| v{live} |" in doc, (
        f"문서 헤더가 v{live}를 주장하면 변경 이력에 해당 행이 있어야 한다")
