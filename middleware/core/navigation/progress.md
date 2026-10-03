---
module: navigation
logical_modules: [M06, M07, M11]
owner: NAV
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "Nav2 모션 상한 fail-closed 계약 시험 통과 (2026-09-15, 5 passed)"
    cmd: "python3 -m pytest test/test_nav2_profile_limits.py -q"
  LOCAL:
    state: GO
    evidence: "36 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리). 패키지 전용 pytest 없음 — repo test/에서 모듈 경로 시험 5개를 grep해 실행"
    cmd: "python3 -m pytest test/test_nav2_hardware_slice.py test/test_footprint_profiles.py test/test_nav2_profile_limits.py test/test_nav2_bandwidth_contracts.py test/test_flask_launch_removed.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "Nav2/SLAM Toolbox 실물 launch 미재실행. 현재는 ament_lint와 조합 계약 시험뿐 — ROS 2 Jazzy 환경에서 hardware.launch.py/gz_*.launch.xml 재실행 필요"
  ARTIFACT:
    state: HOLD
    blocker: "ARM64 로봇 이미지에 포함되나(Dockerfile/compose) 서명 manifest와 immutable digest 발행 전"
  DEVICE:
    state: HOLD
    blocker: "Pi bench Device 설치와 device-readback.sh --json 증거 없음"
  FIELD:
    state: PARKED
adrs: [D-2, D-3, D-4, D-40, D-54, D-58, D-144, D-182, D-184]
plans:
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5.md
---
## 지금 상태

- Nav2와 SLAM Toolbox의 launch/config/맵. Flask UI는 D-3로 `core` FastAPI에 완전히 대체되어 삭제됐다.
- 패키지 자체 pytest는 없다(AGENTS.md 명시) — 실제 계약은 repo 루트 `test/`의 nav2 관련 5개 파일이 담당한다.
- Nav2 `velocity_smoother` 출력은 `nav_cmd_vel`로 remap되어 CommandManager가 최종 `cmd_vel`을 소유한다(D-2).
- `profile_limits.py`(신규, 미커밋)가 Device 모션 상한의 launch-time guard다(D-54 Proposed) — hardware launch override로 우회 금지. `footprint_profile.py`도 신규다.
- 작업 트리 미커밋 변경: `launch/hardware.launch.py`, `params/nav2_params.yaml`, `params_rewrite.py`, `site_map.py`, 신규 `footprint_profile.py`/`profile_limits.py`. LOCAL 증거는 이 작업 트리 기준이다.

## 다음 gate

1. WIP를 커밋하고 LOCAL을 커밋 기준으로 재실행해 `last_verified.commit`을 채운다.
2. ROS 2 Jazzy 환경에서 Nav2/SLAM 런치를 실제로 재실행해 ROS-SIM을 되돌린다.
3. 서명된 ARM64 artifact 발행 후 Pi readback(ARTIFACT → DEVICE).

## 현재 유효한 금지사항

- `gz_bringup_launch.xml`은 `bringup_launch.xml`을 include한다 — 로봇용 Nav2 XML을 fork하지 않는다.
- `profile_limits`는 더 높은 hardware launch override로 우회하지 않는다(D-54).
- TF/param 정책은 `launch/`가 아니라 `navigation.*`에 둔다.
- mapper `scan_topic`의 절대/네임스페이스 여부를 `gz_multi.launch.py`와 별도로 가정하지 않는다.
