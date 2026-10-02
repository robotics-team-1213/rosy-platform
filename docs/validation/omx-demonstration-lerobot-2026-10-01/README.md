# OMX Pilot 시연 → LeRobot v3 검증

2026-10-01 · branch `feat/omx-learning` · Windows Docker Desktop/Linux amd64 Gazebo Harmonic.
실물 장치 grant 없음, source mount 읽기 전용, localhost HTTP/ROS. 기록은 Linux volume,
검증 자료는 `X:/DevTemp`다. 이 문서는 로컬 SIM/데이터셋 증거이며 ARM64·DEVICE/FIELD 수용이 아니다.

## 실제 Gazebo 기록과 실제 LeRobot 재독출

첫 성공 원본 episode: `e404b518-8ea3-44c3-aaee-c2083477d75a`.

| 항목 | 관측 |
|---|---|
| 원본 상태 | complete, 15 frames, issues=[] |
| 카메라 | 실제 OGRE2 RGB 320×240, 10 simulation FPS; 파일을 열어 OMX 팔이 보이는 것 확인 |
| joint1 readback | 0.00000000846 → 0.0199999381 rad; 요청 +0.02 rad |
| ROS goal | SUCCEEDED, UUID `fcd9acba-258f-4349-acb1-57e44ea6c9af` |
| LeRobot | 0.4.4 / dataset v3.0 / `omx_sim_ros` |
| reader 검증 | 모든 15 frames의 state/action/duration/int64 source clocks 일치, 영상 차원 일치 |
| H264 압축 오차 | frame별 RGB 평균 절대 오차 최대 1.73614 / 255 (검증 한도 8) |
| 데이터 | MP4/Parquet 생성, writer finalize 후 실제 LeRobotDataset reader로 재독출 |
| 원본 보존 | export의 `rosy_provenance/<episode_id>`에 manifest/JSONL/PNG 복사 |

원본 위치: `X:/DevTemp/rosy-omx-recordings/<episode_id>`.
검증한 export: `X:/DevTemp/rosy-omx-lerobot-gazebo-e404`.
직접 목표(rad)와 gripper(rad)는 native `omx_follower` 정규화 값으로 변환하지 않았다.
운용자가 지정한 과제 성공은 Action 성공과 별도다. 모델 학습/정책 실행은 수행하지 않았다.

## 버전과 재현

- 로컬 recording 이미지 ID: `sha256:faeb86d666c6848ec61478a72087f7cadfc55d6b23e54dff891202b21029efb2`.
- vendor: OpenMANIPULATOR 5.1.2, revision `0a4af6a923b8b7d80b8c20506d1839c54d2e993e`.
- SDF SHA256: `3974f855b61c852c933772929112ff06104ba1a8f5e8bde034b9ebe13d64c61c`.
- CameraInfo SHA256: `d1b538c8a736b665e05433276033d8722519e8ff1533310f8d6ede6ae8ce00bc`.
- 원본은 base source revision과 실행 당시 adapter tree SHA256을 함께 기록한다.
  이번 검증은 개발 worktree이므로 base commit만으로 전체 실행 소스를 식별하지 않는다.
- exporter Python 3.12.14, CPU torch 2.7.1+cpu / torchvision 0.22.1+cpu.
  [실제 설치 inventory](python-3.12-cpu-inventory.txt); 직접 pin은 `deploy/robot/omx/requirements-lerobot-export.txt`.
- 재현: `deploy/robot/omx/README.md`의 실행·기록·export 절차,
  `probe_pilot_recording.py`와 `python -m omx_adapter.lerobot_export`.

0.4.4의 `add_frame` 검증은 explicit timestamp를 extra feature로 거부한다.
따라서 표준 영상 시간축은 index/fps이고 실제 simulation 시각은 int64 feature로 정확히 남는다.
실제 MP4 인코더 이름은 libx264지만 create 인자의 codec은 `h264`다.

## 발견한 오류와 수정

1. 최초 headless renderer 준비 중 broadcaster 기본 switch-timeout(5초)이 만료됐다.
   초기 broadcaster switch-timeout만 60초로 고정했다. 실행 중 0.5초 readback/8초 watchdog은 유지한다.
2. ROS callback에서 이벤트 JSONL을 flush하면 renderer/관절 callback이 밀렸다.
   acceptance callback은 bounded queue만 갱신하고 별도 writer 스레드가 파일을 쓴다.
