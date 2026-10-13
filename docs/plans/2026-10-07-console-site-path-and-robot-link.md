# Console Site Path and Robot Link Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 관제(`/console`) 등록 로봇 칸에 사이트 경로 세 줄과, 문제가 있는 로봇 카드에만 링크 한 단어를 붙인다. 판단은 이미 있는 gather와 주소 판정으로만 한다.

**Architecture:** Fleet의 순수 함수 `classify_link`가 로봇 행의 `link`를 고른다. `FleetConsole.snapshot`이 gather 예외가 아직 살아 있는 자리에서 한 번 부르고, 주소 상태는 `address_reasons`가 이미 읽는 메모리 스캔에서 스냅샷당 한 번만 받는다. 새 프로브와 새 경로는 없다. 새 화면은 `link`와 기존 조회의 HTTP 결과만 읽는다. 링크 종류를 예외 클래스 이름으로 고르지 않는다. 자리는 `index.html` 등록 로봇 패널 안, `#roster` 위다. D-493의 지도 3 : 오른쪽 열 2는 그대로다.

**Tech Stack:** Python 3.14 (`python`, 이 호스트의 `python3`에는 PyYAML이 없을 수 있다), FastAPI, httpx, 기존 콘솔 정적 페이지(요소 하나와 `node --test`). ROS, 장치, 현장 수용은 이 계획이 열지 않는다.

**기준:** [D-499](../adr/D-499-console-site-path-and-robot-link.md) Proposed. 구현이 끝나도 이 계획 안에서 Status를 Accepted로 바꾸지 않는다. 로컬 미리보기 `http://127.0.0.1:9477/`는 제품이 아니므로 저장소에 넣지 않는다.

---

## 구현 위치

워크트리 `rosy-platform/.worktrees/site-link-monitor`, 브랜치 이름은 `docs/site-link-monitor` 그대로다. 새 워크트리와 새 브랜치를 만들지 않는다. 공유 `main` 체크아웃에는 쓰지 않는다.

스테이징은 `git add <경로>`만 한다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 커밋 전에 `git diff --cached --name-only`가 그 태스크의 경로와 같은지 본다. `--amend`, `rebase`, `reset`, `stash`는 쓰지 않는다. 착지(`git merge --ff-only`)와 푸시는 사용자가 말한 뒤에만 한다. 이 계획의 커밋 명령은 구현을 시작한 뒤에만 실행한다.

스크래치와 pytest 출력은 `X:\DevTemp\site-link-monitor\`에 둔다. 공개 저장소 파일에 실험실 주소, 토큰, 페어링 자료를 적지 않는다. 시험의 베이스 URL은 기존처럼 `http://127.0.0.1`만 쓴다.

각 태스크의 호스트 시험 통과는 장치 수용이 아니다.

## 고정된 분류

`classify_link(exc, *, scheme, address_status)` 반환은 `up`, `moved`, `tls-refused`, `protocol`, `unreachable`, 또는 `None`이다. `None`이면 행에 `link` 키를 넣지 않는다.

순서는 이 코드 그대로다.

1. `exc is None`이면 `up`이다. 주소 상태가 `seen_at_other_address`여도 `up`이다.
2. 그 다음 주소 상태가 `seen_at_other_address`이면 `moved`다. 401, 그 외 `RobotApiError`, `protocol`보다 앞이다.
3. `RobotApiError.status == 401`이면 `tls-refused`다.
4. 그 외 `RobotApiError`는 `None`이다.
5. `scheme == "http"`이고 예외가 `httpx.RemoteProtocolError`이면 `protocol`이다. 집합은 이 클래스 하나다.
6. 나머지는 `unreachable`이다. `https`의 `RemoteProtocolError`, `ssl.SSLError`, `httpx.ConnectError`, 타임아웃은 여기다. https로 평문 HTTP에 물은 경우를 `protocol`로 올리지 않는다.

새 파일 `link-tag.js`와 `site-path.js`는 예외 클래스 이름을 적지 않는다. `roster.js`의 기존 `REACH_LABEL`(`ConnectError` 등)은 지우지 않는다. `link`가 없는 옛 Fleet이 클래스 이름을 `error.code`로 보낼 때 그 표가 한국어로 옮긴다. `link`가 있으면 그 줄은 그리지 않으므로, 새 분류를 클래스 이름과 비교하는 코드는 넣지 않는다.

## 화면 문장

사이트 경로는 세 줄이다. 첫 조회 전에는 각각 `확인 중`이다.

| 줄 | 정상 | 그 밖 |
|---|---|---|
| 프록시 | `GET /healthz`가 200이고 본문 키가 `status` 하나, 값이 `ok` | 연결이 끝나지 않거나 본문이 다르면 `끊김` |
| Fleet | 기존 `GET /api/fleet/state`가 HTTP 상태와 함께 끝나면 `정상`. 200과 401을 가리지 않는다 | 연결이 끝나지 않으면 `끊김`. 401은 지금 토큰 잠금을 유지하고 Fleet 끊김으로 적지 않는다 |
| Vision | 기존 `GET /api/fleet/vision/sources`가 200이고 이름이 있으면 그 이름을 쉼표로 잇는다. 200이고 비면 `없음` | 연결이 끝나지 않으면 `끊김`. 끝난 비-200(503 `VISION_PREVIEW_DISABLED` 포함)은 `끊김`이 아니다. 단어는 `응답`이고 상태 코드를 붙인다 |

