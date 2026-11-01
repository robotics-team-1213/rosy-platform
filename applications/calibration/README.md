# ROSY Calibration

셀의 보정을 한 곳에서 보고 돌리는 앱이다([D-951](../../docs/adr/D-951-rosy-calibration-application.md)). 화면은 아직 없다. 이 문서는 앱의 경계와 보정 순서의 정본이다.

## 경계

- 화면: 이 폴더(`applications/calibration/`). 엔진의 결과 파일과 API를 읽고, 보정 실행을 요청한다.
- 엔진: 셀 도구 `deploy/robot/omx/cell_*`. 실제 측정, 판정, 결과 파일은 여기에 있다.
- 에이전트 절차: `.claude/skills/rosy-calibration/SKILL.md`.
- 팔이 움직이는 단계는 [D-911](../../docs/adr/D-911-omx-native-reviewed-operating-envelope.md) 감독 시험이다. 사람이 스위치 옆에 있는지를 동작마다 확인한다. 현장은 착지한 main만 돌린다([D-932](../../docs/adr/D-932-field-runs-one-landed-revision.md)).

## 보정 순서

| 단계 | 엔진 | 결과 | 팔 동작 |
|---|---|---|---|
| 1. 장치 | `omx_devices.py scan`, `omx_cameras.py inventory` | 역할별 장치, 문제 0 | 없음 |
| 2. 높이 | `cell_depth.py` | 테이블 평면, 깊이↔색 정렬, 각 팔 판(FK 0), 면 높이 | 없음 |
| 3. 카메라 모델 | `cell_frame.py learn` / `check`([D-933](../../docs/adr/D-933-arm-s-cell-coordinate-frame-markers.md) 마커) | 카메라 자세, 마커 위치 | 집게 마커를 FK 점에 보인다(감독) |
| 4. 면 | `cell_depth` 결과 → 각 팔 설정의 `surface_z` | 면별 높이(FK) | 없음 |
| 5. 관절 게인 | 세션 설정 `caps.json`의 `i` | 하중 관절 I 게인 | 정지 시험(감독) |
| 6. 점검 | `cell_calibrate.py check` | 남은 할 일 없음 | 없음 |

- 사람이 정하는 것: 인쇄물 부착(D-933), 바닥을 낮출 사각형의 승인(`limits.low_zones`), 동작마다 스위치 확인.
- 숫자를 손으로 고치지 않는다. 다시 재야 하면 그 단계를 다시 돌린다.

## 두 팔

- 세션 잠금은 팔마다다(`joint_tune.session_lock(arm)`, `record_session --arm`).
- 움직이기 전에 경로 점검(`cell_corridor`)과 통로 예약(`cell_space`)을 거친다.