3. Windows shared recording mount의 느린 쓰기에서 frame_gap/신선도 실패가 발생했다.
   원본은 incomplete로 남겼다. Linux volume을 사용한 성공 기록만 export했다.
4. 지연된 영상은 과거 관절 상태와 pair해야 한다. source skew ≤50 ms와
   현재 live state stream ≤0.5초를 각각 검사한다. 미래 상태로 오래된 영상을 덮어 쓰지 않는다.

## 시험과 제한

최신 재실행도 통과했다: episode `f8f9c67c-0051-4074-b2d1-8d6d234ecf3d`,
11 frames, issues=[], joint1 `0.0000008274 → 0.0199998133 rad`.
ROS UUID `a9940109-eead-433a-bd77-200381c123c5` / SUCCEEDED.
실제 LeRobot reader에서 모든 11 frames 검증, 영상 평균 절대 오차 최대 1.72427.
export는 `X:/DevTemp/rosy-omx-lerobot-gazebo-f8f9`.
같은 세션에서 조종권 갱신을 멈췄고 10초 뒤 별도 episode
`313bfbe1-158a-4b4d-88e5-b0b863d82c40`이 incomplete로 닫혔다:
`control_released`, `outcome_unspecified`, `insufficient_frames`.
이 원본의 오프라인 검증은 거부해야 한다.

리뷰 수정 뒤 최종 adapter tree로 다시 실행했다:
`91723c28-d02c-463e-9b4d-6f65f6a2b614`, **12 frames complete**,
joint1 `0.0000000883 → 0.0199994147 rad`, goal SUCCEEDED.
`X:/DevTemp/rosy-omx-lerobot-gazebo-final`의 실제 reader 12 frames 검증,
영상 오차 최대 1.71431. 원본 `source_tree_sha256`가 최종 adapter/schema 파일 해시와
같음을 별도 재계산으로 확인했다:
dataset commit `88735dcdd1253a58fd853396941da64ce217b8471701c38a30997490953ed433`.
같은 실행의 lease 만료 원본 `33bcbeca-372a-40d4-8cea-1b2206589602`도 incomplete다.

독립 리뷰의 중요한 문제 3개를 수정하고 재검토했다:
저장 오류가 취소·lease 감시로 전파되지 않음, 숨겨진 탭의 늦은 seat 획득 반납,
종료 저장 중 접수된 interruption을 마지막 manifest에 반영.
관련 race/error 테스트 21 passed, Chromium 2 passed.
최종 adapter/foundation/assets/network 회귀 **624 passed, 6 skipped**.

- focused recorder/capture/runtime/API: 21 passed (추가 회귀 시험은 마지막 검증 기록 참조).
- adapter/Pilot/assets/network regression: 259 passed, 28 skipped.
- 실제 LeRobot writer/reader unit integration: 3 passed (MP4/Parquet 포함).
- Pilot Chromium: 시작 실패·재시도·결과 선택·오래된 영상·dispose 반납 1 passed.
- quick tier: 95 passed; 기존 freshness warnings 24.
- 전체 Pilot 재연결/실물 정지/그리퍼 정밀 도달/물체 접촉·집기 과제 성공은 여기서 증명하지 않는다.
- 짧은 한 과제의 데이터 형식·연결 검증이다. 학습 데이터의 다양성·모델 성능 수용은 별도다.

### 전체 브라우저 실행에서 확인한 제한

추가 전체 실행은 680 passed, 6 skipped, 2 failed (1143.66초)였다. OMX 시작 오류가 1초 polling으로 사라지는 문제를 87d1f1e2에서 수정하고 오류가 polling 뒤에도 유지됨을 시험했다. 다른 실패는 Pinky calibration 페이지 load timeout이었다. 두 실패 경로와 hidden seat 경로를 다시 실행해 3 passed, 21 deselected를 확인했다. 전체 실행의 실패를 숨기거나 전체 Pilot LOCAL을 GO로 바꾸지 않는다.

main 병합 뒤 API v1.70 정렬 검증: Fleet task/mission + OMX/foundation 627 passed, 6 skipped; quick 95 passed; OMX Chromium 2 passed; harness lint 0 errors, 기존 freshness warnings 24.
