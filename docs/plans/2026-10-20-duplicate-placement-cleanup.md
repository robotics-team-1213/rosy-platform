# 중복·위치 불일치 정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-10-20 조사에서 나온 중복·위치 불일치 중 동작이 갈라진 것부터 고치고, 같은 코드 사본을 한 곳으로 모으고, 문서와 실제 위치를 맞춘다.

**Architecture:** 묶음 0(문서·빈 파일) → 묶음 1(갈라진 사본, 버그 위험) → 묶음 2(같은 사본 합치기) → 묶음 3(파일 이동) 순서로 한다. 묶음 4는 코드 작업이 아니라 ADR 결정이 필요한 목록이다. Task 하나가 PR 하나다. 저장 형식(해시, 설정 파일)은 바꾸지 않는다.

**Tech Stack:** Python 3.12, ROS 2 Jazzy(rclpy), pytest, 바닐라 JS(Console), bash.

**Spec:** 이 문서의 「조사 근거」 절. 영역별 조사 4건(middleware, operations, learning·contracts·shared·test, tools·deploy·integrations)의 결과를 요약했다.

## Global Constraints

- 시험은 노트북에서 돌리지 않는다(D-584). `python tools/remote/remote_pytest.py --sha <커밋> -- <경로>` → `python test/known_failures.py <run.txt>`에서 `NEW`가 0이어야 한다.
- 작업은 `.worktrees/<주제>`에서 한다. 착지는 사용자가 말한 뒤 `python tools/land.py --tests auto`로 한다(git-workflow.md).
- `concern: safety` 경로(`tools/harness/platform_parts.yaml`)를 건드리는 커밋에는 `Safety-Review: <리뷰어> <근거>` trailer를 단다. 해당 경로는 `middleware/drive/motion_limits`, `core_features.safety*`, `control.safety`, 그리고 파일 단위 태그가 붙은 파일이다(같은 파일 859행 이후 목록).
- 파일을 옮기기 전에 [held-branches.md](../reference/held-branches.md)와 `git worktree list`를 보고, 같은 파일을 고치는 살아 있는 브랜치가 있으면 그 Task를 미룬다.
- 이미 디스크에 저장된 해시·서명·설정 파일이 읽히는 결과는 바뀌면 안 된다.
- docs/validation 아래 기록은 고정이다. 내용을 고치지 않는다(docs/validation/AGENTS.md:41).

## Review Focus

1. 바이트가 같지 않은 해시 사본을 하나로 합치는 경우: 이미 저장된 digest가 맞지 않게 된다. Task 6의 golden 시험이 이것을 막는다.
2. 원점 yaw가 0이 아닌 지도: 지금 지도는 모두 yaw가 0이라 Fleet과 CORE의 차이가 드러나지 않았다. Task 1이 yaw가 π/2인 경우를 시험으로 고정한다.
3. `identity:` 키가 있는 카메라 설정 파일: Vision이 거절한다. Task 2가 시험으로 고정한다.
4. 오류 응답 본문이 JSON이 아닌 Fleet 응답(프록시 502 HTML 등): Vision publish가 맨 `ValueError`로 죽는다. Task 3이 시험으로 고정한다.
5. 파일을 옮긴 뒤 설치된 entry point와 `control.*` import 경로: Task 11과 Task 12는 옮긴 뒤 colcon 설치 결과에서 import가 되는지 확인한다.

---

## 묶음 0 — 문서와 빈 파일

### Task 0: 문서 경로 바로잡기와 빈 파일 정리

**Files:**
- Modify: `AGENTS.md:13`. `vision/perception`→`front_camera/perception`, `middleware/drive/{...,safety}`→`{...,motion_limits}`, `middleware/perception/control/safety_node.py`→`middleware/drive/runtime/safety_node.py`로 바꾼다.
- Modify: `docs/reference/core-drive-responsibilities.md` 28, 31, 47, 51행. `drive/safety/adapter`→`drive/motion_limits/adapter`, `vision/perception`→`front_camera/perception`으로 바꾼다.
- Modify: `docs/reference/platform-folder-responsibilities.md:277`. 소유자를 `server/channel_requests.py`가 아니라 `server/channel/` 아래 실제 파일로 적는다.
- Delete(git 추적 중): `tools/sim/gazebo/pinky_maze.sdf`
- Modify: `tools/perception_prototype/realrun/geom.py:2`. 없는 경로 `src/core/control`을 `middleware/perception`으로 바꾼다.
- 로컬에서만 지울 것(추적 안 함): 저장소 최상위 `test_camera_extrinsic.py`, `test_trip_job_lease.py`, `aff1.log`와 빈 폴더 `middleware/perception/vision/`

