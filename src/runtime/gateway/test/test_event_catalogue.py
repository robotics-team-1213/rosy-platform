"""§8 이벤트 카탈로그와 코드가 내는 이벤트는 같은 목록이어야 한다.

카탈로그는 "소비자가 의존하는 안정적 계약"이라고 스스로 적어 두었지만 양쪽이
말없이 갈라져 있었다. `docking.*` 11 종과 `battery.deep` 은 구현돼 발행되는데
계약에 없었고 — 계약만 읽는 Fleet 은 도킹 상태도, 딥 방전으로 모터가 선 이유도
알 방법이 없다 — `safety.watchdog` 은 v1.0 부터 약속돼 있는데 코드가 낸 적이
없었다. D-31 과 D-32 가 각각 라우트와 응답에 대해 고친 것과 같은 어긋남이다.

**이 파일이 손으로 관리하는 목록을 갖지 않는 것이 핵심이다.** 앞선 판본은
"이벤트처럼 생긴 문자열"을 모으고 예외 목록으로 걸러냈는데, 그 예외 목록이
`battery.deep`(critical)을 숨겼다 — 문서와 똑같이 드리프트한 것이다. 지금은
발행 지점 자체에서 이름·심각도·payload 키를 읽는다. 새 이벤트 계열이 생겨도,
키 하나가 바뀌어도 걸린다.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import re
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[4]
#: CORE 도메인 (D-125/D-126). 발행 지점은 다섯 패키지에 흩어져 있다 — 한
#: 패키지만 읽으면 나머지에서 내는 이벤트는 가드 밖이다.
SRC = ROOT / "src"
PACKAGES = (
    SRC / "runtime" / "gateway" / "core",
    SRC / "contracts" / "foundation" / "core_common",
    SRC / "runtime" / "events" / "core_events",
    SRC / "runtime" / "services" / "core_features",
    SRC / "runtime" / "api_web" / "core_api_web",
)


def _sources() -> list[Path]:
    return sorted(path for package in PACKAGES for path in package.rglob("*.py"))


def _origin(path: Path) -> str:
    """`core_features/core_features/docking/manager.py` 처럼 도메인 기준 경로."""
    for package in PACKAGES:
        if path.is_relative_to(package):
            return path.relative_to(package.parent.parent).as_posix()
    raise ValueError(path)


REFERENCE = ROOT / "docs" / "reference" / "ROSY API & Protocol Reference.md"

#: 이벤트 이름의 모양. **자리에 따라 두 가지를 쓴다.**
#:
#: 발행 자리(이름 인자)는 넓게 본다 — 거기 놓인 문자열은 이미 이벤트 이름이고,
#: 넓혀도 거짓 양성이 없다. 좁게 두면 `imu.bno055_fault` 처럼 숫자가 들어가거나
#: `docking.stage.begin` 처럼 세 마디인 이름이 **조용히** 빠진다. 그리고 문서
#: 쪽 정규식도 같은 모양이었으므로, 그런 이름은 양쪽에서 동시에 안 보이고
#: 가드는 "일치한다"고 답한다 — 이 파일이 없애려던 `battery.deep` 의 실패가
#: 정규식으로 다시 쓰인 것이다.
#:
#: 두 번째 그물(소스의 모든 문자열)은 좁게 둔다. 넓히면 설정 키·경로가 쏟아져
#: 들어와 예외 목록을 키우게 되고, 그 목록이 바로 위의 실패다.
_EVENT_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_EVENT_SHAPED_LITERAL = re.compile(r"[a-z_]+\.[a-z_]+")
_SEVERITIES = {"info", "warning", "error", "critical"}


class Emit:
    """발행 지점 하나에서 읽어낸 것."""

    def __init__(self, name: str, severity: str | None,
                 keys: frozenset[str] | None, where: str) -> None:
        self.name = name
        self.severity = severity
        self.keys = keys          # None = 동적으로 만든 payload, 키를 알 수 없음
        self.where = where

    def __repr__(self) -> str:  # pragma: no cover - 실패 메시지용
        return f"{self.name} @ {self.where}"


def _names_in(node: ast.AST) -> Optional[list[str]]:
    """이벤트 **이름 자리**의 문자열. 정적으로 못 읽으면 `None`.

    `publish("config.changed", data={"key": "safety.limits"})` 에서
    `safety.limits` 는 설정 키이지 이벤트가 아니다. 이름 자리만 보는 것으로
    그런 것이 걸러진다.

    `None` 과 빈 목록은 다르다. 빈 목록은 "이름이 아니다"(예: 첫 인자가 숫자),
    `None` 은 "이름 자리인데 읽지 못했다"(f-string, 모듈 상수, 변수) 이고 —
    그것은 조용히 넘길 것이 아니라 실패시킬 것이다. 읽지 못한 것을 통과시키는
    가드는 통과시키는 법을 하나 더 배운 것뿐이다.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            if _EVENT_NAME.fullmatch(node.value):
                return [node.value]
            # 점이 있는데 모양이 안 맞으면 "우리가 모르는 이름"이다 — 조용히
            # 버리면 가드가 그만큼 눈을 감으므로 `None` 으로 알린다.
            # 점이 아예 없으면 애초에 이름이 아니다(모드 문자열 등). 그것까지
            # 알리면 `if state in ("warning", "critical")` 이 빨개진다.
            return None if "." in node.value else []
        return []
    if isinstance(node, ast.IfExp):
        # self._emit("docking.charging" if confirmed else "docking.charge_lost", ...)
        left, right = _names_in(node.body), _names_in(node.orelse)
        if left is None or right is None:
            return None
        return left + right
    return None


def severity_spellings(tree: ast.AST) -> frozenset[str]:
    """이 모듈에서 `Severity` 열거형을 부르는 이름들.

    접미사로 넘겨짚지 않는다. `import … as Level` 한 줄이면 접미사 규칙은
    그 발행 지점을 **조용히** 놓치고, 접미사에 걸리는 아무 변수(`sev`,
    `thresholds.severity`)는 심각도가 아닌데 심각도로 읽힌다. 그 모듈이 실제로
    무엇을 import 했는지가 답이고, 소스는 이미 손에 있다.
    """
    names = {"Severity"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] == "Severity":
                    names.add(alias.asname or "Severity")
    return frozenset(names)


def _severity_written_at(node: ast.AST,
                         spellings: frozenset[str] = frozenset({"Severity"})
                         ) -> Optional[str]:
    """이 노드가 심각도인가. `"warning"` 이거나 `Severity.WARNING` 이거나.

    소유자를 확인하는 것이 중요하다. 열거형이면 무엇이든 받으면
    `BatteryLevel.CRITICAL` 이 심각도로 읽히고, `if level not in
    (BatteryLevel.WARNING, BatteryLevel.CRITICAL, BatteryLevel.DEEP)` 라는
    평범한 멤버십 검사가 발행 튜플로 잡힌다.
    """
    if isinstance(node, ast.Constant) and node.value in _SEVERITIES:
        return node.value
    if isinstance(node, ast.Attribute) and node.attr.lower() in _SEVERITIES:
        owner = node.value
        # `Severity.X` 도 `schemas.Severity.X` 도 소유자 끝이 그 이름이다.
        spelled = getattr(owner, "attr", None) or getattr(owner, "id", "")
        if spelled in spellings:
            return node.attr.lower()
    return None