로봇 태그는 `link`가 `unreachable`, `moved`, `tls-refused`, `protocol`일 때만 붙인다. `up`과 없는 키와 모르는 값은 태그를 만들지 않는다. 태그가 있으면 지금의 `로봇이 거절:` / `닿지 않음:` 줄은 그리지 않는다. 그 줄이 예외 클래스 이름을 그대로 보여 주기 때문이다. `addressReason`은 그대로 그린다.

| link | 태그 | 다음 |
|---|---|---|
| unreachable | 닿지 않음 | 다음: 주소 확인. `outside_scanned_subnets` 문장은 `addressReason`이 유지한다 |
| moved | 주소 이동 | 추가 문장 없음. `addressReason`의 새 주소로 옮기기 문장이 다음이다 |
| tls-refused | 인증 거부 | 버튼 `다음: 관제 토큰`이 기존 `#console-token`에 포커스만 준다. 망 수리로 적지 않는다 |
| protocol | 프로토콜 | 문장 `등록된 base URL의 스킴으로 로봇 HTTP가 끝나지 않습니다.` 텍스트 `다음: 등록된 Fleet base URL`. 스킴을 바꾸는 버튼은 없다 |

비상 정지, 목표, 임무, 주소 옮기기 버튼의 자리는 그대로다. `POST /api/v1/host/network/mode`, `POST /api/v1/host/network/connect`, nmcli, Docker 수치, 바이트 그래프, 공유기 화면은 넣지 않는다.

---

### Task 1: 링크 분류 순수 함수

**Files:**
- Create: `operations/fleet/fleet/server/link_class.py`
- Test: `operations/fleet/test/test_link_class.py`

**Step 1: Write the failing test**

`operations/fleet/test/test_link_class.py` 전체를 이렇게 둔다.

```python
"""D-499: robot link class from the gather outcome. No HTTP."""

import ssl

import httpx

from fleet.server.link_class import classify_link
from fleet.swarm.transport import RobotApiError


def _refused(status):
    return RobotApiError("rosy_01", status, "HTTP_%s" % status, "no")


def test_success_is_up_even_when_the_address_moved():
    assert classify_link(None, scheme="http", address_status="seen_at_other_address") == "up"


def test_a_failed_gather_at_another_address_is_moved_ahead_of_protocol_and_401():
    protocol = httpx.RemoteProtocolError("disconnected")
    assert classify_link(protocol, scheme="http",
                         address_status="seen_at_other_address") == "moved"
    assert classify_link(_refused(401), scheme="https",
                         address_status="seen_at_other_address") == "moved"
    assert classify_link(_refused(500), scheme="http",
                         address_status="seen_at_other_address") == "moved"


def test_http_401_is_tls_refused_and_any_other_robot_api_error_omits_link():
    assert classify_link(_refused(401), scheme="https", address_status=None) == "tls-refused"
    assert classify_link(_refused(403), scheme="https", address_status=None) is None
    assert classify_link(_refused(500), scheme="http", address_status="outside_scanned_subnets") is None


def test_plain_http_remote_protocol_error_is_protocol():
    exc = httpx.RemoteProtocolError("disconnected")
    assert classify_link(exc, scheme="http", address_status=None) == "protocol"
    assert classify_link(exc, scheme="HTTP", address_status="unknown") == "protocol"


def test_https_protocol_errors_and_connect_failures_stay_unreachable():
    remote = httpx.RemoteProtocolError("disconnected")
    assert classify_link(remote, scheme="https", address_status=None) == "unreachable"
    assert classify_link(httpx.ConnectError("refused"), scheme="http", address_status=None) == "unreachable"
    assert classify_link(ssl.SSLError("certificate"), scheme="https", address_status=None) == "unreachable"
    assert classify_link(TimeoutError("slow"), scheme="http", address_status="outside_scanned_subnets") == "unreachable"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest operations/fleet/test/test_link_class.py -q -p no:cacheprovider`

Expected: FAIL, `fleet.server.link_class`를 가져오지 못한다.

**Step 3: Write minimal implementation**

`operations/fleet/fleet/server/link_class.py`:

```python
"""D-499 robot link class. The browser reads the returned word and never an exception name."""

from __future__ import annotations

import httpx

from fleet.swarm.transport import RobotApiError

# Plain HTTP against a TLS-only CORE. Do not add SSLError or ConnectError here.
_PROTOCOL = (httpx.RemoteProtocolError,)


def classify_link(exc: BaseException | None, *, scheme: str,
                  address_status: str | None) -> str | None:
    """Return a closed link word, or None when the row must omit `link`."""
    if exc is None:
        return "up"
    if address_status == "seen_at_other_address":
        return "moved"
    if isinstance(exc, RobotApiError):
        if exc.status == 401:
            return "tls-refused"
        return None
    if scheme.lower() == "http" and isinstance(exc, _PROTOCOL):
        return "protocol"
    return "unreachable"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest operations/fleet/test/test_link_class.py -q -p no:cacheprovider`

