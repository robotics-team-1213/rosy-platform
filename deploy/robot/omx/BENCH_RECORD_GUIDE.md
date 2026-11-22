# OMX 작업대 녹화 웹 UI · 리더-팔로워 파이프라인 사용 및 수정 가이드

## 1. 웹 UI 접속 및 사용법
- **접속 주소:** `http://rosy-arm-cell.tailb4b84d.ts.net:8771/` (Tailscale 연결 필요)
- **암 선택 및 카메라 표시:**
  - `arm_a`, `arm_b`, `arm_ab`(양팔 동시), `arm_s` 중 선택하면 해당 암에서 **실제로 녹화되는 카메라만 선명(`● 녹화`)** 하게 표시되고, 나머지 카메라는 **흐림(`미녹화`)** 처리됩니다.
- **리더-팔로워 및 홈 이동:**
  - `arm_a`, `arm_b`는 저장된 리더 포즈(`has_leader_pose: true`)가 준비되어 있어 작업대 확인(`at_bench`) 및 `리더 팔에서 손을 떼었습니다(hands_off_leader)` 체크 후 바로 홈 이동/녹화가 가능합니다.
  - `arm_s`는 작업대 현장에서 리더와 팔로워를 수동 정렬한 뒤 `리더 포즈 저장`을 먼저 실행해야 합니다.
- **LeRobot 파라미터 조정:**
  - `num_episodes`(1~500), `episode_time_s`(1~3600s), `reset_time_s`(0.5~600s)는 과제 카드/UI에서 선택적으로 덮어쓸 수 있으며, `robot`, `max_relative_target`, `use_degrees`, `fps`, `cameras`, `teleop` 등 안전 잠금 필드는 서버가 거부합니다.

- **녹화 시작(`POST /start`):** `X-Bench: 1` 헤더와 `name`, `rig_revision`, `arm`, `config`, `caps`, `calibrations`(+ `at_bench: true`)가 필요합니다.
- **리더 정렬(선택):** `align_leader: true` + `hands_off_leader: true`(replay 없는 단일 팔 텔레옵만)이면 녹화 전에 리더를 팔로워 현재 자세(mount 반영)로 보냅니다.
- 30도 미만 차이 관절은 그대로 두고, 목표가 리더 보정 범위 밖이거나 이동이 실패하면 시작을 거절합니다(녹화는 뜨지 않음).

## 2. 모듈 구성
- `deploy/robot/omx/bench_record.py` — 웹 UI HTTP 서버, 세션 락 격리, `arms_status`, `go_home`, `save_leader_pose`, `save_initial_pose`, `lerobot_params` 검증
- `deploy/robot/omx/bench_record.html` — 반응형 2단 웹 UI, `ARM_PREVIEW_CAMS` 미녹화 카메라 흐림, `caps` 바 차트 편집기, 과제 검색/시나리오 수집 현황
- `deploy/robot/omx/leader_home.py` — `LeaderActuator` 기반 가드된 리더 홈 이동 및 `--read-pose`, Mode 4 `wrist_roll` 멀티턴 초기화
- `test/test_omx_bench_record.py` — 단위/회귀 테스트 (57개)

## 3. 빠른 수정 · 테스트 · 셀 PC 배포 방법
수정 작업은 `D:\DevTemp\omx-bench-deploy\`에서 진행한 뒤 `omx_hotfix.py`로 원격 테스트 및 배포를 실행합니다.

```powershell
cd D:\Dev\Robot\Rosy\rosy-platform

# 1) 수정 파일 커밋 (refs/rosy-wip/omx-bench-deploy)
python tools/remote/omx_hotfix.py commit --base a41840cb86 --ref omx-bench-deploy `
  --file deploy/robot/omx/bench_record.py=D:/DevTemp/omx-bench-deploy/bench_record.py `
  --file deploy/robot/omx/bench_record.html=D:/DevTemp/omx-bench-deploy/bench_record.html `
  --file deploy/robot/omx/leader_home.py=D:/DevTemp/omx-bench-deploy/leader_home.py `
  --file test/test_omx_bench_record.py=D:/DevTemp/omx-bench-deploy/test_omx_bench_record.py `
  -m "omx: update bench_record"

# 2) 원격 pytest 검증
python tools/remote/omx_hotfix.py test --sha <COMMIT_SHA> --log-dir D:/DevTemp/omx-bench-deploy-out -- test/test_omx_bench_record.py

# 3) 셀 PC 배포 및 서비스 재시작
python tools/remote/omx_hotfix.py deploy --sha <COMMIT_SHA> --tested-log D:/DevTemp/omx-bench-deploy-out/run-1.txt --host robttt@rosy-arm-cell.tailb4b84d.ts.net
ssh robttt@rosy-arm-cell.tailb4b84d.ts.net "systemctl --user restart rosy-omx-bench-record.service && systemctl --user is-active rosy-omx-bench-record.service"
```