- [ ] **Step 1:** `grep -rn "vision/perception\|drive/safety\|perception/control/safety_node" AGENTS.md docs/reference`로 고칠 곳이 위 목록과 같은지 확인한다.
- [ ] **Step 2:** 위 수정을 한다.
- [ ] **Step 3:** `remote_pytest.py -- test/architecture/test_document_placement.py test/architecture/test_folder_layout.py`를 돌려 PASS를 확인한다.
- [ ] **Step 4:** Commit `docs: 실제 폴더 경로로 AGENTS·책임 문서 갱신, 쓰이지 않는 sdf 삭제`

---

## 묶음 1 — 갈라진 사본 (버그 위험)

### Task 1: CORE 격자 좌표가 원점 yaw를 따르게

**Files:**
- Modify: `middleware/core/services/core_features/maps.py`. `GridFrame.world_to_cell`(70행 부근)을 고치고, 19행 docstring에서 "sampling is axis-aligned"를 지운다.
- Test: `middleware/core/test/` 아래 maps 시험 파일. 없으면 `test_core_features_maps.py`를 만든다.

**Interfaces:**
- Produces: `GridFrame.world_to_cell(x: float, y: float) -> Optional[tuple[int, int]]`. 시그니처는 그대로이고, 계산은 Fleet `rightofway/bays.py:121 Grid.cell_of`와 같은 회전을 쓴다.

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
def test_world_to_cell_rotates_by_origin_yaw():
    grid = GridFrame(width=3, height=3, resolution=1.0, origin_x=0.0, origin_y=0.0,
                     origin_yaw=math.pi / 2, data=(0,) * 9)
    assert grid.world_to_cell(-0.5, 1.5) == (1, 0)

def test_world_to_cell_zero_yaw_unchanged():
    grid = GridFrame(width=3, height=3, resolution=1.0, origin_x=-1.0, origin_y=-1.0, data=(0,) * 9)
    assert grid.world_to_cell(0.5, -0.5) == (1, 0)
```

- [ ] **Step 2:** 시험 PC에서 돌려 첫 시험이 FAIL(`None` 또는 다른 칸)인지 확인한다.
- [ ] **Step 3:** `dx, dy`를 `-origin_yaw`만큼 회전한 뒤 `floor(/resolution)`을 하도록 고친다. 범위 검사는 지금 코드를 그대로 둔다.
- [ ] **Step 4:** `remote_pytest.py -- middleware/core/test`를 돌려 PASS를 확인한다.
- [ ] **Step 5:** Commit `fix(core): GridFrame 좌표 변환이 원점 yaw를 따르게 (Fleet Grid와 일치)`

### Task 2: 카메라 소스 설정 검사를 하나로

**Files:**
- Create: `contracts/foundation/core_common/protocol/sighting_sources.py`
- Modify: `operations/fleet/fleet/server/recognition/sightings_config.py:34` (`load_sighting_sources`)
- Modify: `operations/overhead/rosy_vision/vision_config.py:43` (`load_vision_sources`)
- Test: `contracts/foundation/test/test_sighting_sources.py`, `operations/overhead/test/test_vision_config.py`(있는 파일에 추가)

**Interfaces:**
- Produces:
  - `validate_sighting_config(config: object) -> None`. 문제가 있으면 `ValueError`를 낸다.
  - 모듈 상수 `REQUIRED`, `ALLOWED`, `CREDENTIAL_KINDS`, `CALIBRATION_SOURCES`
  - 검사 규칙은 두 사본의 합집합이다. 최상위 키는 `sources`(필수)와 `identity`(선택)만 허용한다. `corner_world_m`은 유한하고 서로 달라야 한다(Fleet 규칙). 나머지 행별 검사는 두 사본에 공통인 것을 쓴다.
- 두 로더는 먼저 `validate_sighting_config`를 부르고, 각자 dataclass를 만드는 코드는 그대로 둔다. Vision은 `identity`를 읽지 않고 무시한다.

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
def test_vision_accepts_identity_key(tmp_path):
    path = tmp_path / "s.yaml"; path.write_text(VALID_YAML + "identity: {}\n")
    assert load_vision_sources(path)

def test_vision_rejects_nonfinite_corner(tmp_path):
    path = tmp_path / "s.yaml"; path.write_text(VALID_YAML.replace("0.0, 0.0", ".nan, 0.0", 1))
    with pytest.raises(ValueError):
        load_vision_sources(path)
```

  `VALID_YAML`은 `operations/overhead/test`에 이미 있는 예제 설정을 쓴다(`test_site_cameras_example.py` 참고).