Expected: PASS, 5 passed.

**Step 5: Commit**

```bash
git add operations/fleet/fleet/server/link_class.py operations/fleet/test/test_link_class.py
git diff --cached --name-only
git commit -m "test: pin the console robot link classes"
```

---

### Task 2: 스냅샷 행에 link를 붙인다

**Files:**
- Modify: `operations/fleet/fleet/server/console.py` (`snapshot`, 약 250–304행)
- Modify: `operations/fleet/test/test_server_console.py`
- Test: `operations/fleet/test/test_link_on_snapshot.py`

주소 공급자는 Task 3에서 연결한다. 이 태스크의 기본값은 빈 상태다. 공급자가 예외를 내도 스냅샷은 로봇 행을 유지한다.

**Step 1: Write the failing test**

`operations/fleet/test/test_link_on_snapshot.py`:

```python
"""D-499: snapshot stamps link from the gather exception. No second probe."""

import httpx

from fakes import FakeRobot, run
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError


def _console(robot, scheme):
    endpoint = RobotEndpoint(robot_id=robot.robot_id,
                             base_url="%s://127.0.0.1:8080" % scheme, token="t")
    return FleetConsole([endpoint], [robot])


def test_a_successful_gather_is_up_and_a_401_is_tls_refused():
    up = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    row = run(_console(up, "http").snapshot())["robots"][0]
    assert row["online"] is True and row["link"] == "up"

    refused = FakeRobot("rosy_02")
    refused.state_error = RobotApiError("rosy_02", 401, "UNAUTHORIZED", "bad token")
    row = run(_console(refused, "https").snapshot())["robots"][0]
    assert row["online"] is False and row["link"] == "tls-refused"
    assert row["error"]["code"] == "UNAUTHORIZED"


def test_a_non_401_robot_api_error_omits_link():
    robot = FakeRobot("rosy_01")
    robot.state_error = RobotApiError("rosy_01", 500, "HTTP_500", "boom")
    row = run(_console(robot, "http").snapshot())["robots"][0]
    assert "link" not in row
    assert row["error"]["reachable"] is True


def test_plain_http_remote_protocol_error_is_protocol_and_https_is_unreachable():
    plain = FakeRobot("rosy_01")
    plain.state_error = httpx.RemoteProtocolError("disconnected")
    assert run(_console(plain, "http").snapshot())["robots"][0]["link"] == "protocol"

    secure = FakeRobot("rosy_02")
    secure.state_error = httpx.RemoteProtocolError("disconnected")
    assert run(_console(secure, "https").snapshot())["robots"][0]["link"] == "unreachable"


def test_address_status_is_read_once_and_a_provider_failure_keeps_the_row():
    robot = FakeRobot("rosy_01")
    robot.state_error = httpx.ConnectError("down")
    console = _console(robot, "http")
    calls = {"n": 0}

    def status():
        calls["n"] += 1
        return {"rosy_01": "seen_at_other_address"}

    console.set_link_address_status(status)
    row = run(console.snapshot())["robots"][0]
    assert calls["n"] == 1 and row["link"] == "moved"

    def blow():
        raise RuntimeError("scan store")

    console.set_link_address_status(blow)
    row = run(console.snapshot())["robots"][0]
    assert row["robot_id"] == "rosy_01" and row["link"] == "unreachable"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest operations/fleet/test/test_link_on_snapshot.py -q -p no:cacheprovider`

Expected: FAIL, `set_link_address_status`가 없거나 `link`가 없다.

**Step 3: Write minimal implementation**

`console.py`에 `from urllib.parse import urlsplit`과 `from fleet.server.link_class import classify_link`를 추가한다. `__init__`에서 다른 콜백 옆에 `self._link_address_status = None`을 둔다.

```python
def set_link_address_status(self, provider) -> None:
    """robot_id -> address status from the latest scan. None skips the lookup.

    The provider must not contact a robot. snapshot calls it once.
    """
    self._link_address_status = provider
```

`snapshot`의 `results = await asyncio.gather(...)` 직후, 로봇 루프 전에:

```python
statuses = {}
provider = self._link_address_status
if provider is not None:
    try:
        statuses = provider() or {}
    except Exception:
        statuses = {}
```

각 행을 만든 직후(`gather_source`까지 채운 뒤, `_remember` 전) 그 행에:

```python
scheme = urlsplit(self._registered_endpoints.get(robot_id, "")).scheme
exc = result if isinstance(result, BaseException) else None
link = classify_link(exc, scheme=scheme, address_status=statuses.get(robot_id))
if link is not None:
    row["link"] = link
```

`online`, `error`, `state`, `goal`의 기존 할당은 바꾸지 않는다. `_task_dispatch_loop`은 고치지 않는다.

**Step 4: Run test to verify it passes**

Run: `python -m pytest operations/fleet/test/test_link_on_snapshot.py operations/fleet/test/test_server_console.py -q -p no:cacheprovider`

