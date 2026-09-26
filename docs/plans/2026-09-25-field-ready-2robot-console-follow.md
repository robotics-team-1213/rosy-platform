# [2대 관제+군집 FIELD READY] Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-210 범위의 1차 실사용(2대 관제+군집, 실물 1대 + sim 1대, 도크/신호 제외)을 ROS-SIM → ARTIFACT → DEVICE → FIELD 순서로 증거와 함께 닫는다.

**Architecture:** 게이트는 수용 기준 §9 승격 순서(D-213)를 따른다. ROS-SIM은 현재 트리 colcon install 묶음(D-211), ARTIFACT는 Pi 5 네이티브 서명 경로(D-212), DEVICE는 stationary → lifted → floor → 2대 묶음 → 현장 반복 순이다. 구 증거 재사용 금지(D-79).

**Tech Stack:** ROS 2 Jazzy, Python 3.12, colcon, Gazebo (ros_gz), Fleet console (FastAPI), Pi 5 네이티브 ARM64, Ed25519 서명 릴리스, pytest.

**결정:** [D-210](../adr/D-210-field-ready-scope-2robot-console-follow.md), [D-211](../adr/D-211-ros-sim-rerun-bundle.md), [D-212](../adr/D-212-artifact-native-path.md), [D-213](../adr/D-213-device-to-field-promotion.md).
**수용 기준:** `docs/reference/ROSY Module Operational Acceptance Criteria.md` §4 (증거 레코드) / §9 (승격 순서).

**범위 밖 (건드리면 실패):** 충전도크 실물, 신호등 실물, OMX 암, 중앙 Fleet `:8081`, emotion/lamp/led/imu 제품 편입. 이들을 켜거나 capability에 광고하면 해당 Task는 FAIL이다.

---

### Task 1: ROS-SIM 클린 빌드 (D-211)

**Files:**
- Workdir: `src/`
- Verify: `install/setup.bash` 생성 확인

**Step 1: 빌드**

Run: `cd src && colcon build --symlink-install --event-handlers console_direct+`
Expected: 전 패키지 빌드 성공. 과거 `install/` 재사용 금지 — 필요시 삭제 후 클린 빌드.

**Step 2: 오버레이 확인**

Run: `source install/setup.bash && ros2 pkg list | grep -E '^(core|fleet|gz_sim|navigation|description|bringup)$'`
Expected: 6개 패키지 모두 보임.

**Step 3: 증거 기록**

수용 기준 §4 필드(run_id, source `git rev-parse HEAD` + dirty, env, command)로 기록. 다음 Task의 전제.

---

### Task 2: gz_multi 2대 격리 기동 (D-211)

**Files:**
- Launch: `src/sim/gz_sim/` (`gz_multi.launch.py`)
- Test: `src/sim/gz_sim/test/`

**Step 1: 계약 시험**

Run: `python3 -m pytest sim/gz_sim/test -q` (from `src/`)
Expected: PASS (ros_gz 부재 시 self-skip 허용, skip 사유 기록).

**Step 2: 2대 기동**

Run: `ros2 launch gz_sim gz_multi.launch.py robots:=2`
Expected: namespace 2개(`rosy_01`, `rosy_02`) 분리, TF 충돌 없음, 스폰 좌표가 각 로봇 initialpose로 들어감. odom 원점을 관제 pose로 오인하지 않음.

**Step 3: 증거 기록**

`world/map ID`, spawn pose, graph 스냅샷 보관. 실패 시 HOLD, 다음 Task 진행 금지.

---

### Task 3: Fleet console gather/scatter 2대 (D-210/D-211)

**Files:**
- Modify: 없음 ( salesforce `src/site/fleet/fleet/server/`, `fleet/hub/` 읽기만)
- Test: `src/site/fleet/test/`
- Run: `tools/run_fleet_sim.sh`

**Step 1: 단위 계약**

Run: `python3 -m pytest site/fleet/test -q` (from `src/`)
Expected: PASS.

**Step 2: 시뮬+콘솔 통합**

