# Pinky drivable v2: 기존 완주와 최신 소스 재실행

2026-10-19 KST. 기존 r51 원본과 새 Gazebo 실행을 대조했다. 모델과 제어 코드의 소비를 확인했으며 실물 배포·주행은 하지 않았다.

## 버전과 범위

- 기존 r51a/r51b source commit: `91f14c997fcd1c509b2ee6bb9f72b2fdc8548090`.
- 완주 수정 집계 commit: `39d2ffae42f0ab598b9ab07ac7f10acd83f69856`.
- 이번 실행 source commit: `ff8eca4d9b4adcecaccdabf7b9e3886c4eaca789`. 이후 main 병합을 포함하므로 r51과 동일 바이트의 재현은 아니다.
- 모델: `lane-seg-20261010-451f0f85`, ONNX SHA-256 `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`. 새 실행 전후 실제 파일과 manifest의 hash가 일치했다.
- 실행 경로: 실제 Gazebo 센서 → learned drivable → Drive → CORE 최종 명령. 별도 강화학습 정책 승격·적재 시험이 아니다.
- 세 실행 모두 GPU 렌더링, `--lap --stall-s 60 --record --skip-check lane_return` 조건이다. 차선 복귀 검사를 생략했으며 실물 운용 수용으로 확대하지 않는다.

## 기존 성공 기록의 재확인

| 항목 | r51a / 모델 PC | r51b / AI PC |
|---|---:|---:|
| Fleet 최종 이벤트 | arrived | arrived |
| 시험 최종 판정 | PASS | FAIL |
| 정착 후 목표 거리 / 기준 | 0.108 / 0.15 m | 0.156 / 0.15 m |
| 반대편 경유점 최근접 거리 | 0.040 m | 0.029 m |
| 샘플 경로 누적 이동 | 6.739 m | 6.812 m |
| 주행 시간 구간 keep_debug 인식 | learned_drivable 1,499건 | learned_drivable 1,478건 |
| 위 구간 대체 인식 | 0건 | 0건 |
| 마지막 명령 / odom 선속도 | 0 / 0 m/s | 0.04 / 약 0.04 m/s |

주행 시간 구간은 첫 비영 cmd_vel부터 마지막 비영 cmd_vel까지다. 준비 중 fallback은 각각 1건·2건 있었고 첫 비영 명령보다 13.46초, 20.201/19.996초 앞이었다. 샘플 경로 누적 이동은 보존된 path 구간 길이의 합이며 연속 궤적의 정확한 길이가 아니다. `result.json`의 `moved_m`는 한 바퀴 시작점과 정착점 사이 거리이므로 전체 이동 거리로 읽지 않는다.

두 실행의 횡단보도 looking 진입·해제 로그는 각각 두 쌍이다. 따라서 카메라 drivable의 완주·정지 성공 근거는 있지만, 기존 일지의 두 arrived 이벤트를 두 번의 최종 수용 통과로 계산하면 안 된다.

## 최신 워크트리 재실행

고정 commit 실행 명령은 `tools/remote/remote_sim.py --host ai --sha ff8eca4d9b4adcecaccdabf7b9e3886c4eaca789 --minutes 60`이다. bench는 `fleet_trips`, 인자는 `--render gpu --learned-lane-pointer <host-model-pointer> --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return`이다. 실행 식별자는 `sim-ff8eca4d9b-043ecd`다.

**exit 1 / FAIL.** 약 523.5초 뒤 `started → running → stopped`, 사유 `stall`로 종료됐다. 서쪽 횡단보도를 통과한 뒤 `ring_s`의 약 `(-0.188, -0.189) m`에서 진행이 멈췄다. Fleet 경로 투영 진행은 6.683 m, 샘플 path 누적 이동은 약 6.216 m, 경유점 최근접 거리는 0.032 m다. 위치 추정은 LOCALIZED였다.

마지막 50초에는 선속도 명령이 0이고 각속도 범위는 -0.6~+0.6 rad/s였다. 인식 전략은 `drivable_pivot_right`, `drivable_off_line_left`, `drivable_pivot_left` 사이를 오갔다. CORE TRACKING에서 기록된 body gap은 약 0.34–0.35 m, stop gap은 0.02 m였다. 기록은 전진 없이 좌우 회전을 반복하다 진행 정체로 끝난 현상을 보여 준다. 단일 실행으로 특정 커밋의 회귀나 모델·경로 안내·제어 중 하나의 근본 원인을 확정하지 않는다.

주행 시간 구간 인식은 learned_drivable 1,465건 / denoise_fallback 1건이었다. 종료 시 CORE OFF, lease released, 마지막 cmd_vel·odom 선·각속도 0, 잔존 소유 프로세스 없음이 확인됐다. 최신 버전의 안정적인 반복 완주는 미확인이다.

## 보존 증거

원본 r51 기록은 외부 세션 scratch의 `lap-runs/r51a/out/trips/`, `r51b/out/trips/`에 있다. 새 실행은 외부 scratch `pinky-drivable-v2-recheck-20261019/run1/out/trips/`, 실행 로그는 그 상위 `run.txt`에 보존했다. 원격 runner가 결과를 가져온 뒤 아래 로컬 파일의 존재·크기·SHA-256과 실패 결과를 다시 확인했다.

| 파일 | SHA-256 |
|---|---|
| result.json | `446fde73f9a750c4f06392e14fa9ce4cd1a2d699b3a076c03b6637e5b22dc48f` |
| observations.jsonl | `676c524b9b0a7262adad1cb4bc4a3a101e26e27f7face57d3c6b8040c1c0d75f` |
| launch.log | `8b8e1b90ce582c6945b703ab54c01592b7aa0904464b9d7f481b45d32c7c9f71` |
| api-log.jsonl | `aa1a9efae7594d01d4f7176971fbf8fde55e6c13568d5a5e671f4eec08f97422` |

## 실물 테스트 준비 상태

사용자 목적은 성공한 모델·제어 구현을 실물 ROSY Pinky로 옮겨 시험하는 것이다. 성공 소스의 git archive와 해당 모델을 외부 scratch `pinky-v2-device-test-20261019/`에 모아 hash를 대조했다. 소스 archive SHA-256은 `0b06b128773eea23f62ea796a2716409e6075996a813e865a150115ad349c393`다. 이것은 설치 가능한 서명 payload가 아니다.

실물은 대상 지정, 활성 release·모델·카메라 보정·설정 비교가 남아 있다. `paint_source=learned`만으로 drivable 선택을 보장하지 않으므로 `learned_paint_target=drivable`과 실제 모델 소비까지 확인해야 한다. SIM의 정확한 pose·카메라 기하·안내 수명·지도 벽 처리·검사 생략 설정을 그대로 복사하지 않는다. 실물 접속·설정 변경·재시작·운동 명령은 수행하지 않았다.