Expected: PASS. 기존 스냅샷 시험이 `link` 추가로 깨지면, 그 단언이 행의 키 목록을 통째로 고정한 경우에만 기대 목록에 `link`를 더한다. 다른 기대값은 느슨하게 만들지 않는다.

**Step 5: Commit**

이 태스크는 아직 커밋하지 않는다. Task 3이 같은 행의 주소 공급을 끝내고, Task 4가 API 문서를 같은 커밋에 넣는다. D-499가 행과 문서를 한 구현 커밋으로 묶는다.

---

### Task 3: 주소 상태는 기존 스캔에서 한 번

**Files:**
- Modify: `operations/fleet/fleet/server/app.py` (`install_discovery_routes`가 끝난 뒤, 약 464–468행 다음)
- Modify: `operations/fleet/fleet/server/app.py`는 `_task_dispatch_loop`(약 634–659행)을 읽기만 한다. 편집하지 않는다.
- Test: `operations/fleet/test/test_link_address_source.py`

**Step 1: Write the failing test**

`operations/fleet/test/test_link_address_source.py`:

```python
"""D-499: link address status reuses address_reasons. It does not gather again."""

from pathlib import Path

from fleet.server.ingest_routes import address_reasons


def test_dispatch_loop_does_not_read_link():
    text = Path("operations/fleet/fleet/server/app.py").read_text(encoding="utf-8")
    start = text.index("async def _task_dispatch_loop")
    end = text.index("async def _mission_feedback_schedule_loop")
    body = text[start:end]
    assert '["link"]' not in body
    assert '.get("link")' not in body


def test_link_status_uses_the_address_reasons_rows():
    """The app wires set_link_address_status to address_reasons robot statuses."""
    app = Path("operations/fleet/fleet/server/app.py").read_text(encoding="utf-8")
    assert "set_link_address_status" in app
    assert "address_reasons" in app
    # The classifier stays the only place that names the protocol exception.
    assert "RemoteProtocolError" not in app


def test_address_reasons_status_map_shape():
    class Console:
        registered_endpoints = {"rosy_01": "http://127.0.0.1:8080"}

    class Hub:
        def __init__(self):
            self.registry = self

        def identity_snapshot(self):
            return {}

    class Discovery:
        def snapshot(self, endpoints, identities, enrolled):
            return {"scanner_online": False, "scanner_state": "off", "devices": None}

    class Enrollment:
        def enrolled_names(self):
            return {}

        def listing(self):
            return None

    result = address_reasons(console=Console(), hub=Hub(), discovery=Discovery(),
                             enrollment=Enrollment())
    assert {row["robot_id"]: row["status"] for row in result["robots"]} == {"rosy_01": "unknown"}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest operations/fleet/test/test_link_address_source.py -q -p no:cacheprovider`

Expected: FAIL, `app.py`에 `set_link_address_status`가 없다.

**Step 3: Write minimal implementation**

`app.py`가 discovery 라우트를 설치한 블록 안, `install_discovery_routes(...)` 호출 다음에:

```python
from fleet.server.ingest_routes import address_reasons

def _link_addresses():
    reasons = address_reasons(console=console, hub=hub, discovery=discovery,
                             enrollment=enrollment)
    return {entry["robot_id"]: entry["status"] for entry in reasons["robots"]}

console.set_link_address_status(_link_addresses)
```

`discovery is None`이면 이 블록에 들어가지 않으므로 공급자를 두지 않는다. 그때 링크는 예외와 스킴만으로 고른다. `address_reasons`를 로봇마다 부르지 않는다. 스캔을 새로 시작하거나 로봇 URL로 요청을 보내지 않는다.

`console_routes.gathered`는 `{**row, "line_stuck": ...}`라서 `link`가 응답 복사에 남는다. 그 함수에 분류를 다시 넣지 않는다. `SharedGather`의 주석(캐시된 스냅샷은 읽기 전용)을 유지한다.

**Step 4: Run test to verify it passes**

Run: `python -m pytest operations/fleet/test/test_link_class.py operations/fleet/test/test_link_on_snapshot.py operations/fleet/test/test_link_address_source.py operations/fleet/test/test_server_console.py -q -p no:cacheprovider`

Expected: PASS.

**Step 5: Commit**

Task 4와 한 커밋이다. 여기서 커밋하지 않는다.

---

### Task 4: Fleet API 문서에 link를 적는다

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md` (머리 `**Version:**`, §10.8의 capabilities 단락 다음, `# 11. 변경 이력`의 첫 데이터 행)
- Modify: `test/test_line_follow_contract_docs.py` (머리 버전 핀)

커밋 순간에 머리 버전을 다시 읽는다. 지금 워크트리 머리는 `v1.118`이다. 그대로면 다음은 `v1.119`다. 동료가 이미 머리를 올렸으면 그 머리의 다음 정수만 쓴다. 번호를 미리 예약하지 않는다.

**Step 1: Write the failing test**

`test/test_line_follow_contract_docs.py`의 버전 단언 옆에 다음을 더하고, 머리 핀의 `v1.118`은 Step 3에서 고른 버전으로 바꾼다. 먼저 이 단언만 추가하면 문서에 `link`가 없어 실패한다.