Run: `bash tools/run_fleet_sim.sh`
Expected: 콘솔이 2대 상태 gather, 로봇별 goal/cancel과 전체 e-stop이 올바른 대상 CORE에 전달됨. 일부 로봇 timeout이 전체 성공으로 합산되지 않음.

**Step 3: 증거 기록**

요청/응답 + 이벤트 `seq` 보관 (PRT-004 추적은 D-170에 따라 REST+seq로 대체).

---

### Task 4: Formation relay + HOLD/ABORT/resume (D-211)

**Files:**
- Code: `src/site/fleet/fleet/swarm/relay.py`, `session.py`, `arming.py` (읽기; 변경 시 같은 Task에 시험 동반)
- Test: `src/site/fleet/test/test_relay.py`, `test_session.py`, `test_arming.py`, `test_boundaries.py`

**Step 1: 경계 시험**

Run: `python3 -m pytest site/fleet/test/test_boundaries.py site/fleet/test/test_arming.py -q`
Expected: PASS. `formation/`·`arming.py`에 httpx/websockets/asyncio/rclpy import 없음.

**Step 2: 릴레이 불변식 확인**

확인 항목: leader pose byte-for-byte fan-out, 유실 프레임 반복 없음(정지 시 0 Hz), stale/sequence gap 시 FOR-004 HOLD/ABORT, arming 거절은 실행 중 relay/session 불변, resume 전 pending_triggers 해소 필요.

Run: `python3 -m pytest site/fleet/test/test_relay.py site/fleet/test/test_session.py -q`
Expected: PASS.

**Step 3: 2대 시나리오 증거**

Task 2–3 환경에서 follow → 스트림 단절 HOLD → 스트림 복귀 resume → cancel/ABORT를 순서대로 실행하고 각 전이의 이벤트·시각을 보관.

---

### Task 5: ROS-SIM 증거 묶음 확정 (D-211 gate)

**Files:**
- Record: `docs/plans/` 증거 첨부 (이 파일에 체크포인트 추가) + 각 모듈 `logs.md`

**Step 1: 판정**

Task 1–4 증거가 모두 있고 같은 `(source revision, profile, config)` 키에 묶이는지 확인. 하나라도 다른 키·구 트리면 HOLD.

**Step 2: 게이트 기록**

ROS-SIM GO 조건: Task 1–4 PASS + 시나리오 로그. 이 게이트 없이 Task 6 이후 진행 금지.

---

### Task 6: Pi 5 네이티브 ARTIFACT 빌드 (D-212)

**Files:**
- Build: `deploy/image/`, `deploy/robot/Dockerfile` 계열 (읽기; 변경 시 D-212 위반 여부 확인)
- Test: `test/test_arm64_release_builder.py`, `test/test_unsigned_handoff_import.py`

**Step 1: 호스트 계약 시험 (x86 사전 점검용)**

Run: `python3 -m pytest test/test_arm64_release_builder.py test/test_unsigned_handoff_import.py -q`
Expected: PASS. 이것은 ARTIFACT GO가 아니다.

**Step 2: Pi 5 네이티브 빌드**

Pi 5 위에서: base image URL/SHA 고정 확인 → native payload 빌드(core/io linux/arm64) → revision label·image ID 검증 → unsigned payload 원자 생성.
QEMU 발행 금지. 기존 개발 후보 이미지 ID 재사용 금지(D-66).

**Step 3: 증거 기록**

builder JSON, image ID, base digest, source revision 보관.

---

### Task 7: 서명·manifest·SBOM (D-212)

**Files:**
- Release: `deploy/release/` (`manifest.py`, 서명 검증 경로)
- Test: `test/test_release_manifest.py`, `test/test_release_signing.py`, `test/test_release_bundle.py`

**Step 1: 계약 시험**

Run: `python3 -m pytest test/test_release_manifest.py test/test_release_signing.py test/test_release_bundle.py -q`
Expected: PASS.

**Step 2: 오프라인 서명**