- [ ] **Step 2:** 시험 PC에서 둘 다 FAIL인지 확인한다.
- [ ] **Step 3:** 공용 검사를 contracts에 만들고, 두 로더에서 각자 하던 중복 검사 줄을 지운다.
- [ ] **Step 4:** `remote_pytest.py -- contracts/foundation operations/overhead/test operations/fleet/test -k "sighting or vision_config or site_cameras"`를 돌려 PASS를 확인한다.
- [ ] **Step 5:** Commit `fix: Fleet·Vision 카메라 소스 설정 검사를 contracts 하나로 (identity 키, corner 유한성)`

### Task 3: Vision publish 오류 처리를 TrackClient와 같게

**Files:**
- Modify: `operations/overhead/rosy_vision/publish.py:21-70` (`SightingPublisher`)
- Test: `operations/overhead/test/test_publish.py`. 있으면 거기에 추가하고, 없으면 새로 만든다.

**Interfaces:**
- Consumes: `rosy_vision/track/fleet_client.py`의 `TrackClient`와 `_body`(오류 응답 해석)
- Produces: `SightingPublisher`의 공개 메서드는 바꾸지 않는다. HTTP 요청, 토큰 헤더, 오류 해석은 `TrackClient`가 맡도록 위임하거나 `_body`를 공용 함수로 꺼내 쓴다. 둘 중 diff가 작은 쪽을 고른다.

- [ ] **Step 1: 실패하는 시험 쓰기.** `httpx.MockTransport`로 `502`, `text/html` 본문을 돌려주게 하고, `publish(...)`가 `fleet_client`가 같은 경우에 내는 오류 타입을 내는지(`ValueError`가 아닌지) 확인한다.
- [ ] **Step 2:** 시험 PC에서 FAIL(`ValueError`)인지 확인한다.
- [ ] **Step 3:** 위임하도록 고친다.
- [ ] **Step 4:** `remote_pytest.py -- operations/overhead/test`를 돌려 PASS를 확인한다.
- [ ] **Step 5:** Commit `fix(vision): publish가 JSON 아닌 오류 응답에서 죽지 않게 TrackClient 재사용`

### Task 4: Fleet Discord 전송을 integrations 어댑터로

**Files:**
- Modify: `operations/fleet/fleet/server/channel/health/discord.py:13` (`BareDiscordPublisher`)
- Test: `operations/fleet/test/` 아래 health discord 시험

**Interfaces:**
- Consumes: `integrations/messaging/discord/rosy_discord/replies.py:15`의 전송 함수와 snowflake 검증
- 먼저 `tools/harness/platform_parts.yaml`에서 `operations/fleet`의 `allow`에 integrations가 있는지 본다.
  - **있으면:** `BareDiscordPublisher.publish`가 그 함수를 부르게 한다.
  - **없으면:** import하지 말고 snowflake 검증(17~20자리 숫자)만 Fleet 사본에 넣는다. 사본은 묶음 4의 결정 목록에 남긴다.

- [ ] **Step 1: 실패하는 시험 쓰기.** `channel_id="abc"`일 때 `publish`가 네트워크를 타기 전에 `ValueError`를 내는지 확인한다.
- [ ] **Step 2:** FAIL을 확인한다.
- [ ] **Step 3:** 위 분기 중 하나로 구현한다.
- [ ] **Step 4:** `remote_pytest.py -- operations/fleet/test -k discord`를 돌려 PASS를 확인한다.
- [ ] **Step 5:** Commit `fix(fleet): Discord 채널·봇 ID 검증 누락 보완`

### Task 5: TLS 체인 검증 사본을 소유권 시험에 넣기