```python
def test_fleet_state_robot_row_documents_link():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")
    assert "D-499" in reference
    for word in ("up", "unreachable", "moved", "tls-refused", "protocol"):
        assert word in reference
    assert "GET /api/fleet/state" in reference
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_line_follow_contract_docs.py -q -p no:cacheprovider`

Expected: FAIL, `D-499`가 그 파일에 없다.

**Step 3: Write minimal implementation**

§10.8에서 capabilities 단락 다음에 이 단락을 넣는다.

```markdown
Fleet `GET /api/fleet/state` robot rows also expose optional `link` (D-499):
`up`, `unreachable`, `moved`, `tls-refused`, or `protocol`. Absent on a robot
API error other than HTTP 401. `up` is a successful gather and carries no
console tag. The field is display-only. CORE paths, envelope 1.0, and the
dispatch loop's online/state/goal read are unchanged. An older Fleet omits the field.
```

변경 이력 표의 첫 데이터 행 위에, 고른 버전으로:

```markdown
| v1.119 | 2026-10-07 | Additive (D-499): Fleet `GET /api/fleet/state` 로봇 행 선택 필드 `link`(`up`·`unreachable`·`moved`·`tls-refused`·`protocol`). 401이 아닌 로봇 API 오류에는 필드가 없다. 표시 전용. CORE 경로·envelope 1.0·발행 루프의 online/state/goal 판정은 그대로다 |
```

머리가 `v1.118`이 아니면 `v1.119` 대신 그 다음 번호를 표와 `**Version:**` 줄과 `test_line_follow_contract_docs.py`의 `v1.118` 핀에 같이 적는다. 셋은 한 커밋이다.

**Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_line_follow_contract_docs.py operations/fleet/test/test_link_class.py operations/fleet/test/test_link_on_snapshot.py operations/fleet/test/test_link_address_source.py -q -p no:cacheprovider`

Expected: PASS.

문서 모듈 기록은 이 커밋에 넣지 않는다. `docs/logs.md`는 구현 커밋마다 한 줄을 끝에 붙이고(CRLF, BOM 없음), `python tools/harness/rosy_harness.py generate`로 `docs/index.md`만 갱신한다. 동료 행이 같은 파일에 있으면 자신의 행만 `git apply --cached --unidiff-zero`로 올린다.

**Step 5: Commit**

```bash
git add operations/fleet/fleet/server/console.py operations/fleet/fleet/server/app.py ^
  operations/fleet/test/test_link_on_snapshot.py operations/fleet/test/test_link_address_source.py ^
  docs/reference/ROSY API & Protocol Reference.md test/test_line_follow_contract_docs.py ^
  docs/logs.md docs/index.md
git diff --cached --name-only
git commit -m "feat: report the robot link on fleet state"
```

PowerShell에서는 `^` 대신 한 줄에 경로를 나열한다.

---

### Task 5: 사이트 경로 문장

**Files:**
- Create: `operations/fleet/fleet/server/web/site-path.js`
- Test: `operations/fleet/test/web/site-path.test.mjs`

**Step 1: Write the failing test**

`operations/fleet/test/web/site-path.test.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";

import { fleetRow, proxyRow, visionRow } from "../../fleet/server/web/site-path.js";

test("before any sample the three rows are still checking", () => {
  for (const row of [proxyRow(null), fleetRow(null), visionRow(null)]) {
    assert.equal(row.word, "확인 중");
  }
});

test("proxy is up only for healthz 200 and the exact ok body", () => {
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ok" } }).word, "정상");
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ok", extra: 1 } }).word, "끊김");
  assert.equal(proxyRow({ finished: true, status: 200, body: { status: "ready" } }).word, "끊김");
  assert.equal(proxyRow({ finished: false }).word, "끊김");
});

test("fleet is up when the state request finishes, including 401", () => {
  assert.equal(fleetRow({ finished: true, status: 200 }).word, "정상");
  assert.equal(fleetRow({ finished: true, status: 401 }).word, "정상");
  assert.equal(fleetRow({ finished: true, status: 500 }).word, "정상");
  assert.equal(fleetRow({ finished: false }).word, "끊김");
});

test("vision names an empty list and a dropped connection apart from a finished 503", () => {
  assert.deepEqual(visionRow({ finished: true, status: 200, names: ["ceiling_north"] }),
    { name: "Vision", word: "ceiling_north", kind: "good" });
  assert.equal(visionRow({ finished: true, status: 200, names: [] }).word, "없음");
  assert.equal(visionRow({ finished: false }).word, "끊김");
  const disabled = visionRow({ finished: true, status: 503, names: [] });
  assert.equal(disabled.word, "응답 503");
  assert.notEqual(disabled.word, "끊김");
});
```

**Step 2: Run test to verify it fails**

Run: `node --test operations/fleet/test/web/site-path.test.mjs`

Expected: FAIL, 모듈이 없다.

**Step 3: Write minimal implementation**

`operations/fleet/fleet/server/web/site-path.js`:

```javascript
// D-499 site path words. The page passes results of calls it already makes.

