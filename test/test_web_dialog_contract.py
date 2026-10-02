"""웹 표면의 대화 상자 계약 — D-218.

세 웹 표면(콘솔·Fleet·게임)은 브라우저 네이티브 window.confirm 을 확인
문법으로 쓴다(불가역 확인의 졸업, D-92 제5항 — 두 번째 표면이 생기며
트리거가 성립했고, '공유 컴포넌트'의 자리를 브라우저가 이미 채우고 있다).
이 계약이 지키는 것:

1. alert/prompt 는 금지다 — 모의 안내(F-20)도, 확인 아닌 길도 없다.
2. confirm 은 고정된 파일·횟수로만 산다 — 새 확인은 이 핀을 고치는
   커밋과 함께 온다(그 커밋이 리뷰의 자리다).
3. 확인 없이 세상을 바꾸는 길이 늘어나는지는 브라우저 시험이 지킨다
   (Fleet 전체 정지·콘솔 모드 전환·정책 적용의 거부 경로).
"""

import importlib.util
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _load_registry():
    """D-329 표면 레지스트리를 경로로 직접 읽는다.

    `test/` 와 `src/hmi/web_common/test` 는 한 파일 트리에 있으나 서로의 import 경로에
    없다. sys.path 를 넓히면 그쪽 conftest 까지 함께 올라오므로 경로로 로드한다.
    """
    path = ROOT / "src" / "hmi" / "web_common" / "test" / "surface_registry.py"
    spec = importlib.util.spec_from_file_location("rosey_surface_registry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry = _load_registry()

#: 파일별 window.confirm 허용 수. 늘릴 때는 이 표와 함께 커밋한다.
PINNED_CONFIRMS = {
    "app.js": 8,
    "settings.js": 8,  # D-371: 목록 행 삭제 셋(토큰·도크·웨이포인트)은 confirmIrreversible
    "map.js": 1,
    "telemetry.js": 1,  # 교통 정책 적용 확인 — D-362 P1 분할로 app.js에서 이동
    "console.js": 3,   # Fleet 목표 지정, 전체 정지, 정지 래치 재허가
    "roster.js": 1,    # 카메라 고장 뒤 IR 추적 선택 확인
    "install.js": 1,   # D-410 설치 문서의 전체 정지 — 관제 표면의 첫 화면 규칙을 따른다
}


def surface_scripts():
    for base in registry.for_contract(ROOT, "dialog"):
        if base.is_file():
            if base.suffix == ".js":
                yield base
            continue
        for path in sorted(base.glob("*.js")):
            yield path


def test_no_alert_or_prompt_on_any_surface():
    offenders = []
    for path in surface_scripts():
        text = path.read_text(encoding="utf-8")
        for needle in ("alert(", "prompt("):
            # (?<!\w): myalert( 같은 합성어만 제외한다. 앞의 마침표
            # (window.alert)까지 면책하면 침입 경로가 된다 — 변이 증명이
            # 이것을 붙잡았다.
            if re.search(rf"(?<!\w){re.escape(needle)}", text):
                offenders.append(f"{path.name}: {needle}")
    assert offenders == [], (
        "alert/prompt 는 웹 표면의 어휘가 아니다(D-218, F-20): " + ", ".join(offenders)
    )


def test_confirm_lives_only_in_the_pinned_files_and_counts():
    found = {}
    for path in surface_scripts():
        text = path.read_text(encoding="utf-8")
        count = len(re.findall(r"window\.confirm\(", text))
        if count:
            found[path.name] = count
    assert found == PINNED_CONFIRMS, (
        f"window.confirm 배치가 핀과 다르다(D-218): {found} != {PINNED_CONFIRMS}"
    )


def test_every_confirm_message_names_what_it_will_do():
    """확인 문장은 청중의 평문으로 결과를 묻는다 — '~할까요?/~했습니까?'."""
    for path in surface_scripts():
        text = path.read_text(encoding="utf-8")
        for block in re.findall(
            r"window\.confirm\(((?:\"[^\"]*\"|'[^']*'|`[^`]*`))\)", text
        ):
            message = block[1:-1]
            assert "까요" in message or "니까" in message or "확인" in message, (
                f"{path.name}: 확인 문장이 결과를 묻지 않는다: {block}"
            )