def _severity_of(node: Optional[ast.AST], spellings: frozenset[str]) -> Optional[str]:
    """심각도 자리의 값. 비어 있으면 `EventBus.publish` 의 기본값인 info 다.

    자리가 **비어 있는 것** 과 자리에 무언가 있는데 **읽지 못한 것** 은 다르다.
    앞은 기본값 info 가 맞고(발행 지점의 3 분의 1 쯤이 그렇다), 뒤는 조용히 info 로
    적어 넣으면 문서도 info 라고 적혀 있을 때 그 어긋남이 영영 안 보인다.
    읽지 못한 것은 `None` 으로 돌려 실패시킨다.

    **자리를 정해 읽는다.** 인자를 훑어 심각도처럼 생긴 것을 집으면
    `publish("x.y", source="error", …)` 의 `source` 가 심각도로 읽힌다.
    """
    if node is None:
        return "info"
    return _severity_written_at(node, spellings)


def _looks_like_an_emit_tuple(elts: list[ast.AST], spellings: frozenset[str]) -> bool:
    """`(type, severity, data)` 인가, 아니면 그냥 문자열 두 개짜리 튜플인가.

    모양만 보면 `("config.yaml", "path")` 나 `if x in ("mission.assigned", …)`
    같은 평범한 튜플이 이벤트로 잡힌다. 심각도나 payload 가 함께 있어야
    발행 자리다.
    """
    return any(isinstance(node, ast.Dict)
               or _severity_written_at(node, spellings) is not None
               for node in elts[1:])


#: ROS 퍼블리셔 변수의 이름 규약. 이 패키지는 예외 없이 이렇게 짓는다.
_ROS_PUBLISHER_SUFFIXES = ("_pub", "_publisher")


def _is_event_bus(func: ast.AST) -> bool:
    """`self._events.publish(...)` 인가 `self.cmd_vel_pub.publish(msg)` 인가.

    ROS 퍼블리셔도 `publish` 다. 이름 자리에 `Twist()` 가 앉아 있으니 "이름을
    못 읽었다"로 잡혀 가드가 영원히 빨개진다.

    **버스를 허용 목록으로 고르지 않는다.** `self._events`·`svc.events` 만
    통과시키면 `events.publish(...)`(모듈 전역·지역 이름)나 `self.bus.publish(...)`
    는 발행 자리로 세어지지도 않고 **조용히** 빠진다 — 가드가 눈을 감는 쪽으로
    틀리는 것이다. 그래서 반대로 적는다: `publish` 는 전부 발행 자리이고,
    ROS 퍼블리셔 이름 규약(`*_pub`)에 맞는 것만 뺀다. 규약을 벗어난 퍼블리셔가
    생기면 가드가 빨개지고, 그것은 이름을 고치거나 여기를 고치라는 뜻이다 —
    어느 쪽이든 사람이 보게 된다.
    """
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value
    name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
    return not name.endswith(_ROS_PUBLISHER_SUFFIXES)


def _is_ros_publish(call: ast.Call) -> bool:
    """ROS 퍼블리셔 호출의 **모양**: 위치 인자 하나, 키워드 없음.

    이름 규약만으로 빼면, 이벤트 버스를 담은 속성이 우연히 `_pub` 으로 끝날 때
    그 자리가 통째로 사라진다. 모양까지 맞을 때만 뺀다 —
    `self._events_pub.publish(name, data={...})` 는 규약에 걸려도 모양이
    다르므로 발행 자리로 남는다.
    """
    return len(call.args) == 1 and not call.keywords


#: 이벤트가 아닌 것을 `publish` 하는 도메인 객체. 소유자 이름 **과** 모양이
#: 함께 맞아야 뺀다 — 이름 자리에 문자열 상수가 오면 그것은 여전히 발행 자리로
#: 읽힌다(`svc.vision.publish("x.y", ...)` 는 걸린다).
_NON_EVENT_PUBLISHERS = {
    # `VisionFrameStore.publish(data: bytes, *, captured_at, ...)` — 카메라 프레임.
    "vision",
}