function pending(name) {
  return { name, word: "확인 중", kind: "neutral" };
}

export function proxyRow(sample) {
  if (!sample) return pending("프록시");
  const body = sample.body;
  const exact = sample.finished === true && sample.status === 200
    && body !== null && typeof body === "object" && !Array.isArray(body)
    && Object.keys(body).length === 1 && body.status === "ok";
  return exact ? { name: "프록시", word: "정상", kind: "good" }
    : { name: "프록시", word: "끊김", kind: "crit" };
}

export function fleetRow(sample) {
  if (!sample) return pending("Fleet");
  if (sample.finished === true && typeof sample.status === "number") {
    return { name: "Fleet", word: "정상", kind: "good" };
  }
  return { name: "Fleet", word: "끊김", kind: "crit" };
}

export function visionRow(sample) {
  if (!sample) return pending("Vision");
  if (sample.finished !== true) return { name: "Vision", word: "끊김", kind: "crit" };
  if (sample.status === 200 && Array.isArray(sample.names) && sample.names.length) {
    return { name: "Vision", word: sample.names.join(", "), kind: "good" };
  }
  if (sample.status === 200) return { name: "Vision", word: "없음", kind: "warn" };
  return { name: "Vision", word: `응답 ${sample.status}`, kind: "warn" };
}
```

**Step 4: Run test to verify it passes**

Run: `node --test operations/fleet/test/web/site-path.test.mjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add operations/fleet/fleet/server/web/site-path.js operations/fleet/test/web/site-path.test.mjs
git diff --cached --name-only
git commit -m "test: pin the console site path words"
```

---

### Task 6: 로봇 링크 태그 문장

**Files:**
- Create: `operations/fleet/fleet/server/web/link-tag.js`
- Test: `operations/fleet/test/web/link-tag.test.mjs`

**Step 1: Write the failing test**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { linkTag } from "../../fleet/server/web/link-tag.js";

test("only a problem link produces a tag", () => {
  assert.equal(linkTag("up"), null);
  assert.equal(linkTag(undefined), null);
  assert.equal(linkTag("other"), null);
  assert.equal(linkTag("unreachable").word, "닿지 않음");
  assert.equal(linkTag("moved").word, "주소 이동");
  assert.equal(linkTag("moved").next, null);
  assert.equal(linkTag("tls-refused").word, "인증 거부");
  assert.equal(linkTag("tls-refused").focus, "console-token");
  assert.equal(linkTag("protocol").word, "프로토콜");
  assert.match(linkTag("protocol").text, /등록된 base URL/);
  assert.equal(linkTag("protocol").focus, null);
});

test("new link files do not name transport exceptions", () => {
  const web = new URL("../../fleet/server/web/", import.meta.url);
  for (const name of ["link-tag.js", "site-path.js"]) {
    const text = readFileSync(new URL(name, web), "utf8");
    for (const banned of ["RemoteProtocolError", "ConnectError", "RobotApiError", "SSLError"]) {
      assert.equal(text.includes(banned), false, `${name} names ${banned}`);
    }
  }
});
```

**Step 2: Run test to verify it fails**

Run: `node --test operations/fleet/test/web/link-tag.test.mjs`

Expected: FAIL, `link-tag.js`가 없다. `REACH_LABEL`을 지워서 이 시험을 통과시키지 않는다.

**Step 3: Write minimal implementation**

`operations/fleet/fleet/server/web/link-tag.js`:

```javascript
// D-499. The caller passes the server `link` word. Unknown words render nothing.

const TAGS = {
  unreachable: { word: "닿지 않음", kind: "crit", text: null, next: "다음: 주소 확인", focus: null },
  moved: { word: "주소 이동", kind: "warn", text: null, next: null, focus: null },
  "tls-refused": {
    word: "인증 거부", kind: "warn",
    text: "포트는 응답하고 토큰이 거절됐습니다. 망 수리가 아닙니다.",
    next: "다음: 관제 토큰", focus: "console-token",
  },
  protocol: {
    word: "프로토콜", kind: "warn",
    text: "등록된 base URL의 스킴으로 로봇 HTTP가 끝나지 않습니다.",
    next: "다음: 등록된 Fleet base URL", focus: null,
  },
};

export function linkTag(link) {
  return Object.prototype.hasOwnProperty.call(TAGS, link) ? TAGS[link] : null;
}
```

**Step 4: Run test to verify it passes**

Run: `node --test operations/fleet/test/web/link-tag.test.mjs operations/fleet/test/web/site-path.test.mjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add operations/fleet/fleet/server/web/link-tag.js operations/fleet/test/web/link-tag.test.mjs
git diff --cached --name-only
git commit -m "test: pin the console robot link tag"
```

---

### Task 7: 관제 화면에 붙인다

**Files:**
- Modify: `operations/fleet/fleet/server/web/index.html` (약 169–173행, `#address-drift`와 `#roster` 사이)
- Modify: `operations/fleet/fleet/server/web/styles.css` (`.roster-block > #roster` 규칙, 약 40행)
- Modify: `operations/fleet/fleet/server/web/roster.js` (`card`, 약 136–224행)
- Modify: `operations/fleet/fleet/server/web/console.js` (`refreshState` 약 330행, `pageScope.interval(refreshState` 약 865행)
- Modify: `operations/fleet/fleet/server/web/vision-view.js` (`createVisionView` 인자, `refreshSources` 약 282–314행)
- Test: `operations/fleet/test/web/site-path-place.test.mjs`

