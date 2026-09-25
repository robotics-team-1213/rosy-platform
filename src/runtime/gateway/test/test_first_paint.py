"""concept 16 §5 / Law 0 — 빈칸과 em dash는 다른 사실이다.

운용자가 가장 자주 보는 화면은 교대 시작의 빈 화면이다. 지금까지 그 화면은
값 자리를 전부 em dash로 배송했고, 그건 **센서가 죽은 화면과 똑같이 생겼다**.
로봇 고장인지 자기가 로그인을 안 한 건지 구분할 수 없었다.

빈칸 = 아직 묻지 않았다. em dash = 물었는데 없다.
"""

from pathlib import Path
import re

WEB_ROOT = Path(__file__).parent.parent.parent / "core_api_web" / "core_api_web" / "web"
INDEX = WEB_ROOT / "index.html"
DOM = WEB_ROOT / "dom.js"
APP = WEB_ROOT / "app.js"

EVIDENCE_WORDS = ("fresh", "delayed", "disconnected", "unavailable")


def test_the_shipped_markup_carries_no_em_dash_in_value_slots():
    """첫 페인트는 JS가 돌기 전에 이미 운용자 눈에 들어온다.

    `>—<`만 찾으면 `SEQ —`·`voltage —`처럼 라벨이 앞에 붙은 자리를 놓친다.
    실제로 그렇게 놓쳤다 — 고침과 그 고침을 지키는 시험이 같은 좁은 패턴을
    인코딩하면 둘 다 같은 구멍을 갖는다. 그래서 **텍스트가 대시로 끝나는**
    id 자리를 전부 본다. `<title>`은 id가 없어 걸리지 않는다.
    """
    html = INDEX.read_text(encoding="utf-8")
    slots = [
        (slot, text.strip())
        for slot, text in re.findall(r'id="([^"]+)"[^>]*>([^<]*—)<', html)
    ]
    assert not slots, f"값 자리에 em dash가 박혀 배송된다: {slots[:8]}"


def test_a_binding_is_empty_before_the_first_fetch():
    dom = DOM.read_text(encoding="utf-8")
    assert "let requested = false;" in dom, "요청 여부를 기억하지 않는다"
    assert 'value ?? (requested ? fallback : "")' in dom, (
        "요청 전에도 fallback(em dash)을 쓴다"
    )


def test_the_page_level_signal_does_not_reuse_the_evidence_vocabulary():
    """페이지 상태에 값별 증거 어휘를 쓰면 둘이 섞인다(concept 16 §5)."""
    dom = DOM.read_text(encoding="utf-8")
    block = re.search(r"let requested = false;.*?export function markRequested\(\) \{.*?\}", dom, re.DOTALL)
    assert block, "markRequested 선언을 찾지 못했다"
    for word in EVIDENCE_WORDS:
        assert f'"{word}"' not in block.group(0), f"페이지 상태가 값 어휘 {word}를 쓴다"


def test_the_flag_flips_only_after_a_real_fetch():
    """요청이 돌아온 뒤에야 em dash가 '물었는데 없다'를 뜻한다."""
    app = APP.read_text(encoding="utf-8")
    assert "markRequested()" in app
    order = app.index('await api("/api/v1/robot/state")'), app.index("markRequested()")
    assert order[0] < order[1], "요청 전에 플래그를 세운다"


def test_pre_auth_host_facts_are_not_exposed_here():
    """인증 전에 호스트·릴리스를 보여주는 것은 무인증 엔드포인트를 새로 여는
    일이고, 이 변경의 범위가 아니다 — 사람이 따로 결정한다."""
    api = (WEB_ROOT.parent / "api" / "v1" / "system.py").read_text(encoding="utf-8")
    assert "Depends(viewer)" in api, "system 라우트가 인증을 잃었다"