**Files:**
- Modify: `operations/fleet/fleet/server/peer/camera_peer_tls.py:9`. CORE `tls_anchor.py`의 `cryptography<42` 대체 경로를 같은 방식으로 넣는다.
- Modify: `test/architecture/test_peer_proof_ownership.py:8-9`. 지금 peer_crypto 두 사본만 대조하는데, `tls_anchor.py` ↔ `camera_peer_tls.py`의 검증 함수 본문도 대조하도록 늘린다.

- [ ] **Step 1:** 시험에 TLS 쌍을 추가하고, 시험 PC에서 FAIL(본문 다름)인지 확인한다.
- [ ] **Step 2:** Fleet 사본을 CORE 사본과 맞춘다.
- [ ] **Step 3:** `remote_pytest.py -- test/architecture/test_peer_proof_ownership.py operations/fleet/test -k peer`를 돌려 PASS를 확인한다.
- [ ] **Step 4:** Commit `fix(fleet): camera peer TLS 검증을 CORE와 맞추고 사본 대조 시험에 추가`

### Task 6: 해시 형식 고정 시험 (형식은 바꾸지 않음)

**Files:**
- Test: `test/architecture/test_canonical_hash_formats.py` (Create)
- Modify(같은 바이트를 만드는 사본만): `contracts/learning/.../incident_handoff.py:8`, `prediction.py:52`가 한 함수를 쓰게 한다. ensure_ascii, separators, 크기 제한이 모두 같은 사본만 합친다.

**Interfaces:**
- 조사에서 나온 해시 함수 7곳(`incident_handoff.digest`, `prediction.canonical_sha256`, `artifacts._json`, `registry.py:27`, `fleet_rules.py:29`, `operational_comparison.py:11`, `judgment_acceptance.py:17`, `review_admission._hash`, `review_migration.py:23`)에 대해 시험을 쓴다. 각 함수에 `{"이름": "로봇", "b": [1, 2]}`를 넣었을 때 나오는 hex를 **현재 값 그대로** 기록한다.

- [ ] **Step 1:** 각 함수의 현재 출력을 시험 PC에서 뽑아 golden 값으로 시험에 적는다.
- [ ] **Step 2:** PASS를 확인한다. 현재 동작을 고정하는 시험이다.
- [ ] **Step 3:** 바이트가 같은 사본끼리만 한 함수로 합치고, golden이 그대로인지 확인한다.
- [ ] **Step 4:** 형식이 다른 사본은 합치지 않는다. 각 정의 위에 `# 형식 고정: <저장 위치>가 이 digest를 저장함, test_canonical_hash_formats` 한 줄을 단다. 저장 위치는 grep으로 확인해서 적는다.
- [ ] **Step 5:** Commit `test: 정규 JSON 해시 형식별 golden 고정, 같은 형식 사본 합침`

---

## 묶음 2 — 같은 사본 합치기 (동작 불변)

각 Task는 기존 시험이 모두 통과하는 것으로 검증하고, 새 헬퍼에는 시험을 하나씩 둔다.

### Task 7: 각도 계산 헬퍼를 배포 단위마다 하나로

- **CORE**(`middleware/core/gateway/core/bridge/`): `ros_bridge.py:517`과 `odometry.py:96`이 `translate.py:20`의 함수를 쓰게 한다.
- **control 배포**(`middleware/perception`, `middleware/drive`):
  - quaternion → yaw는 `sensors/sensing/localization.py:29 planar_yaw`를 쓴다.
  - 각도 wrap은 같은 파일 13행 함수를 쓴다.
  - 대상: 조사 목록의 drive·perception 사본 약 15곳. `startup_calibration_node.py`에만 5곳이 있다.
  - 예외: `line_follow/cue/odom_pivot.py:19`는 ±π에서 동작이 다르므로 손대지 않고 주석만 단다.
- **Fleet**: `operations/world/.../map_pose.py:170 _wrap`을 공개 이름 `wrap_angle`로 내보내고(`_wrap`은 남겨 둔다), Fleet 사본 7곳이 그것을 쓰게 한다.
- **시험:** `planar_yaw`와 `wrap_angle`에 ±π, 0, 3π 경계 값을 넣는 시험을 추가한다. `remote_pytest.py -- middleware/perception/test middleware/drive middleware/core/test operations/fleet/test operations/world`
- **Safety:** `drive/motion_limits/adapter/bumper.py`를 건드리므로 Safety-Review trailer가 필요하다. 이 파일만 따로 커밋해도 된다.

### Task 8: learning 해시·hex 검사 헬퍼

