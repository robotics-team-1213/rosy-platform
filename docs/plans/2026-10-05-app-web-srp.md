# 앱·웹 SRP 경계 고정 계획

> 실행 전 필독: 검토 문서 `docs/assessments/2026-10-05-app-web-role-review.md`의 「SRP로 나누는 방법」. 이 계획은 그 제안의 구현이다. 새 앱을 만들지 않는다.

**Goal:** Console 세 문서와 Robot 세 문서가 서로의 조작 모듈을 import하지 못하도록 시험으로 고정한다.

**Architecture:** 문서 분리는 이미 있다. `/console`은 `console.js`, `/console/install`은 `install.js`, `/console/cell`은 `cell.js`다. Robot은 `panels.yaml`이 패널을 `console`·`setup`·`device`에 끼운다. 남은 일은 화면을 다시 짜는 것이 아니라, 그 경계를 넘는 import가 조용히 돌아오지 않게 하는 것이다. `vision-view.js`는 운용과 설치가 함께 쓴다. 운용 쪽은 프리뷰 필드가 없으면 보정을 쓰지 않는다. 이 계획에서 그 파일을 둘로 나누지 않는다.

**Tech Stack:** 기존 정적 ES 모듈, pytest, `panels.yaml`. 번들러·새 서버·새 포트 없음.

**기준 트리:** 검토 스냅샷은 로컬 main `cf7d4f5b62c2228b2163429154a33431a907098c`다. 시험은 `feat/app-web-srp-fence`에서 main `cb6c42f46` 위로 고정한다.

---

## 하지 않는 일

- Rosy Install, Rosy Cell, 바닥 확인 앱, 두 번째 운전 앱을 만들지 않는다.
- `operations/fleet/fleet/server/web`을 `operations/ui/console`로 옮기지 않는다.
- Robot `console.teleop`을 지우지 않는다. Pilot DEVICE 수용 뒤의 링크 전환은 별도 작업이다.
- Cam, Pilot 셸, Face, 게임 보드, 진단 페이지, Pinky 학습 검수를 수정하지 않는다.
- `shared/web`에 관제·로봇 조작 규칙을 넣지 않는다.
- 화면 마크업을 이 계획으로 재배치하지 않는다. 현재 D-410 분리가 시험으로 이미 고정돼 있다 (`test_console_camera_pairing.py`, `test_site_lanes_api.py`, `test_site_map_api.py`).

## 현재 코드에서 확인한 것

- `console.js`는 `enrollment.js`, `camera-pairing.js`, `map-fit-view.js`, `cell.js`를 import하지 않는다. D-410 주석이 12행과 720행에 있다.
- `install.js`가 등록·페어링·맵 맞춤·경기장 뷰를 import한다.
- `cell.js`는 `fleet-client.js`와 `cell-document-editor.js`만 import한다.
- `console.js`와 `install.js`가 `vision-view.js`를 같이 import한다. `vision-view.js`의 Fleet 호출은 `/api/fleet/vision/sources`와 `/api/fleet/vision/lease`뿐이다. `writeProfile`은 보정 입력 칸이 있을 때만 칸에 값을 채운다.
- Robot 역할 표면은 `test/test_role_menu_migration.py`가 패널별로 일부 고정한다. 폴더와 surface가 어긋난 새 패널을 막는 시험은 `test_panel_module_folder_matches_surface`다.

---

### Task 1: Console 문서별 import 펜스

**Files:**
- Create: `operations/fleet/test/test_document_imports.py`
- Modify: 없음. 이 시험이 실패하면 Task 2로 간다.
- Test: `operations/fleet/test/test_document_imports.py`

`operations/fleet/fleet/server/web`의 엔트리 셋이 정적 import만 본다. 동적 `import()`가 있으면 실패한다.

허용은 엔트리별로 닫힌 목록이다.

- `console.js`: `formation.js`, `map-view.js`, `roster.js`, `line-stuck.js`, `signals.js`, `tracking-view.js`, `start-point-view.js`, `vision-view.js`, `authorization.js`, `address-drift.js`, `poll-gate.js`, `confirmed-action.js`, `/common/fleet-client.js`, `/common/ui.js`, `/common/scope.js`
- `install.js`: `authorization.js`, `enrollment.js`, `camera-pairing.js`, `camera-peer.js`, `vision-view.js`, `field-view.js`, `map-fit-view.js`, `poll-gate.js`, `peer-picker.js`, `address-drift.js`, `/common/fleet-client.js`, `/common/scope.js`, `/common/task-chooser.js`, `/common/ui.js`
- `cell.js`: `/common/fleet-client.js`, `/console/assets/cell-document-editor.js`

상대 `./이름.js`와 절대 `/common/…`, `/console/assets/…`를 같은 비교 키로 맞춘다. 목록에 없는 import가 있으면 그 스펙을 assertion 메시지에 넣는다.

확인 명령:

```bash
python -m pytest operations/fleet/test/test_document_imports.py -q
```

펜스 확인: `console.js`에 `import { createEnrollmentPanel } from "./enrollment.js";`를 임시로 넣으면 FAIL (`console.js imports outside its document: ['enrollment.js']`)이다. 그 줄은 되돌리고 커밋하지 않는다. 되돌린 뒤 PASS다.

### Task 2: 펜스가 실패할 때만 모듈을 옮긴다

Task 1이 현재 트리에서 PASS면 이 Task의 코드 변경은 없다. 나중에 실패하면, 실패 메시지에 나온 엔트리에서 그 import와 호출만 빼고 그 모듈이 속한 문서의 엔트리에 둔다. `install.js`가 `map-view.js`나 `formation.js`를 가져가게 하지 않는다.

### Task 3: Robot 패널은 자기 표면 폴더에만 둔다

**Files:**
- Modify: `test/test_role_menu_migration.py`
- Test: `test_panel_module_folder_matches_surface`

`panels/console/`은 `surface: console`, `panels/setup/`은 `setup`, `panels/host/`와 `panels/system/`은 `device`다. `console.teleop`은 `panels/console/teleop.js`와 `surface: console`인 채로 남는다. 이 시험은 그 패널을 삭제하지 않는다.

```bash
python -m pytest test/test_role_menu_migration.py::test_panel_module_folder_matches_surface -q
```

## 완료 기준

- `test_document_imports.py`가 현재 엔트리 import와 맞고, `console.js`에 `enrollment.js` import를 넣으면 실패했다가 되돌리면 통과한다.
- `test_panel_module_folder_matches_surface`가 통과하고 `console.teleop`은 운용 표면에 남아 있다.
- 제품 앱 수, 포트, `surfaces.yaml`의 `owns`, Pilot·Cam·Face는 그대로다.
- 호스트 pytest 통과는 장치 수용이 아니다. 이 계획은 브라우저 재배치나 현장 확인을 포함하지 않는다.

## 실행 기록

2026-10-05. 목표는 달성했다. `test_document_imports.py`와 `test_panel_module_folder_matches_surface`가 main `cb6c42f46` 위의 `feat/app-web-srp-fence`에서 통과했다. `console.js`에 `enrollment.js` import를 넣으면 펜스가 `['enrollment.js']`로 실패하고, 되돌리면 통과한다. Task 2의 제품 코드 이동은 없다. `console.teleop`은 운용 표면에 남아 있다. 새 앱은 없다.