**Step 1: Write the failing test**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../../fleet/server/web/", import.meta.url);
const html = readFileSync(new URL("index.html", root), "utf8");
const roster = readFileSync(new URL("roster.js", root), "utf8");
const consoleJs = readFileSync(new URL("console.js", root), "utf8");
const vision = readFileSync(new URL("vision-view.js", root), "utf8");

test("the site path block sits in the roster panel above the robot list", () => {
  const panel = html.slice(html.indexOf('aria-labelledby="roster-heading"'), html.indexOf('aria-labelledby="vision-heading"'));
  const pathAt = panel.indexOf('id="site-path"');
  const listAt = panel.indexOf('id="roster"');
  assert.ok(pathAt > 0 && pathAt < listAt);
  assert.equal(html.includes("/api/v1/host/network"), false);
});

test("the page reads link and the calls it already makes", () => {
  assert.match(roster, /linkTag/);
  assert.match(consoleJs, /\/healthz/);
  assert.match(consoleJs, /proxyRow|site-path/);
  assert.match(vision, /onSources/);
  assert.equal(consoleJs.split("/api/fleet/vision/sources").length, 1);
});
```

`console.js`가 vision sources를 직접 부르지 않으므로 `split` 길이는 1이다. vision-view.js만 그 경로를 가진다. 시험을 그 파일에 대해 단언하지 말고, 콘솔 파일에 두 번째 폴링을 넣지 않는 것으로 고정한다.

**Step 2: Run test to verify it fails**

Run: `node --test operations/fleet/test/web/site-path-place.test.mjs`

Expected: FAIL, `#site-path`가 없다.

**Step 3: Write minimal implementation**

`index.html`의 `#address-drift` 블록 다음, `#roster` 앞에:

```html
<section id="site-path" class="site-path" aria-labelledby="site-path-heading">
  <h3 id="site-path-heading">관제 경로</h3>
  <ul id="site-path-list"></ul>
</section>
```

`styles.css`의 `.roster-block > #roster, .roster-block > .address-drift` 선택자에 `, .roster-block > #site-path`를 더한다. `#site-path` 여백은 `.address-drift`와 같은 `gap`과 `margin`만 준다. 새 색과 새 글꼴은 만들지 않는다. 상태 색은 기존 `ui-tag`의 `good` / `warn` / `crit` / `neutral`만 쓴다.

`roster.js`는 `linkTag`를 `./link-tag.js`에서 가져온다. `card`에서 모드 태그 다음에:

```javascript
const link = view.stateUnavailable ? null : linkTag(robot.link);
if (link) {
  const linkNode = tag(link.word, link.kind);
  linkNode.dataset.link = robot.link;
  head.appendChild(linkNode);
}
```

`robot.error`로 `로봇이 거절` / `닿지 않음` 단락을 만드는 조건에 `&& !link`를 더한다. `addressReason` 단락은 조건 그대로 둔다. `link.text`가 있으면 hint 한 줄을 더한다. `link.next`가 있으면, `link.focus`가 `console-token`일 때만 `button`(type button)을 만들어 `#console-token`에 `focus()`를 호출한다. `focus`가 없으면 버튼 없는 텍스트다. 스킴을 고치는 컨트롤은 만들지 않는다.

`console.js`는 `proxyRow`, `fleetRow`, `visionRow`를 `./site-path.js`에서 가져온다. 모듈 스코프에 `let pathSample = { proxy: null, fleet: null, vision: null };`를 둔다.

```javascript
function paintSitePath() {
  const list = el("site-path-list");
  list.replaceChildren(...[pathSample.proxy, pathSample.fleet, pathSample.vision].map((sample, index) => {
    const row = [proxyRow, fleetRow, visionRow][index](sample);
    const item = document.createElement("li");
    const name = document.createElement("b");
    name.textContent = row.name;
    const word = tag(row.word, row.kind);
    item.append(name, word);
    return item;
  }));
}
```

`tag`가 `console.js`에 없으면 `roster.js`가 쓰는 같은 헬퍼를 여기서 새로 복제하지 말고, 기존 콘솔 태그 헬퍼를 그대로 부른다. 없는 경우에만 `document.createElement("ui-tag")`와 `setAttribute("status", row.kind)`, `textContent = row.word`로 그 한 줄을 만든다.

`refreshState`의 `call("/api/fleet/state")`가 반환되면 `pathSample.fleet = { finished: true, status: 200 }`이다. `catch`에서 `err.name === "AbortError"`이면 경로 표본을 바꾸지 않는다. `typeof err.status === "number"`이면 `pathSample.fleet = { finished: true, status: err.status }`다. 401의 `markLocked`는 지금 자리에 둔다. 상태 번호가 없으면 `pathSample.fleet = { finished: false }`다. 그 다음에 `paintSitePath()`를 부른다.