def _is_frame_publish(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value
    name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
    first = call.args[0] if call.args else None
    named = isinstance(first, ast.Constant) and isinstance(first.value, str)
    return name in _NON_EVENT_PUBLISHERS and not named


def _publishes(node: ast.AST) -> bool:
    """이 함수 몸통에 발행 호출이 있는가.

    ROS 퍼블리셔는 세지 않는다. `self.cmd_vel_pub.publish(msg)` 하나가 함수를
    중계로 승격시키면, 중계에만 주는 면제가 그 함수에 딸려 들어간다.
    """
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        called = getattr(inner.func, "attr", "") or getattr(inner.func, "id", "")
        if called == "_emit" or (called == "publish" and _is_event_bus(inner.func)):
            return True
    return False


def _qualified(stack: list[str], name: str) -> str:
    return ".".join(stack + [name])


def relay_fingerprints() -> dict[tuple[str, str], str]:
    """중계 함수들과 **그 몸통의 지문**.

    중계란 이름을 받아 그대로 버스로 넘기는 함수다 — `_emit(type_, …)` 과
    `_emit_all(pending)` 처럼. 그 몸통에서 발행되는 이름은 정적으로 읽을 수
    없지만, 읽어야 할 이름은 호출 자리나 튜플 리터럴 쪽에 있고 그것은 이미
    잡힌다. 그래서 중계 몸통은 발행 지점 추출에서 통째로 뺀다.

    **면제는 패턴이 아니라 이 네 함수의 이 몸통들에만 준다.** 네 번의 리뷰가
    모두 이 면제로 들어왔고, 매번 "어떤 모양이면 중계인가"를 좁혔지만 그
    질문에는 끝이 없었다 — 면제의 근거는 데이터 흐름("이 이름은 caller 가
    준 것이다")인데 검사할 수 있는 것은 이름의 철자뿐이기 때문이다. 그래서
    모양을 묻기를 그만두고 몸통 자체를 고정한다. 한 줄이라도 바뀌면 지문이
    달라져 면제가 사라지고, 그 순간 그 안의 동적 발행이 곧바로 걸린다.
    """
    found: dict[tuple[str, str], str] = {}
    for path in _sources():
        origin = _origin(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for qualname, node in _functions_in(tree):
            if node.name.startswith("_emit") and _publishes(node):
                key = (origin, qualname)
                # 마지막이 이기게 두면 고정 목록이 거짓말을 한다.
                found[key] = ("두 번 정의됨: " + qualname if key in found
                              else fingerprint(node))
    return found


def _functions_in(tree: ast.AST):
    """`(한정 이름, 노드)`. 같은 이름의 메서드가 두 클래스에 있어도 구분된다."""
    def walk(node: ast.AST, stack: list[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield _qualified(stack, child.name), child
                yield from walk(child, stack + [child.name])
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, stack + [child.name])
            else:
                yield from walk(child, stack)
    yield from walk(tree, [])


def fingerprint(node: ast.AST) -> str:
    """주석·공백·docstring 에는 둔감하고 코드에는 민감한 지문.

    `ast.dump` 를 해시하지 않는다. 그 출력은 파이썬 버전마다 다르다(3.13 에서
    빈 필드를 생략하기 시작했다) — 개발 호스트(3.14)에서 고정한 값이 CI·Pi
    (3.12)에서 틀려져, 가드가 멀쩡한 중계를 두고 빨개진다. 정규화한 소스
    (`ast.unparse`)는 버전을 타지 않는다. docstring 은 설명이지 흐름이 아니므로
    뺀다.
    """
    node = copy.deepcopy(node)
    body = getattr(node, "body", None)
    if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        node.body = body[1:] or [ast.Pass()]
    normalised = ast.unparse(node)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


#: 몸통이 이 지문과 같을 때에만 중계로 인정한다. 값을 손으로 고치는 것이
#: 곧 "이 함수를 다시 읽었다"는 서명이다 — 그러라고 있는 목록이다.
PINNED_RELAYS = {
    ("core_features/core_features/docking/manager.py", "DockingManager._emit"):
        "15ae9dd72fa20f0b",
    ("core_features/core_features/safety/manager.py", "SafetyManager._emit"):
        "e0aca301e45601ff",
    ("core_features/core_features/power/battery.py", "BatteryMonitor._emit_all"):
        "fdb020d71a91a47a",
    ("core_features/core_features/power/manager.py", "PowerManager._emit_all"):
        "da516d1499355bc6",
}


#: 이벤트 이름과 모양이 같은 파일 이름들 (`app.js`, `docks.json`, `audit.jsonl`).
_FILE_SUFFIXES = {"js", "css", "html", "json", "jsonl", "yaml", "yml", "md", "sh", "py"}

#: 첫 인자가 "점 찍힌 이름"인데 이벤트가 아닌 호출들. capability 경로(CAP-001)와
#: Host Agent RPC 메서드가 그렇다 — 목록이 아니라 **자리** 로 걸러진다.
_NAMESPACED_FIRST_ARG = {"require", "supports", "request"}


def _declared_capability_names() -> set[str]:
    """도메인 모델이 CAP-001 경로·concept id 로 선언한 이름들.

    `core_common.domain` 의 표(`_CAP001_TO_CONCEPT`, `TaskKind.capability`·
    `concept_id`)가 곧 선언이다. 여기에 손으로 옮겨 적으면 그 목록이 표와
    따로 드리프트한다 — 표에서 읽는다.
    """
    from core_common.domain.capabilities import _CAP001_TO_CONCEPT
    from core_common.domain.tasks import TaskKind

    names = {name for pair in _CAP001_TO_CONCEPT for name in pair}
    for kind in TaskKind:
        names.update((kind.capability, kind.concept_id))
    return names


def _literals_with_another_job(tree: ast.AST) -> set[str]:
    """이벤트가 아닌 것이 이미 분명한 자리에 놓인 문자열들."""
    spoken_for: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        first = node.args[0]
        if called in _NAMESPACED_FIRST_ARG and isinstance(first, ast.Constant):
            if isinstance(first.value, str):
                spoken_for.add(first.value)
        named_first = isinstance(first, ast.Constant) and isinstance(first.value, str)
        if not named_first and called not in ("_emit", "publish"):
            # `_wire_bool(lane["visible"], "lane.visible")` — 값을 첫 자리에
            # 받고 뒤따르는 문자열은 오류 메시지용 **필드 경로 라벨** 이다.
            # 이름을 첫 자리에 받는 래퍼(`notify("x.y", …)`)는 여기 안 걸린다.
            for arg in node.args[1:]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    spoken_for.add(arg.value)
        for keyword in node.keywords:
            # `_authorize(websocket, capability="swarm.lead")` — 자리는 같고
            # 이름만 키워드로 적힌 것.
            if keyword.arg == "capability" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    spoken_for.add(keyword.value.value)
    return spoken_for


def emit_sites() -> tuple[list[Emit], list[str]]:
    """발행 지점들과, **이름을 읽지 못한 자리들**.

    두 번째 목록이 비어 있지 않으면 가드는 그만큼 눈을 감고 있는 것이다.
    """
    sites: list[Emit] = []
    unresolved: list[str] = []
    for path in _sources():
        # 도메인에 `manager.py` 가 여럿이다. 파일 이름만 적으면 실패 메시지가
        # 읽는 사람을 엉뚱한 파일로 보낸다.
        found, blind = scan(path.read_text(encoding="utf-8"), _origin(path))
        sites.extend(found)
        unresolved.extend(blind)
    return sites, unresolved


def scan(source: str, origin: str = "<test>") -> tuple[list[Emit], list[str]]:
    """소스 하나에서 발행 지점을 읽는다.

    파일이 아니라 문자열을 받는 것이 요점이다 — 추출기가 무엇을 잡고 무엇을
    놓치는지를 합성 소스로 직접 물을 수 있어야, "빠져나갈 수 없다"가 주장이
    아니라 테스트가 된다.
    """
    sites: list[Emit] = []
    unresolved: list[str] = []
    tree = ast.parse(source)
    spellings = severity_spellings(tree)

    def descend(node: ast.AST, stack: list[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = (origin, _qualified(stack, node.name))
            if key in PINNED_RELAYS and PINNED_RELAYS[key] != fingerprint(node):
                # 이 말을 안 하면 아래에서 "이름을 정적으로 읽을 수 없다"만
                # 나온다 — 루프 변수 이름 하나 바꾼 사람은 없는 결함을 찾아
                # 헤매다가 고정 목록을 지우는 쪽으로 간다.
                unresolved.append(
                    f"{origin}:{node.lineno}: 고정된 중계의 몸통이 바뀌었다 — "
                    "발행되는 이름이 여전히 호출 자리나 튜플 리터럴에서 오는지 "
                    "확인하고 PINNED_RELAYS 를 갱신할 것")
            if PINNED_RELAYS.get(key) == fingerprint(node):
                # 고정된 중계다. 이 몸통이 발행하는 이름은 호출 자리와 튜플
                # 리터럴 쪽에서 이미 읽혔으므로 여기서는 아무것도 보지 않는다.
                # 한 줄이라도 바뀌면 지문이 달라져 이 가지로 오지 않는다.
                return
            stack = stack + [node.name]
        elif isinstance(node, ast.ClassDef):
            stack = stack + [node.name]
        read(node)
        for child in ast.iter_child_nodes(node):
            descend(child, stack)

    def read(node: ast.AST) -> None:
        first: ast.AST | None = None
        severity_node: ast.AST | None = None
        payloads: list[ast.AST] = []
        is_call = False
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            bus = ((_is_event_bus(func) or not _is_ros_publish(node))
                   and not _is_frame_publish(node))
            if called == "_emit" or (called == "publish" and bus):
                is_call = True
                keywords = {k.arg: k.value for k in node.keywords}
                first = node.args[0] if node.args else keywords.get("type_") or keywords.get("type")
                severity_node = (node.args[1] if len(node.args) > 1
                                 else keywords.get("severity"))
                # `data=` 를 먼저 본다. 순서대로 첫 dict 를 집으면
                # `publish(…, context={…}, data={…})` 가 엉뚱한 키를 읽는다.
                payloads = ([keywords["data"]] if "data" in keywords else [])
                payloads += list(node.args[1:]) + [k.value for k in node.keywords]
        elif (isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 2
              and _looks_like_an_emit_tuple(node.elts, spellings)):
            # 절전·배터리는 `(type, severity, data)` 튜플을 모아 두었다가
            # 한 번에 낸다 — append 로도, 리스트 리터럴로도.
            first = node.elts[0]
            # `(name, payload)` 의 둘째 칸은 심각도 자리가 아니다 — 거기서
            # 읽으려 하면 "심각도를 못 읽었다"고 틀린 이유로 빨개진다.
            severity_node = node.elts[1] if len(node.elts) == 3 else None
            payloads = list(node.elts[1:])

        if first is None and not is_call:
            return
        where = f"{origin}:{getattr(node, 'lineno', 0)}"
        if first is None:
            unresolved.append(f"{where}: 이름 인자가 없다")
            return
        names = _names_in(first)
        if names is None:
            # 호출이든 튜플이든 마찬가지다. `_looks_like_an_emit_tuple` 을
            # 통과한 튜플은 이미 자기가 발행 자리라고 말한 것이므로, 그
            # 이름을 못 읽으면 그것도 눈을 감은 것이다. 이 모양은
            # `power/battery.py`·`power/manager.py` 가 실제로 쓰는 것이라, 새
            # 배터리·절전 이벤트가 가장 쉬운 길로 새는 자리였다.
            unresolved.append(f"{where}: 이름을 정적으로 읽을 수 없다")
            return
        if not names:
            return          # 이름 자리가 아니었다 (숫자 등)

        severity = _severity_of(severity_node, spellings)
        if severity is None:
            unresolved.append(f"{where}: 심각도를 정적으로 읽을 수 없다")
            return
        payload = next((a for a in payloads if isinstance(a, ast.Dict)), None)
        keys: frozenset[str] | None = None
        if payload is not None:
            literal = [k.value for k in payload.keys
                       if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if len(literal) == len(payload.keys):
                keys = frozenset(literal)
        sites.extend(Emit(name, severity, keys, where) for name in names)

    descend(tree, [])
    return sites, unresolved


def emitted() -> list[Emit]:
    return emit_sites()[0]


#: `type` 열 한 칸에 여러 이벤트가 들어가는 행이 있다.
_ROW = re.compile(r"^\|\s*(?P<types>(?:`[a-z][a-z0-9_]*\.[a-z0-9_/.]+`[^|`]*)+)\|"
                  r"\s*(?P<severity>[^|]*)\|\s*(?P<sender>[^|]*)\|(?P<payload>.*)$",
                  re.MULTILINE)


class Row:
    def __init__(self, severity: str, sender: str, payload: str) -> None:
        self.severity = severity.strip()
        self.sender = sender.strip()
        self.payload = payload

    @property
    def severities(self) -> set[str]:
        """한 칸에 여러 값이 적힌 행이 있다 (`info/error/info`)."""
        return {part.strip() for part in re.split(r"[/,]", self.severity) if part.strip()}

    @property
    def keys(self) -> set[str]:
        """문서가 적은 payload 키. `{goal\\|waypoint, duration_ms}` → 세 개."""
        match = re.search(r"\{([^}]*)\}", self.payload)
        if not match:
            return set()
        parts = re.split(r"[,|]", match.group(1).replace("\\", ""))
        return {p.strip().strip("`?").strip() for p in parts if p.strip()}

    @property
    def unimplemented(self) -> bool:
        return "미구현" in self.payload

    @property
    def robot_sent(self) -> bool:
        return "로봇" in self.sender


def catalogue() -> dict[str, Row]:
    text = REFERENCE.read_text(encoding="utf-8")
    start = text.index("# 8. 이벤트 카탈로그")
    section = text[start:text.index("\n# ", start + 10)]
    rows: dict[str, Row] = {}
    for match in _ROW.finditer(section):
        row = Row(match.group("severity"), match.group("sender"), match.group("payload"))
        for quoted in re.findall(r"`([a-z][a-z0-9_]*\.[a-z0-9_/.]+)`", match.group("types")):
            head, _, rest = quoted.partition(".")
            for leaf in rest.split("/"):
                rows[f"{head}.{leaf}"] = row
    return rows


def test_the_catalogue_is_not_a_wish_list():
    """로봇이 낸다고 적힌 것은 코드에 있어야 한다.

    `safety.watchdog` 은 v1.0 부터 여기 있었고 코드에는 없었다. 계약을 읽고
    `safety.*` 를 구독한 쪽은 조종이 끊겨 로봇이 서도 아무 신호를 받지 못했다.
    """
    names = {site.name for site in emitted()}
    promised = {name for name, row in catalogue().items()
                if row.robot_sent and not row.unimplemented}

    assert not promised - names, (
        "카탈로그가 약속하는데 코드가 내지 않는다: " + ", ".join(sorted(promised - names))
    )


def test_nothing_is_emitted_behind_the_contract():
    """코드가 내는 것은 카탈로그에 있어야 한다.

    `docking.*` 11 종과 `battery.deep` 이 그랬다. 문서화되지 않은 이벤트는 §1 의
    폐기 정책 바깥에 있어, 언제 사라져도 아무도 약속을 깬 것이 아니게 된다.
    """
    documented = set(catalogue())
    undocumented = sorted({site.name for site in emitted()} - documented)

    assert not undocumented, "코드가 내는데 카탈로그에 없다: " + ", ".join(undocumented)


def test_every_documented_payload_key_is_one_the_code_sends():
    """`{}` 안에 적힌 키는 실제로 실려야 한다.

    `nav.stuck` 은 `{timeout_ms}` 로 적혀 있었고 코드는 `timeout_s` 를 보냈다.
    계약대로 읽은 소비자는 KeyError 를 받는다.
    """
    sent: dict[str, set[str]] = {}
    for site in emitted():
        if site.keys is not None:
            sent.setdefault(site.name, set()).update(site.keys)

    wrong: list[str] = []
    for name, row in catalogue().items():
        if name not in sent or row.unimplemented:
            continue
        for key in row.keys - sent[name]:
            wrong.append(f"{name}: 문서에 있는 '{key}' 를 코드가 보내지 않는다")

    assert not wrong, "\n".join(wrong)


def test_every_key_the_code_sends_is_documented():
    documented = catalogue()
    missing: list[str] = []
    for site in emitted():
        row = documented.get(site.name)
        if row is None or site.keys is None:
            continue
        for key in site.keys - row.keys:
            missing.append(f"{site.name} ({site.where}): '{key}' 가 문서에 없다")

    assert not missing, "\n".join(missing)


def test_the_documented_severity_is_the_one_the_code_uses():
    """심각도는 소비자가 경보를 거는 기준이다. 장식이 아니다."""
    documented = catalogue()
    wrong: list[str] = []
    for site in emitted():
        row = documented.get(site.name)
        if row is None:
            continue
        # 부분 문자열이 아니라 값이다. `in` 으로 두면 한 칸에 여러 값이 적히는
        # 순간(Fleet 행들이 이미 그렇다) 검사가 합집합이 되어 아무 값이나 받는다.
        if site.severity not in row.severities:
            wrong.append(f"{site.name} ({site.where}): 코드 {site.severity}, 문서 {row.severity}")

    assert not wrong, "\n".join(wrong)


def test_an_event_this_package_emits_is_marked_as_the_robot_sending_it():
    """발신 열을 잘못 적는 것이 가장 조용한 드리프트다.

    로봇 이벤트를 `Fleet` 으로 바꿔 적으면 `robot_sent` 가 거짓이 되어 wish-list
    검사에서 빠지고, 그 행은 양방향 모두에서 감시 밖으로 나간다 — 한 칸을
    고쳐 쓰는 것으로 가드가 그 이벤트를 통째로 놓게 된다.
    """
    documented = catalogue()
    mislabelled = sorted({
        site.name for site in emitted()
        if site.name in documented and not documented[site.name].robot_sent
    })

    assert not mislabelled, (
        "이 패키지가 내는데 발신이 로봇이 아니라고 적혀 있다: " + ", ".join(mislabelled)
    )


def test_the_fleet_rows_are_excluded_by_their_sender_column():
    """`mission.*` 는 Fleet 이 낸다. 하드코딩한 예외가 아니라 표가 정한다."""
    rows = catalogue()

    assert rows["mission.assigned"].sender == "Fleet"
    assert not rows["mission.assigned"].robot_sent
    assert rows["safety.estop"].robot_sent


def test_no_emit_site_hides_its_name_from_the_guard():
    """이름을 정적으로 못 읽는 발행 자리가 있으면 가드는 그만큼 눈을 감는다.

    `publish(type_=…)`, `publish(f"docking.{stage}")`, `publish(EVT)` 는 모두
    조용히 통과했다. 통과시키는 대신 여기서 실패한다 — 새 발행 자리는 이름을
    리터럴로 적거나, 이 검사를 고치고 왜 그런지 적어야 한다.
    """
    _sites, unresolved = emit_sites()

    assert not unresolved, "\n".join(unresolved)


def test_a_literal_that_looks_like_an_event_is_either_emitted_or_declared():
    """발행 자리를 우회한 이름을 잡는 두 번째 그물.

    래퍼 함수를 거치면 발행 자리 추출은 놓친다 — 그래도 문자열은 소스에 남는다.
    이벤트처럼 생긴 문자열은 실제 발행 이름이거나, 아래 목록에 이유와 함께
    있어야 한다.

    목록이 실제 이벤트를 숨기는 것이 지난 판본의 실패였다. 그래서 목록과 발행
    이름이 겹치면 그것 자체가 실패다 — 숨기려면 먼저 그 교집합을 통과해야 한다.
    """
    #: 이벤트처럼 생겼지만 이벤트가 아닌 것. 각각 그 자리에서 무엇인지 적는다.
    #: **목록이 아니라 자리로** 거르는 것이 원칙이다 — 아래 셋은 자리로 설명되지
    #: 않아서 남은 것들이고, 이 목록이 길어지면 그건 새 *자리* 를 배워야 한다는
    #: 신호이지 한 줄 더 적으라는 신호가 아니다.
    not_events = {
        "safety.limits": "config.changed 의 key 값",
        "robot.identity": "config.changed 의 key 값",
        "auth.tokens": "config.changed 의 key 값",
        "dds.rmw": "config.changed 의 key 값",
        "rosy.sensor_provider": "importlib entry-point group (control_sensor_adapter)",
        "adc.battery": "D-247 hardware.json 장치 id (api/v1/host.py 토픽 판정 표)",
        "adc.ultrasonic": "D-247 hardware.json 장치 id (api/v1/host.py 토픽 판정 표)",
    }
    names = {site.name for site in emitted()}

    overlap = sorted(set(not_events) & names)
    assert not overlap, (
        "이 목록이 실제 발행 이벤트를 숨기고 있다: " + ", ".join(overlap))

    capabilities = _declared_capability_names()
    overlap = sorted(capabilities & names)
    assert not overlap, (
        "CAP-001/concept 표의 이름이 이벤트로도 발행된다: " + ", ".join(overlap))

    unclassified: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        spoken_for = _literals_with_another_job(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value
            if (not _EVENT_SHAPED_LITERAL.fullmatch(value)
                    or value in names or value in not_events):
                continue
            if (value in spoken_for or value in capabilities
                    or value.rpartition(".")[2] in _FILE_SUFFIXES):
                continue
            unclassified.append(f"{_origin(path)}:{node.lineno}: {value}")

    assert not unclassified, (
        "이벤트처럼 생긴 문자열인데 발행 이름도 아니고 목록에도 없다:\n"
        + "\n".join(unclassified))


def test_the_extractor_reads_the_shapes_this_package_actually_uses():
    """추출기가 조용히 아무것도 못 찾으면 위의 모든 검사가 공허해진다."""
    sites = emitted()
    names = {site.name for site in sites}

    # 실제 49 개다(2026-09-22). 느슨하게 두면 여럿이 조용히 사라져도 통과한다.
    assert len(names) >= 46, f"only found {len(names)}"
    # 직접 호출, 튜플 수집, 조건식 이름 — 세 가지 모양이 모두 잡혀야 한다.
    assert "nav.started" in names            # publish("...", data={...})
    assert "power.mode_changed" in names     # pending.append((...))
    assert "docking.charge_lost" in names    # "a" if cond else "b"
    assert any(site.keys for site in sites if site.name == "safety.watchdog")


@pytest.mark.parametrize("event", ["battery.deep", "safety.watchdog", "docking.failed"])
def test_the_events_this_change_was_about_are_covered(event):
    """회귀 방지: 이 셋이 각각 이 파일이 존재하는 이유다."""
    assert event in catalogue()
    assert event in {site.name for site in emitted()}


# --- 추출기 자신에 대한 검사 ------------------------------------------------
#
# 위의 검사들은 전부 "추출기가 발행 지점을 다 찾는다"에 기대고 있다. 그
# 전제가 틀리면 전부 공허해지고, 틀렸다는 사실은 조용하다. 그래서 합성
# 소스로 직접 묻는다.


def _names_and_blind(source: str) -> tuple[set[str], list[str]]:
    return _names_and_blind_at(source, "<test>")


def _names_and_blind_at(source: str, origin: str) -> tuple[set[str], list[str]]:
    sites, unresolved = scan(source, origin)
    return {site.name for site in sites}, unresolved


@pytest.mark.parametrize("source,expected", [
    ('self._events.publish("nav.started", data={"goal": 1})', "nav.started"),
    ('svc.events.publish("nav.started", data={"goal": 1})', "nav.started"),
    ('self.core.events.publish("nav.started", data={"goal": 1})', "nav.started"),
    # 허용 목록이 아니라 제외 목록이므로, 버스를 어디에 담아도 잡힌다.
    ('events.publish("nav.started", data={"goal": 1})', "nav.started"),
    ('self.bus.publish("nav.started", data={"goal": 1})', "nav.started"),
    ('self._emit("nav.started", "info", {"goal": 1})', "nav.started"),
    # 이름을 키워드로 적어도 자리는 같다.
    ('self._events.publish(type_="nav.started", data={"goal": 1})', "nav.started"),
    # 튜플로 모아 두었다가 내는 것.
    ('pending.append(("nav.started", "info", {"goal": 1}))', "nav.started"),
])
def test_the_shapes_that_publish_are_all_seen(source, expected):
    names, blind = _names_and_blind(source)

    assert expected in names, f"{source} 를 놓쳤다"
    assert not blind


@pytest.mark.parametrize("source", [
    'self._events.publish(f"docking.{stage}", data={})',      # f-string
    'self._events.publish(EVENT_NAME, data={})',              # 모듈 상수
    'self._events.publish(name, data={})',                    # 지역 변수
    'self._events.publish(NAMES[0], data={})',                # 첨자
    'self._events.publish("nav." + suffix, data={})',         # 이어붙이기
    'self._events.publish(data={})',                          # 이름 자리가 없다
])
def test_a_name_the_guard_cannot_read_is_reported_not_skipped(source):
    """조용히 넘기면 가드는 통과시키는 법을 하나 더 배운 것뿐이다."""
    names, blind = _names_and_blind(source)

    assert not names
    assert blind, f"{source} 가 조용히 지나갔다"


def test_a_camera_frame_is_not_mistaken_for_an_event():
    names, blind = _names_and_blind(
        "self._svc.vision.publish(bytes(msg.data), captured_at=1.0, frame_id='cam')")

    assert not names and not blind


def test_a_named_publish_on_the_frame_store_is_still_read():
    """빼는 것은 소유자 이름만이 아니라 모양까지다. 이름 자리에 이벤트
    이름이 오면 그것은 발행이다."""
    names, blind = _names_and_blind('svc.vision.publish("vision.stale", data={"age_s": 1})')

    assert names == {"vision.stale"} and not blind


def test_a_ros_publisher_is_not_mistaken_for_the_bus():
    names, blind = _names_and_blind("self.cmd_vel_pub.publish(msg)")

    assert not names and not blind


def test_a_publisher_that_breaks_the_naming_convention_fails_loudly():
    """모르는 모양은 통과가 아니라 실패다.

    `_pub` 규약을 벗어난 ROS 퍼블리셔가 생기면 여기가 빨개진다 — 이름을
    고치거나 규약을 고치라는 뜻이고, 어느 쪽이든 사람이 보게 된다. 반대로
    적었다면(버스만 허용) 그 자리는 조용히 사라졌을 것이다.
    """
    _names, blind = _names_and_blind("self.wheels.publish(msg)")

    assert blind


@pytest.mark.parametrize("label,source", [
    # 중계는 이름이 **다른 자리에서 읽히기 때문에** 봐주는 것이다. 그 근거가
    # 없는 이름은 모양이 닮았다고 봐주지 않는다.
    ("평범한 지역 변수",
     "def send(self, kind):\n"
     "    self._events.publish(kind, data={})\n"),
    # 리뷰가 실제 패키지의 observability.py 에 한 줄 넣어 641 개 테스트를 전부
    # 초록으로 통과시킨 모양이다. for 튜플 언팩이라는 것만으로 봐주면
    # `component`·`name`·`key`·`value`·`source` 가 통째로 면제된다.
    ("중계 함수 밖의 for 튜플 언팩",
     "def metrics(svc):\n"
     "    for component, health in items:\n"
     "        svc.events.publish(component, severity='error', data={'health': 1})\n"),
    ("모듈 수준의 for 튜플 언팩",
     "for component, health in items:\n"
     "    svc.events.publish(component, data={})\n"),
    # `_emit` 파라미터는 그 함수 **안에서만** 중계다.
    ("_emit 파라미터를 다른 함수에서 쓴 것",
     "def _emit(self, type_, severity, data):\n"
     "    self._events.publish(type_, severity=severity, data=data)\n"
     "def elsewhere(self):\n"
     "    self._events.publish(type_, data={})\n"),
    # 이름만 `_emit…` 인 헬퍼는 중계가 아니다.
    ("발행하지 않는 _emit… 헬퍼",
     "def _emit_label(self, type_):\n"
     "    return type_.upper()\n"
     "def send(self, type_):\n"
     "    self._events.publish(type_, data={})\n"),
    # **발행하는** `_emit…` 헬퍼도 마찬가지다. 파라미터를 봐주는 근거는 그
    # 이름이 `_emit(…)` 호출 자리에서 읽힌다는 것인데, 추출기가 읽는 호출
    # 이름은 정확히 `_emit` 뿐이다. 리뷰가 실제 패키지에서 이름 한 단어를
    # 늘리는 것만으로 같은 구멍을 다시 통과했다.
    ("발행하는 _emit… 래퍼 함수",
     "def _emit_component_health(component):\n"
     "    svc.events.publish(component, severity='error', data={'health': 1})\n"
     "def metrics(svc):\n"
     "    for component, health in items:\n"
     "        _emit_component_health(component)\n"),
    ("발행하는 _emit… 메서드",
     "class S:\n"
     "    def _emit_health(self, component):\n"
     "        self._events.publish(component, data={})\n"),
    # ROS 퍼블리셔는 함수를 중계로 승격시키지 않는다.
    ("ROS 퍼블리셔로 중계 행세를 한 것",
     "def _emit_wheels(self, kind):\n"
     "    self.cmd_vel_pub.publish(msg)\n"
     "    self._events.publish(kind, data={})\n"),
    # for 튜플 언팩은 **중계가 받은 것을 푸는 자리**일 때만 봐준다. 관계없는
    # 이터러블 위의 루프는 그냥 루프다 — 리뷰가 실제 `power/manager.py` 의
    # `_emit_all` 에 이런 루프를 하나 더 붙여 659 개 테스트를 전부 초록으로
    # 통과시켰다.
    ("중계 안이지만 관계없는 이터러블 위의 for",
     "def _emit(self, type_, severity, data):\n"
     "    for name, value in EXTRA:\n"
     "        self._events.publish(name, data={})\n"),
    ("_emit_all 에 덧붙인 두 번째 루프",
     "def _emit_all(self, pending):\n"
     "    for type_, severity, data in pending:\n"
     "        self._events.publish(type_, severity=severity, data=data)\n"
     "    for component, health in self._component_health().items():\n"
     "        self._events.publish(component, severity='error', data={'h': health})\n"),
    # 다시 대입하면 호출 자리에서 읽은 이름과 발행되는 이름이 다르다.
    ("_emit 안에서 파라미터를 다시 대입한 것",
     "def _emit(self, type_, severity, data):\n"
     "    type_ = compute()\n"
     "    self._events.publish(type_, severity=severity, data=data)\n"),
])
def test_the_relay_allowance_does_not_cover_a_name_read_nowhere_else(label, source):
    _names, blind = _names_and_blind(source)

    assert blind, f"{label} 이(가) 조용히 지나갔다"


@pytest.mark.parametrize("imports,spelling", [
    ("", "'critical'"),
    ("from core_common.protocol.schemas import Severity\n", "Severity.CRITICAL"),
    ("from core_common.protocol import schemas\n", "schemas.Severity.CRITICAL"),
    # 접미사로 넘겨짚으면 이 한 줄이 그 발행 지점을 조용히 놓친다.
    ("from core_common.protocol.schemas import Severity as Sev\n", "Sev.CRITICAL"),
    ("from core_common.protocol.schemas import Severity as Level\n", "Level.CRITICAL"),
])
def test_the_severity_is_read_however_the_module_spells_it(imports, spelling):
    """그 모듈이 실제로 무엇을 import 했는지가 답이다.

    철자 규칙(`…sev` 로 끝나면 심각도)은 두 방향으로 틀린다: `as Level` 을
    놓치고, `thresholds.severity` 같은 것을 심각도로 읽는다.
    """
    sites, blind = scan(f"{imports}pending.append(('battery.deep', {spelling}, data))\n")

    assert [(site.name, site.severity) for site in sites] == [("battery.deep", "critical")]
    assert not blind


def test_an_enum_this_module_never_imported_is_not_a_severity():
    """`Level.CRITICAL` 이 심각도가 아니면 이것은 발행 튜플도 아니다."""
    names, blind = _names_and_blind("pending.append(('battery.deep', Level.CRITICAL, data))\n")

    assert not names and not blind


def test_a_severity_argument_that_cannot_be_read_is_reported_not_defaulted():
    """조용히 info 로 적어 넣으면, 문서도 info 라고 적혀 있을 때 그 어긋남이
    영영 보이지 않는다."""
    _names, blind = _names_and_blind(
        'self._events.publish("nav.started", severity=level, data={})\n')

    assert blind


def test_an_enum_membership_test_is_not_an_emit_tuple():
    """`BatteryLevel.CRITICAL` 은 심각도가 아니다.

    열거형이면 무엇이든 심각도로 읽으면 `if level not in (BatteryLevel.WARNING,
    BatteryLevel.CRITICAL, BatteryLevel.DEEP)` 이 발행 자리로 잡혀, 가드가
    멀쩡한 코드를 두고 거짓으로 빨개진다.
    """
    names, blind = _names_and_blind(
        "if level not in (BatteryLevel.WARNING, BatteryLevel.CRITICAL, "
        "BatteryLevel.DEEP):\n    pass\n")

    assert not names and not blind


def test_a_tuple_whose_name_cannot_be_read_is_reported_too():
    """호출만 보고하고 튜플은 넘기면, 절전·배터리가 실제로 쓰는 모양이 통째로
    감시 밖이다 — 새 이벤트가 가장 쉬운 길로 새는 자리였다."""
    _names, blind = _names_and_blind(
        "pending.append((kind, 'critical', {'percent': pct}))\n")

    assert blind


def test_a_relay_is_read_at_the_tuple_and_its_own_body_is_not_trusted():
    """이름은 튜플 리터럴 쪽에서 읽는다.

    그리고 **고정되지 않은** 중계의 몸통은 면제받지 못한다 — 합성 소스는
    `PINNED_RELAYS` 에 없으므로 그 안의 동적 발행이 그대로 걸린다. 이것이
    이 설계의 요점이다: 면제는 "이렇게 생겼으면"이 아니라 "이 함수의 이
    몸통이면"이다.
    """
    names, blind = _names_and_blind(
        "def _emit_all(self, pending):\n"
        "    for type_, severity, data in pending:\n"
        "        self._events.publish(type_, severity=severity, data=data)\n"
        "\n"
        "def collect(self):\n"
        "    pending.append(('battery.deep', 'critical', {'percent': 3}))\n")

    assert names == {"battery.deep"}
    assert blind, "an unpinned relay body must not be trusted"


def test_a_severity_left_to_the_default_is_read_as_info():
    """기본값에 기대는 발행 지점을 검사에서 빼면 3 분의 1 이 감시 밖이다."""
    sites, _blind = scan('self._events.publish("nav.started", data={})')

    assert [site.severity for site in sites] == ["info"]


def test_a_plain_tuple_is_not_read_as_an_emit():
    """`("config.yaml", "path")` 나 `x in ("mission.assigned", ...)` 같은 것."""
    names, blind = _names_and_blind(
        'PATHS = ("config.yaml", "rosy.yaml")\n'
        'if kind in ("mission.assigned", "mission.done"):\n'
        '    pass\n')

    assert not names and not blind


def test_a_non_severity_argument_is_not_read_as_the_severity():
    """자리를 정해 읽지 않으면 `source="error"` 가 심각도가 된다."""
    sites, _blind = scan('self._events.publish("nav.started", source="error", data={})')

    assert [site.severity for site in sites] == ["info"]


def test_the_documented_severity_is_matched_by_value_not_by_substring():
    row = Row("info", "로봇", "{}")

    assert row.severities == {"info"}
    assert Row("info/error/info", "Fleet", "{}").severities == {"info", "error"}


def test_the_relay_bodies_that_get_the_exemption_are_the_ones_we_reviewed():
    """면제는 좁히는 것만으로는 부족하다. **셀 수 있어야** 한다.

    네 번의 리뷰가 모두 이 면제로 들어왔다. 매번 "어떤 모양이면 중계인가"를
    좁혔지만 그 질문에는 끝이 없다 — 근거는 데이터 흐름("이 이름은 caller 가
    준 것이다")인데 정적으로 볼 수 있는 것은 철자뿐이기 때문이다. 마지막
    판본은 `for … in <파라미터>` 를 요구했고, 루프 바로 위에서 그 파라미터를
    다시 대입하는 것으로 뚫렸다.

    그래서 모양을 묻기를 그만두었다. 면제는 이 네 함수의 **이 몸통들** 에만
    준다. 한 줄이라도 바뀌면 지문이 달라지고, 면제가 사라지고, 그 안의 동적
    발행이 곧바로 걸린다. 이 값을 손으로 고치는 것이 "이 함수를 다시 읽었다"는
    서명이다.
    """
    assert relay_fingerprints() == PINNED_RELAYS, (
        "중계 함수의 몸통이 바뀌었거나 새 중계가 생겼다. 그 함수를 읽고, "
        "발행되는 이름이 정말로 호출 자리나 튜플 리터럴에서 오는지 확인한 뒤 "
        "PINNED_RELAYS 를 고칠 것.")


def test_a_ros_publisher_does_not_make_a_function_a_relay():
    """`_publishes` 가 ROS 퍼블리셔를 세면, 그 함수 안의 튜플 발행 자리가
    조용히 사라진다 — 호출만 세는 것으로는 튜플 모양을 못 막는다."""
    _names, blind = _names_and_blind(
        "def _emit(self, type_, severity):\n"
        "    self.cmd_vel_pub.publish(msg)\n"
        "    pending.append((type_, severity, {'a': 1}))\n")

    assert blind


def test_a_pinned_relay_whose_body_changed_is_no_longer_exempt():
    """면제는 그 이름에 주는 것이 아니라 **그 몸통** 에 준다.

    이름만 맞으면 봐주는 것은 지난 판본들과 같은 실수다 — 리뷰는 실제
    `_emit_all` 의 루프 바로 위에 한 줄을 더해 통과했고, 함수의 이름도 위치도
    그대로였다.
    """
    origin, qualname = next(iter(PINNED_RELAYS))
    holder = qualname.rpartition(".")[0]

    _names, blind = _names_and_blind_at(
        f"class {holder}:\n"
        "    def _emit(self, type_, severity, data):\n"
        "        type_ = self._rewrite(type_)\n"
        "        self._events.publish(type_, severity=severity, data=data)\n",
        origin)

    # 두 가지가 모두 나와야 한다. 지문을 안 보고 이름만으로 건너뛰면 안내
    # 메시지는 그대로 나오지만 **몸통은 여전히 건너뛰어져** 그 안의 동적
    # 발행이 보고되지 않는다 — 안내만 보고 통과시키면 그것을 놓친다.
    assert any("PINNED_RELAYS" in message for message in blind), blind
    assert any("정적으로 읽을 수 없다" in message for message in blind), (
        "the changed body was still skipped", blind)


def test_a_collected_emit_written_as_a_list_is_read_too():
    """`append((…))` 와 `append([…])` 는 같은 일을 한다. 튜플만 보면 대괄호
    하나로 수집 경로 전체가 감시 밖으로 나간다."""
    names, blind = _names_and_blind(
        "pending.append(['battery.deep', 'critical', {'percent': 3}])\n")

    assert names == {"battery.deep"} and not blind


def test_a_two_element_emit_has_no_severity_slot_to_fail_on():
    """`(name, payload)` 의 둘째 칸은 payload 다. 거기서 심각도를 읽으려 하면
    "심각도를 못 읽었다"고 **틀린 이유로** 빨개진다."""
    sites, blind = scan("pending.append(('nav.started', {'goal': 1}))\n")

    assert [(site.name, site.severity) for site in sites] == [("nav.started", "info")]
    assert not blind
    assert sites[0].keys == frozenset({"goal"})


@pytest.mark.parametrize("name", ["imu.bno055_fault", "docking.stage.begin", "nav.dwb_stuck"])
def test_a_name_with_a_digit_or_a_third_segment_is_still_an_event(name):
    """좁은 정규식은 **양쪽에서 동시에** 눈을 감는다.

    발행 자리에서도 문서 표에서도 같은 모양을 요구했으므로, 숫자가 든 이름은
    코드에서도 카탈로그에서도 안 보이고 가드는 "일치한다"고 답했다 — 이 파일이
    없애려던 `battery.deep` 의 실패가 정규식으로 다시 쓰인 것이다. 이 저장소의
    보드가 `rosy_imu_bno055` 라 이런 이름은 한 커밋 거리에 있다.
    """
    sites, blind = scan(f'self._events.publish("{name}", severity="error", data={{"c": 1}})\n')

    assert [site.name for site in sites] == [name]
    assert not blind


def test_a_dotted_name_the_guard_cannot_recognise_is_reported():
    """모르는 모양은 통과가 아니라 실패다."""
    _names, blind = _names_and_blind(
        'self._events.publish("Power.Brownout", severity="error", data={})\n')

    assert blind


def test_the_document_table_reads_the_same_name_shapes_the_code_does():
    """두 정규식은 함께 넓어져야 한다.

    코드 쪽만 넓히면 `imu.bno055_fault` 는 발행으로는 보이는데 표에서는 안
    읽혀 "문서에 없다"고 빨개진다. 표 쪽만 넓히면 그 반대다. 좁은 채로 두면
    **양쪽이 함께 눈을 감고** 가드는 일치한다고 답한다 — 그것이 가장 나쁘다.
    """
    row = ("| `imu.bno055_fault` | error | 로봇 | `{code}` |\n"
           "| `docking.stage.begin` | info | 로봇 | `{}` |\n")
    found = [name for match in _ROW.finditer(row)
             for name in re.findall(r"`([a-z][a-z0-9_]*\.[a-z0-9_/.]+)`", match.group("types"))]

    assert found == ["imu.bno055_fault", "docking.stage.begin"]


def test_a_dotless_string_in_the_name_slot_is_not_reported():
    """`if state in ("warning", "critical")` 은 발행 자리가 아니다."""
    _names, blind = _names_and_blind('if state in ("warning", "critical"):\n    pass\n')

    assert not blind


def test_a_bus_whose_attribute_ends_in_pub_is_still_a_bus():
    """이름 규약만으로 빼면, 버스를 담은 속성이 우연히 `_pub` 으로 끝날 때
    그 발행 자리가 통째로 사라진다. 호출 모양까지 본다."""
    names, blind = _names_and_blind(
        'self._events_pub.publish("nav.started", data={"goal": 1})\n')

    assert names == {"nav.started"} and not blind

    # 진짜 ROS 퍼블리셔는 여전히 조용하다.
    quiet_names, quiet_blind = _names_and_blind("self.cmd_vel_pub.publish(msg)\n")
    assert not quiet_names and not quiet_blind


def test_a_collection_of_four_is_not_a_way_out():
    """`2 <= len <= 3` 으로 세면 원소 하나를 더 붙여 수집 경로를 빠져나간다."""
    _names, blind = _names_and_blind(
        "pending.append((kind, 'critical', {'percent': 3}, ts))\n")

    assert blind


def test_the_payload_is_the_data_keyword_not_the_first_dict_seen():
    sites, _blind = scan(
        'self._events.publish("nav.started", context={"zzz": 1}, data={"goal": 2})\n')

    assert [site.keys for site in sites] == [frozenset({"goal"})]


def test_a_changed_pinned_body_says_what_to_do_about_it():
    """"이름을 정적으로 읽을 수 없다"만 나오면, 루프 변수 이름 하나 바꾼 사람은
    없는 결함을 찾아 헤매다가 고정 목록을 지우는 쪽으로 간다."""
    origin, qualname = next(iter(PINNED_RELAYS))
    holder = qualname.rpartition(".")[0]

    _names, blind = _names_and_blind_at(
        f"class {holder}:\n"
        "    def _emit(self, type_, severity, data):\n"
        "        self._events.publish(type_, severity=severity, data=data)\n",
        origin)

    assert any("PINNED_RELAYS" in message for message in blind), blind


def test_the_fingerprint_does_not_depend_on_the_python_version():
    """개발 호스트(3.14)와 CI·Pi(3.12)가 같은 값을 내야 고정 목록이 의미가 있다.

    `ast.dump` 는 3.13 에서 출력이 바뀌었고, 그 해시로 고정한 값은 3.12 에서
    네 중계를 모두 "몸통이 바뀌었다"고 빨갛게 만들었다. 고정 스니펫의 지문을
    상수와 비교해, 버전을 타는 정규화로 돌아가면 어느 쪽에서든 여기서 걸린다.
    주석과 docstring 은 지문에 들어가지 않는다.
    """
    source = ("def _emit(self, a):\n"
              "    \"\"\"doc\"\"\"\n"
              "    self._events.publish(a, data={})  # comment\n")
    bare = "def _emit(self, a):\n    self._events.publish(a, data={})\n"

    assert fingerprint(ast.parse(source).body[0]) == "0a2aebee7eb5a74a"
    assert fingerprint(ast.parse(bare).body[0]) == "0a2aebee7eb5a74a"
