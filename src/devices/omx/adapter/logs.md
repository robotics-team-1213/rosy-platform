# omx_adapter logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/apps/omx_adapter`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register omx_adapter under D-168
- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가
- 증거: `python -m pytest src/apps/omx_adapter/test -q` 10 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD PARKED
- 결정: D-168
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(devices): move omx_adapter under src/devices/omx/omx_adapter (D-231)

- 변경: src/devices/omx/omx_adapter로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 장치 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 - prepare selected OMX-AI workcell target
- Change: record OMX-AI as selected but keep runtime disabled; remove the unmeasured six-joint default; lock official ROBOTIS Jazzy source revisions and add a separate workstation image plan.
- Evidence: focused profile/product/vendor-lock suite: 13 passed; disabled CLI output: `{}`.
- Gate change: SOURCE/LOCAL evidence refreshed; ROS-SIM and ARTIFACT remain HOLD; DEVICE/FIELD remain PARKED.
- Decision: D-273; execution plan: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · feat(omx): add single-owner arm command policy (D-282 P3)

- 변경: hardware-free command admission policy 추가. 명시적 workcell/runtime-session identity, 단일 active owner, fresh joint-state sequence/calibration, per-joint bounds, bounded goal을 확인하고 action fault/cancel/timeout 후 software HOLD를 유지한다.
- 증거: in-memory action fake 기반 정책 시험 26 passed. ROS graph, vendor action server, serial device, physical stop은 시험하지 않았다.
- gate 변화: SOURCE 코드 증거만 추가; action 통합과 대상 workstation timing이 남아 ROS-SIM HOLD, 실기기·독립 stop/recovery 근거 전까지 DEVICE/FIELD PARKED.
- 결정: D-282; recovery는 명시적 operator 확인과 더 최신의 유효 feedback을 요구하며 자동 goal replay는 금지한다. 실행 순서: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · fix(omx): report cancellation evidence precisely (D-282 P3)

- 변경: action cancel API 호출의 local 결과를 `cancel_outcome`으로 구분하고 호출 예외를 `cancel_call_failed`로 보고한다. monotonic clock보다 미래인 joint feedback은 거부하고 HOLD한다.
- 증거: command-owner ROS-free 시험 28 passed; 전체 focused adapter/product/vendor-lock/identity/preflight 시험 99 passed. 테스트는 가짜 action port와 주입 clock을 사용한다.
- 제한: `poll()`은 호출자 구동이다. bounded 주기 scheduler, ROS/vendor action 연결, action server의 cancel acknowledgement는 아직 없다. API 반환은 실제 취소나 정지를 증명하지 않는다.
- gate 변화: SOURCE 근거 보강. 두 인스턴스 vendor 시뮬 결과는 연결된 probe 보고서로 확인; target workstation timing·camera topics·실물 stop/recovery가 남아 ROS-SIM HOLD, DEVICE/FIELD PARKED.
- 결정: D-282; 실제 OMX capability는 계속 비활성.
## 2026-09-26 · uncommitted · OMX ROS arm and calibrated camera runtime

- Added optional ROS 2 FollowJointTrajectory runtime wiring with configured-joint feedback filtering, steady-clock watchdog polling, cancellation acknowledgement, and terminal action status. Profile remains disabled and runtime has no remote command endpoint.
- Added exact-stamp Image/CameraInfo pairing with bounded unmatched queues, one latest frame, persistent camera identity, optical frame, calibration revision, and a SHA-256 check over all CameraInfo calibration fields.
- Evidence: 99 focused host tests and 11 ROS 2 Jazzy tests in the pinned amd64 image, including isolated vendor Gazebo no-op/readback/cancel and synthetic camera pairing/digest/replay rejection.
- Limits: target Linux workstation timing, physical stop/recovery, camera selection/calibration, immutable artifact, and field runtime remain unverified.
- 변경: Added generic ROS arm-action execution and camera frame admission; OMX profile remains disabled.
- 증거: 99 focused host tests and 11 ROS 2 Jazzy tests pass, including isolated vendor Gazebo no-op/readback/cancel and synthetic camera pairing/digest/replay rejection.
- gate 변화: SOURCE GO; ROS-SIM HOLD pending target-workstation timing and physical fault/stop evidence; ARTIFACT HOLD; DEVICE/FIELD PARKED.
