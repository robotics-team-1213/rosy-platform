"""웹 표면의 대화 상자 계약 — D-218.

웹 표면은 D-371·D-439 공용 confirmIrreversible과 수명·권한을 소유하는
확인 처리기를 쓴다. 네이티브 window.confirm은 정지 접근을 막으므로 금지한다.
이 계약이 지키는 것:

1. alert/prompt 는 금지다 — 모의 안내(F-20)도, 확인 아닌 길도 없다.
2. 공용 확인과 소유 처리기는 고정된 파일·횟수로만 산다 — 새 확인은 이 핀을 고치는
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

    `test/` 와 `shared/web/test` 는 한 파일 트리에 있으나 서로의 import 경로에
    없다. sys.path 를 넓히면 그쪽 conftest 까지 함께 올라오므로 경로로 로드한다.
    """
    path = ROOT / "shared" / "web" / "test" / "surface_registry.py"
    spec = importlib.util.spec_from_file_location("rosey_surface_registry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry = _load_registry()

#: 상대 경로별 공용 확인/소유 처리기 호출 수. 새 확인은 이 표와 함께 리뷰한다.
PINNED_CONFIRMS = {
    "middleware/ui/robot/app.js": 6,
    "middleware/ui/robot/map.js": 1,
    "middleware/ui/robot/panels/console/docking.js": 1,
    "middleware/ui/robot/panels/console/line-follow.js": 1,
    "middleware/ui/robot/panels/console/mode.js": 1,
    "middleware/ui/robot/panels/host/operations.js": 1,
    "middleware/ui/robot/panels/setup/dock-admin.js": 2,
    "middleware/ui/robot/panels/setup/docking.js": 1,
    "middleware/ui/robot/panels/setup/localization.js": 1,
    "middleware/ui/robot/panels/setup/traffic-policy.js": 1,
    "middleware/ui/robot/panels/system/security.js": 1,
    "middleware/ui/robot/peer-approval.js": 2,
    "middleware/ui/robot/settings.js": 2,
    "middleware/ui/robot/telemetry.js": 1,
    "operations/fleet/fleet/server/web/camera-pairing.js": 2,
    "operations/fleet/fleet/server/web/camera-peer.js": 2,
    "operations/fleet/fleet/server/web/cell/cell.js": 1,
    "operations/fleet/fleet/server/web/confirmed-action.js": 1,
    "operations/fleet/fleet/server/web/console.js": 3,
    "operations/fleet/fleet/server/web/enrollment.js": 1,
    "operations/fleet/fleet/server/web/roster.js": 1,
    # Activation, camera-draft replacement (D-497), trip cancel (D-494).
    "operations/fleet/fleet/server/web/site-map.js": 3,
    "operations/fleet/fleet/server/web/tracking-view.js": 1,
}
CONFIRM_CALL = re.compile(
    r"\bconfirmIrreversible\s*\(|\bconfirmedAction\.run\s*\(|"
    r"(?<!function )\brunConfirmed\s*\(|"
    r"\(options\.confirm\s*\|\|\s*confirmIrreversible\)\s*\(|"
    r"(?<!\w)confirm\s*\("
)


def surface_scripts():
    for base in registry.for_contract(ROOT, "dialog"):
        if base.is_file():
            if base.suffix == ".js":
                yield base
            continue
        for path in sorted(base.rglob("*.js")):
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
        assert not re.search(r"window\.confirm\s*\(", text), path.relative_to(ROOT)
        count = len(CONFIRM_CALL.findall(text))
        if count:
            found[path.relative_to(ROOT).as_posix()] = count
    assert found == PINNED_CONFIRMS, (
        f"공용 확인 소유자가 핀과 다르다(D-371·D-439): {found} != {PINNED_CONFIRMS}"
    )


def test_every_confirm_message_names_what_it_will_do():
    """확인 문장은 청중의 평문으로 결과를 묻는다 — '~할까요?/~했습니까?'."""
    for path in surface_scripts():
        text = path.read_text(encoding="utf-8")
        for block in re.findall(
            r"(?:\b(?:confirmIrreversible|confirm|confirmedAction\.run)\s*\(\s*\{\s*"
            r"(?:kind,\s*)?message:\s*|\bconfirmIrreversible\)\s*\(\s*\{\s*message:\s*|"
            r"\brunConfirmed\(\s*)((?:\"[^\"]*\"|'[^']*'|`[^`]*`))", text
        ):
            message = block[1:-1]
            assert "까요" in message or "니까" in message or "확인" in message, (
                f"{path.name}: 확인 문장이 결과를 묻지 않는다: {block}"
            )