서명 환경에서 `SHA256SUMS` 서명 → 빌드 호스트에서 `verify_release_files()` 통과. 개인키는 빌드 호스트에 두지 않음. 산출물: `.img.xz`, `.bmap`, `manifest.json`, `SHA256SUMS(.sig)`, `sbom.spdx.json`, `release-notes.md`.

**Step 3: 비밀 스캔**

마운트된 이미지 트리에 secret 스캔 적용. PSK·토큰·개인키 검출 시 FAIL.

---

### Task 8: BUILD_GO 확정 (D-212 gate)

**Files:**
- Verify: `deploy/image/verify-artifacts.sh`

**Step 1: 이미지 검사**

Run (압축 해제 후):

```bash
sudo losetup -Pf --show rosy-pi5-<release-id>.img
sudo mount /dev/loopXp2 /mnt/rosy
ROSY_IMAGE_MOUNT=/mnt/rosy ./deploy/image/verify-artifacts.sh dist/<release-id>
```

Expected: 필수 unit + enable 상태, recovery 선행·`Requires=`/`After=` 정렬, 공개키 존재·개인키 부재, 기본 `ROSY_RUNTIME_MODE=core`, motor unit 비활성, CORE 로그인 계정 uid 분리, OCI archive 존재, secret 스캔 통과.

**Step 2: 판정**

통과 시 `BUILD_GO`. `ROSY_IMAGE_MOUNT` 없는 실행은 무효. 이것으로 BOOT_GO 승격 금지.

---

### Task 9: SD 기록 + 첫 부팅 (D-213)

**Files:**
- Runbook: `docs/deployment/pi5-acceptance-checklist.md` §§4–5, `docs/deployment/pinky-pro-first-device-runbook.md` G0–G2

**Step 1: 기록**

SD 2장 준비(굽기용+복구용). single-readback 방식으로 기록·검증.

**Step 2: 유선 랜 없이 부팅**

확인: 첫 부팅 자기 HOLD 없음, CORE 기동+대시보드, 인터넷 없이 기동 완료, mode `core`, motor/io 미기동, 전원 재인가 자동 복구.

**Step 3: 네트워크**

`ROSY-SETUP-<id>` AP → setup UI → STA 프로비저닝 → mDNS/IPv4 접속 → peer/인터넷 도달 분리 기록. 실패 시 HOLD.

---

### Task 10: 설치 + stationary readback (D-213)

**Files:**
- Scripts: `deploy/robot/verify/verify-pi.sh`, `deploy/robot/verify/device-readback.sh`
- Test: `test/test_device_readback.py`, `test/test_pinky_commissioning.py`

**Step 1: 설치**

Run: `ROSY_ROBOT_NUMBER=<N> sudo ./install-pi.sh` (identity 없이 진행 금지, 충돌 시 중단).
Expected: core-only 설치, config/data 보존.