- **Create:** `contracts/learning/src/rosy/contracts/learning/digest.py`에 두 함수를 둔다.
  - `is_sha256_hex(value: object) -> bool`
  - `file_sha256(path: Path) -> str`. 1 MiB 블록 스트리밍 방식이다.
- **Modify:** 조사 목록의 hex 검사 약 25곳과 파일 sha256 6곳이 이 함수를 쓰게 한다. 소문자만 허용하는지가 사본마다 다를 수 있으니 바꾸기 전에 각 정규식을 비교한다. 다르면 그 사본은 남긴다.
- **`_in_checkout()` 17곳은 합치지 않는다.** `sys.path`를 잡기 전에 실행되는 부트스트랩이라 import할 수 없다. 먼저 각 파일에서 이 함수가 import보다 앞에서 쓰이는지 확인한다. 아니라면 합친다.
- **시험:** `digest.py` 단위 시험을 추가하고 `remote_pytest.py -- contracts/learning learning test/learning`을 돌린다.

### Task 9: Console fetch 래퍼를 공용 클라이언트로

- **Modify:**
  - `operations/site_ui/console/devices/camera-pairing.js:137`, `devices/enrollment.js:207`, `installation/camera-peer.js:21`이 `fleet-client.js`의 클라이언트를 쓰게 한다.
  - `console.js:153`과 `installation/install.js:100`의 래퍼를 하나로 합친다.
- **유지할 것:** `error.detail`과 `error.code`를 그대로 보여야 한다. 오류 메시지가 같은지 기존 브라우저 회귀 시험으로 확인한다(rosy-remote-tests 스킬의 browser suite).

### Task 10: 작은 사본 정리

PR 하나로 묶는다. 각 항목은 한쪽을 지우고 import로 바꾸는 일이다.

- **Situation 교착 탐지:**
  - `traffic_watch.py:69 _cycle`을 지우고, Fleet `traffic/blocks.py:442 wait_cycle`을 `rosy_situation`으로 옮긴다. Situation은 Fleet을 import할 수 없기 때문이다. 그리고 Fleet이 그것을 import하게 한다.
  - `COMMAND_WORDS`도 같은 방식으로 옮긴다.
- **얼굴 노드:** `middleware/robot_ui/face/emotion/emotion.py`와 `emotion_server.py` 중 launch에서 쓰지 않는 쪽의 entry point와 파일을 지운다. 먼저 `grep -rn "emotion_server\|'emotion'" middleware/robot_ui deploy`로 확인한다.
- **Pinky 속도 기본값(0.20, 0.80):** `bringup.py:77-78`과 `launch/bringup_robot.launch.py:73-74`가 `pinky_pro_adapter.py:26-27` 상수를 쓰게 한다.
- **deploy 반복:**
  - `lock_value()` 6곳을 `deploy/robot/pinky_pro/image/lib/lock.sh` 하나로 모으고 `source "$(dirname "$0")/lib/lock.sh"`로 불러 쓴다.
  - `validate-pinky-from-windows.ps1`은 이미 `verify-from-windows.ps1`을 부르고 있으니, 거기서 `Invoke-BoundedSshProcess`를 dot-source해서 쓴다.
- **`_birds_eye`:** `lane_bev.py:368`과 `paint_localizer.py:256`의 메서드를 모듈 함수 하나로 합친다.
- **시험:** 바뀐 패키지의 시험 경로를 `remote_pytest.py`로 돌린다. 이미지 스크립트는 `bash -n`과 `test/test_*image*` 시험을 돌린다.

---

## 묶음 3 — 파일 이동

시작 전에 held-branches.md와 worktree 목록을 확인한다(Global Constraints).

### Task 11: goal_escape를 drive/runtime으로

- **Move:** `middleware/perception/nodes/goal_escape.py`를 `middleware/drive/runtime/goal_escape.py`로 옮긴다.
- **Modify:** `middleware/perception/test/test_goal_escape.py:11-12`의 import와, `control.*` 경로를 매핑하는 setup.py나 manifest를 고친다. 먼저 `grep -rn "goal_escape" middleware tools/harness`로 확인한다.
- **확인:** 시험 PC 설치본에서 `python -c "from control.goal_escape import GoalEscape"`와 goal_node 기동 시험이 통과해야 한다.
- **Safety:** 파일 단위 safety 태그가 있으면 trailer를 단다.