`refreshHealthz`는 `call`을 쓰지 않는다. `fleet-client`가 401과 비정상을 던져서 본문 비교가 불가능하다.

```javascript
async function refreshHealthz() {
  const life = pageScope.capture();
  try {
    const response = await fetch("/healthz", { cache: "no-store", signal: life.signal });
    const body = await response.json();
    if (!life.current()) return;
    pathSample.proxy = { finished: true, status: response.status, body };
  } catch (err) {
    if (err.name === "AbortError") return;
    pathSample.proxy = { finished: false };
  }
  paintSitePath();
}
```

`pageScope.interval(refreshState, STATE_MS)` 옆에 `pageScope.interval(refreshHealthz, STATE_MS)`를 둔다. `refreshState` 안에서 healthz를 다시 부르지 않는다.

`createVisionView` 인자에 `onSources = () => {}`를 더한다. `refreshSources`가 `result`를 받은 직후 `onSources({ finished: true, status: 200, names: result.sources })`를 부른다. `catch`에서 AbortError는 반환하고, `typeof error.status === "number"`이면 `onSources({ finished: true, status: error.status, names: [] })`, 아니면 `onSources({ finished: false })`다. 콘솔의 `createVisionView({...})`에 `onSources: (sample) => { pathSample.vision = sample; paintSitePath(); }`를 넘긴다. sources 요청을 하나 더 만들지 않는다.

**Step 4: Run test to verify it passes**

Run: `node --test operations/fleet/test/web/site-path.test.mjs operations/fleet/test/web/link-tag.test.mjs operations/fleet/test/web/site-path-place.test.mjs operations/fleet/test/web/address-drift.test.mjs`

Expected: PASS. 주소 이동 문장 시험이 그대로 통과한다.

브라우저로 `/console`을 연다. 토큰이 없으면 Fleet 줄은 `정상`이고 기존 토큰 안내가 남는다. healthz를 막지 않은 상태에서 프록시 줄은 `정상`이다. 로봇 행에 `link: "protocol"`을 준 픽스처가 없으면 장치에서 그 태그를 확인했다고 적지 않는다. 호스트에서는 `link-tag` 시험이 문장을 고정한다.

**Step 5: Commit**

```bash
git add operations/fleet/fleet/server/web/index.html operations/fleet/fleet/server/web/styles.css ^
  operations/fleet/fleet/server/web/roster.js operations/fleet/fleet/server/web/console.js ^
  operations/fleet/fleet/server/web/vision-view.js ^
  operations/fleet/test/web/site-path-place.test.mjs
git diff --cached --name-only
git commit -m "feat: show the site path and robot link on the console"
```

화면 커밋에도 `docs/logs.md` 한 줄과 `docs/index.md` 재생성을 포함한다. D-499 Status 줄은 고치지 않는다.

---

### Task 8: 호스트 시험과 알려진 실패

**Files:**
- Modify: `docs/logs.md` (끝에 한 기록, 아직 없다면)
- Modify: `docs/index.md` (`python tools/harness/rosy_harness.py generate`의 출력만)

**Step 1: Run the focused suites**

작업 디렉터리는 이 워크트리다.

```bash
python -m pytest operations/fleet/test/test_link_class.py operations/fleet/test/test_link_on_snapshot.py operations/fleet/test/test_link_address_source.py operations/fleet/test/test_server_console.py operations/fleet/test/test_address_drift.py test/test_line_follow_contract_docs.py test/test_harness_contracts.py -q -rfE -p no:cacheprovider > X:/DevTemp/site-link-monitor/run.txt
node --test operations/fleet/test/web/site-path.test.mjs operations/fleet/test/web/link-tag.test.mjs operations/fleet/test/web/site-path-place.test.mjs operations/fleet/test/web/address-drift.test.mjs
python test/known_failures.py X:/DevTemp/site-link-monitor/run.txt
python tools/harness/rosy_harness.py lint
```

Expected: pytest PASS, node PASS, `known_failures.py`가 `NEW` 없음, lint 오류 0. 기존 warning은 모듈 `last_verified` 밀림이면 이 변경의 실패가 아니다. `NEW`가 있으면 그 브랜치에서 고치고 이 단계를 다시 한다. `test/known_failures.txt`에 이 브랜치의 실패를 넣지 않는다.

**Step 2: Do not claim device acceptance**

호스트 시험은 장치, ARM64 이미지, 현장 수용을 대신하지 않는다. D-499는 Proposed로 남긴다. `main`에 fast-forward하지 않고 푸시하지 않는다.

---

## 범위 밖

- 패킷 목록, 요청 폭포, 컨테이너 CPU·메모리·바이트, 공유기 관리.
- 등록된 base URL의 스킴을 자동으로 바꾸는 일.
- `/healthz` 본문을 세 서비스 상태로 늘리는 일.
- 로봇 Wi-Fi 카드, 콘솔의 `nmcli`, 목표·비상정지·텔레옵 변경.
- 여섯 번째 `link` 단어. 모르는 값은 태그를 그리지 않는다.
- D-499를 Accepted로 바꾸는 일. 착지와 푸시.