**Step 2: 검증 + readback**

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh
sudo /opt/rosy/deploy/robot/verify/device-readback.sh --json
```

Expected: identity·activation/manifest digest·서명 상태·health·graph·config generation·`cmd_vel` publisher 수 일치. 불일치 시 `device_runtime=HOLD`. SSH/HTTP 성공만으로 GO 선언 금지.

**Step 3: stationary CORE 확인**

단일 `cmd_vel` publisher, readiness HOLD 시 zero 출력, e-stop 래치와 해제(새 operator action + fresh evidence) 관측.

---

### Task 11: lifted-wheel bench (D-213)

**Files:**
- Contracts: `test/test_bringup_motor_contracts.py`, `test/test_robot_runtime.py`
- Procedure: `deploy/robot/verify/verify-motors.sh`, `docs/deployment/power-bench-verification.md`

**Step 1: 바퀴 든 상태 시험**

바퀴를 든 채로: deadman/timeout/UART-loss 시 측정 시간 내 zero, `motor/ready` lease 만료, 재시작·e-stop 후 명령 미재개, encoder 방향·scale·rollover 대조.

**Step 2: 판정**

측정값(정지 지연/거리 포함) 기록 없이 다음 단계 진행 금지.

---

### Task 11b: UPDATE_GO (D-213)

**Files:**
- Test: `test/test_release_bundle.py`, `test/test_release_delivery.py`, `test/test_release_updater.py`
- Checklist: `docs/deployment/pi5-acceptance-checklist.md` §6

**Step 1: 실기 update/rollback**

정상 번들 설치 → 손상/미서명/다른 키/보드 불일치 거부 → health 실패 rollback(90초 bound) → 전원 차단 복구(previous가 core로) → staging 정리·여유공간 거부·prune 금지 확인.

**Step 2: 판정**

통과 시 `UPDATE_GO`. motor/io가 어느 경우에도 기동하지 않았는지 확인.

---

### Task 12: 측정 floor course 단일 로봇 (D-213)

**Files:**
- Map/profile: 현장 site map + map ID, 측정 footprint, 속도 envelope (0.20 m/s / 0.80 rad/s 상한, launch override 우회 불가)
- Nav: `src/navigation/navigation/`, CORE readiness gate

**Step 1: P0 가드 확인**

profile 한계 단일 원천, field demo-map fallback 금지(미보유 시 HOLD), footprint 실측 상태만 선택, lifecycle+motor lease 없으면 HOLD+zero.

**Step 2: 주행 반복**

goal → 진행 → 도착 pose/정지 또는 명시 실패, cancel 완료, timeout·bounded recovery, stale localization/TF 단절 시 HOLD. goal error·path length·clearance·정지 지연/거리·covariance·회복 횟수·자원 사용 기록.

**Step 3: 배터리 실측 (`BATTERY_GO`)**

만충/중간/20% 3점 실측 대조, 부팅 직후 크리티컬 오발 방지, 급가속 새그 내성, deep 5% 시 모터 정지+센티넬+유예 동작 확인.

---

### Task 13: 2대 묶음 실물1+sim1 (D-210/D-213)

**Files:**
- Console: `src/site/fleet/fleet/server/`, relay/session (Task 4와 동일 불변식)
- Map: 양쪽 동일 map_id (다르면 `swarm.hold reason: map_mismatch`, 대형 유지)

**Step 1: 동일 맵 2대 세션**

실물 1 + sim 1: console goal/cancel/e-stop, formation arm → relay → watch → HOLD/ABORT/resume, 스트림 단절 HOLD, 일부 timeout의 전체 성공 합산 금지, 접수 표시와 실제 결과 구분.

**Step 2: 증거**

양쪽 map_id, relay 로그, HOLD/ABORT 이벤트, resume 전 재검증 기록. 실물 2대는 PARKED로 남김(2호기 확보 후 후속 ADR).

---

### Task 14: FIELD 반복 + 승인 (D-210 gate)

**Files:**
- Record: 현장 조건·반복 횟수·성공률/오차/지연·승인자·rollback 결과

**Step 1: 반복 실행**

대표 실내 조건에서 Task 12–13 시나리오 반복. 결과 평균으로 다른 키를 메우지 않음(키 변경 시 해당 판정 HOLD 후 재검증).

**Step 2: 승인**

운영자·안전 담당 승인 + rollback 결과 보관 시 `FIELD READY(범위 한정: 2대 관제+군집, 실물1+sim1, 단일 맵)` 선언. 범위 밖 일반화 금지.

---

### Task 15: 게이트·문서 마감

**Files:**
- Modify: 각 모듈 `progress.md` (gate 갱신), `logs.md` (append), `docs/reference/ROSY ADR Log.md` (D-210~D-213 `Proposed` → `Accepted`, 단 해당 범위 증거가 전부 있을 때만)
- Generate: `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`

**Step 1: 시험**

Run: `python -m pytest test/test_module_functional_surface.py test/test_harness_contracts.py -q`
Expected: PASS.

**Step 2: 커밋**

작은 단위로 커밋. `git diff --check` + focused test를 매 커밋 전 실행.

---

**Plan complete and saved to `docs/plans/2026-09-25-field-ready-2robot-console-follow.md`. Two execution options:**

**1. Subagent-Driven (this session)** - Task 1–5 ROS-SIM 묶음부터 subagent로 실행, Task 사이 리뷰

**2. Parallel Session (separate)** - 새 세션에서 executing-plans로 배치 실행, 체크포인트 리뷰

**Which approach?** — 선택됨: 1. Subagent-Driven (this session).

---

## Execution log

### Task 1 — HOLD (2026-09-24, Windows host, ROS toolchain absent)

- `run_id`: task1-ros-sim-clean-build-20260924
- `module` / `scenario`: ROS-SIM clean build / Task 1
- `source`: commit `2661a352a68631b7327d164c2d8e341017ed00af`, dirty. `git status --porcelain`:
  `M "docs/reference/ROSY ADR Log.md"` (D-210~D-213 4행 추가) + untracked D-210~D-213 ADR 4건과 본 플랜 파일.
- `environment`: Windows_NT (PowerShell), Python 3.14.5, x86_64. ROS 2 Jazzy overlay ABSENT,
  `colcon`/`ros2` 없음 (`python -m colcon`: No module named colcon).
- `artifact`: n/a (빌드 산출물 없음 — 빌드 미시작)
- `device`: n/a (호스트 단계)
- `profile`: n/a (빌드 단계, 런타임 프로파일 미개입)
- `config_generation`: n/a
- `command`: `cd src; colcon build --symlink-install --event-handlers console_direct+`
- `observation`: 빌드 미시작. `colcon: CommandNotFoundException` (exit 1).
  Step 2 NOT EXECUTED (물을 것 없음). `src/install/setup.bash` 없음.
  루트 `install/` (2026-09-19/22 생성)은 구 트리 산출물이므로 증거로 미사용 (D-79).
- `fault_recovery`: n/a (장애 주입 없음 — 툴체인 부재가 차단. 복구 경로: ROS 2 Jazzy+colcon 호스트에서 Task 1 재실행)
- `result`: HOLD (툴체인 부재). 판정자: Task 1 evidence subagent (2026-09-24T15:48:21Z).
  다음 gate: ROS 가능 호스트에서 Task 1 재실행이 GO 되기 전 Task 5 묶음 불가, ARTIFACT/DEVICE 승격 불가.
- Spec review: 1차 ❌(§4 필드 명시·파일 기록·source 식별자 보완 요구) → 본 기록으로 해소, 재리뷰 ✅ SPEC COMPLIANT. 코드 없음 → quality review N/A. Task 1 마감.

### Task 2 Step 1 — FAIL (2026-09-24, Windows host, overlay 없음)

- `run_id`: task2-gz-multi-contract-20260924
- `module` / `scenario`: gz_sim / Task 2 Step 1 contract test
- `source`: commit `2661a352a68631b7327d164c2d8e341017ed00af`, dirty (`M docs/reference/ROSY ADR Log.md` + untracked D-210~D-213 ADR·본 플랜).
- `environment`: Windows host, CPython 3.14.5, pytest 8.4.2. ROS 2 Jazzy/colcon/Gazebo ABSENT, colcon overlay 없음.
- `artifact`: n/a (호스트 계약 단계, 빌드 없음)
- `device`: n/a (호스트 단계)
- `profile`: n/a (런타임 미개입)
- `config_generation`: n/a
- `command`: `cd src && python -m pytest sim/gz_sim/test -q` (+ `test_gz_multi_core.py -q -rs` 후속 확인)
- `observation`: 6 failed, 251 passed, 1 skipped, 6 errors (35.71s).
  12건 전부 `test_coverage_harness_contract.py`, 원인 `ModuleNotFoundError: No module named 'control'`
  (`sim/gz_sim/scripts/coverage_harness.py:68`, `tour_plan()` 내 deferred import).
  `test_gz_multi_core.py`는 `launch` 모듈 부재로 self-skip (정당한 ROS-부재 사유).
  launch 파일 `src/sim/gz_sim/launch/gz_multi.launch.py` 존재 확인.
- `fault_recovery`: n/a (장애 주입 없음. 복구 경로: Task 1 GO인 ROS 호스트에서 overlay source 후 재실행)
- `result`: FAIL (Step 1). 판정자: Task 2 Step 1 evidence subagent (2026-09-24T15:51:48Z).
  Step 3 귀결: Task 2 HOLD, Steps 2–3 미시도, 다음 Task 진행 금지(ROS 필요 단계).
- Spec review: ✅ SPEC COMPLIANT. 원인 판정: 환경적 요인 (문서화된 전제 `needs a ROS overlay` 미충족,
  CI도 overlay source 후 실행. cwd 정상, conftest 부재는 의도된 구조이므로 결함 아님).
  코드 없음 → quality review N/A. `PYTHONPATH` 우회 실행은 off-spec이므로 증거로 불인정.

### ⚠️ Source key 변경 기록 (2026-09-25)

- Task 1·2 실행 시 HEAD: `2661a352` (+dirty). Task 3 실행 시 HEAD: `743a707f` (+dirty).
- Delta `2661a352..743a707f`는 docs-only 1커밋 (`docs/logs.md` +9, `docs/validation/uiux-surfaces-2026-09-24/README.md` +11, 코드 변경 없음) — controller 직접 확인.
- Task 1·2 기록은 원본 key 그대로 역사적 실행 증거로 유지 (재작성 금지).
- Task 5 묶음 key는 단일 일관 revision이어야 하므로, ROS 호스트에서 전 ROS 단계를 한 revision으로 재실행하기 전 Task 5는 HOLD.

### Task 3 Step 1 — PASS (2026-09-24, Windows host, ROS-free 패키지)

- `run_id`: task3-fleet-unit-contract-20260924
- `module` / `scenario`: fleet / Task 3 Step 1 unit contract
- `source`: commit `743a707f`, dirty (`M docs/reference/ROSY ADR Log.md` + untracked D-210~D-213 ADR·본 플랜).
- `environment`: Windows host, CPython 3.14.5, pytest 8.4.2. ROS/Gazebo 부재 — 무관 (fleet은 ROS-free, conftest가 sys.path 구성).
- `artifact`: n/a (호스트 단위 계약, 빌드 없음)
- `device`: n/a (호스트 단계)
- `profile`: n/a (런타임 미개입)
- `config_generation`: n/a
- `command`: `cd src && python -m pytest site/fleet/test -q`
- `observation`: 404 passed, 0 failed, 0 errors, 5 skipped.
  skip 5건 전부 `test_geometry.py:124` "FOLLOW is a single follower" (FOLLOW×{2..6} 조합) —
  `geometry.py:115-116`의 by-design guard + `test_follow_refuses_more_than_one_follower` 통과이므로 정당.
  단 doc-gap: FLEET SRS FOR-001·formation AGENTS에 단수 추종자 제한 미기재 (후속 1행 메모 권장, 코드 변경 없음).
- `fault_recovery`: n/a (장애 주입 없음)
- `result`: PASS (Step 1 only). 판정자: Task 3 Step 1 evidence subagent (2026-09-24T15:56:02Z).
  Step 2 (`tools/run_fleet_sim.sh`) 미시도 — Task 3 전체는 OPEN.
- Spec review: ✅ SPEC COMPLIANT. 코드 없음 → quality review N/A.

### Task 4 Step 1 — PASS by citation (동일 세션·동일 key의 결정적 단위시험)

- 근거: Task 3 Step 1 세션의 targeted 실행 `test_boundaries.py 7 + test_arming.py 9 + test_relay.py 22 + test_session.py 57 = 95 passed`.
  controller 직접 재실행 확인: `95 passed in 2.63s`.
- `test_boundaries.py:11-14`의 import 금지(`httpx`, `websockets`, `rclpy`, `asyncio`) 단언 포함 통과.
- Task 4 Step 2의 불변식 체크리스트·Step 3의 2대 시나리오 증거는 OPEN (ROS 호스트 필요).