### Task 12: learning 담당 폴더 맞추기

- **Move:**
  - `learning/training/perception/review_{bridge,dataset,eval_package,eval_companion,provenance,authority}.py`를 `learning/curation/perception/`으로 옮긴다.
  - `learning/registry/perception/intake.py:298 evaluate()`와 `intake_eval_gate.py`를 `learning/evaluation/perception/`으로 옮기고, registry는 import해서 쓴다.
- **Modify:** CLI entry point, `tools/harness/platform_parts.yaml`의 owner, `learning/*/AGENTS.md`를 고친다.
- **Test:** `test/test_omx_collection_pipeline.py`와 `test/test_omx_wrist_alias.py`를 `learning/curation/omx/test/`로 옮긴다.
- **확인:** `remote_pytest.py -- learning test/learning`, `test/architecture/test_platform_parts.py`

### Task 13: Console 전용 클라이언트를 Console로

- **Move:** `shared/web/fleet-client.js`와 `shared/web/request.js`를 `operations/site_ui/console/`로 옮긴다. 리뷰 웹앱이 `createRequest`를 쓰는지 먼저 grep한다. 쓰면 `request.js`는 shared에 남긴다.
- **확인:** Console 브라우저 회귀 시험.

### Task 14: tools 일회성 WSL 스크립트와 docs/validation 코드

- **Move:** 조사에서 나온 `tools/*.sh` 17개(`/rosy` 하드코딩)와 `tools/probe_wsl.sh`를 `docs/reference/legacy-tools/wsl/`로 옮긴다.
- **Modify:** `test/architecture/test_folder_layout.py:101-106`. docs/validation에서 `evidence/` 밖의 `*.py`도 막는다. 지금 있는 9개는 허용 목록에 넣는다. 기록은 고정이라 옮기지 않는다.
- **Modify:** `operations/fleet/test/test_fleet_sim_site_d601.py:33-44`. evidence 스크립트 내용을 검사하는 부분을 지우고, 같은 검사를 현재 launch 파일(`integrations/simulation/gazebo/launch/`)에 대해 한다.
- **Delete(git rm):** `middleware/perception/map/map_260905_update_v2/reports/`의 결과 파일 4개(D-226).
- **확인:** `remote_pytest.py -- test/architecture operations/fleet/test/test_fleet_sim_site_d601.py`

---

## 묶음 4 — 결정이 필요한 것 (코드 작업 전에 ADR)

각 항목을 Proposed ADR로 올리고, Accepted가 되면 별도 plan을 쓴다.

| 항목 | 선택지 |
|---|---|
| contracts 안 동작 코드(`account_client.py` PKCE 클라이언트, `prediction.forward()`, `camera_setup.judge()`) | owner 패키지로 옮김 / contracts 규칙을 고쳐 허용 |
| learning이 middleware·tools를 `sys.path`로 import(`road_replay.py` 등 약 12곳) | 필요한 부분을 contracts로 올림 / platform_parts에 예외 등록. 어느 쪽이든 `import_prefix: []` 경로도 경계 시험이 검사하게 한다 |
| peer_crypto·TLS 사본(CORE와 Fleet) | `contracts/foundation`으로 옮겨 사본 제거 / 지금처럼 사본과 대조 시험 유지 |
| Fleet `localization/*` 자세 판정 | World로 옮김 / Fleet 소유로 문서화 |
| Gazebo scripts 위치 | platform_parts(tools/sim)과 책임 문서(유지) 중 하나로 통일 |
| Isaac 위치(`learning/envs/isaac`) | integrations/simulation/isaac로 옮김 / 유지 |
| 로봇을 움직이는 보정 노드가 perception에 있음 | drive로 옮김 / nodes 예외 유지 |
| `deploy/site/install-model-pc-guard.sh` | `deploy/model_pc`로 옮김 / 이미 legacy이므로 삭제 |
| `local_action_transport`·`local_stop_transport`의 `_exchange` 중복 | safety 경로라 Safety-Review를 거친 뒤에 합침 |

---

## 조사 근거 (요약)

조사 4건의 원본 보고는 이 세션의 대화에 있다. Task가 인용한 경로와 행 번호는 2026-10-20 `main`(8d8921ac0e) 기준이다. 착수할 때 행 번호가 맞지 않으면 함수 이름으로 다시 찾는다.
