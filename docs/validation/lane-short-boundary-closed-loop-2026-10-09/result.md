# 짧은 선 일괄 제거의 폐루프 반례

**판정: 70 mm 길이 필터 채택 보류. 주행 승격 HOLD.** 2026-10-09 KST, 모델 PC의 격리 Gazebo/ROS 2에서 현재 로컬 `main` `247561153ca1032bb4fb65123c1b247adb1240a6`을 빌드했다. [개방루프 반례](../lane-short-boundary-2026-10-09/result.md)를 실제 CORE 폐루프 주행으로 재확인했다. 이 결과는 ROS-SIM 증거이며 장치·현장 증거가 아니다.

## 동일 조건 비교

두 조건 모두 `bend_expected=True`, 동일 B9 world, 시작 자세와 `trip --plan left:60`, CORE HTTP 게이트웨이, 카메라·라이다·odom을 사용했다. 기준은 기존 60 mm 후처리 조건, 후보는 `extract_lines` 결과에서 진행방향 길이가 70 mm 미만인 선을 피팅 전에 제외했다. [SIM 전용 후처리](evidence/sitecustomize.py)는 제품 소스를 바꾸지 않았다. ROS 도메인 91, Gazebo partition `rosy_lane_cl_24756115`, CORE 포트 8127로 기존 작업공간과 격리했다. 코드 archive의 로컬/원격 SHA-256은 모두 `1934f941668a9a5e273e0bfb592c796837ebff124d92fed906807a374fe50d0b`. `colcon build --packages-up-to gz_sim core control description` 16개 패키지가 완료됐다.

| 조건 | run | CORE 종결 | 최종 GT x, y (m) | 경로 길이 (m) | 관측 프레임 | 70 mm 미만 후보 |
|---|---|---|---:|---:|---:|---:|
| 60 mm | [base1](evidence/base1-summary.json) | `junction_transverse` 뒤 `lane_lost_before_junction`, HOLD | -0.955, -0.491 | 1.012 | 299 | 9 |
| 60 mm | [base2](evidence/base2-summary.json) | 동일, HOLD | -0.959, -0.492 | 1.012 | 301 | 7 |
| 70 mm | [gate1](evidence/gate1-summary.json) | 교차부 명령 전에 `camera_reselection_required`, LOST | -1.029, -0.488 | 1.072 | 327 | 0 |
| 70 mm | [gate2](evidence/gate2-summary.json) | 동일, LOST | -1.018, -0.489 | 1.080 | 330 | 0 |

각 run의 [keeper 프레임](evidence/base1-keep.jsonl), [base2](evidence/base2-keep.jsonl), [gate1](evidence/gate1-keep.jsonl), [gate2](evidence/gate2-keep.jsonl)을 함께 보존했다. 후보 조건에서 70 mm 미만 후보가 0건이므로 필터 적용을 관찰할 수 있다. 후보에서도 `bend_ahead`가 5~6프레임 나타났지만 폐루프 목표를 완료하지 못했다. 기준도 교차부를 통과한 성공 사례가 아니다. 2회씩의 SIM 비교만으로 실패 원인을 그 필터 하나로 확정할 수는 없지만, 길이 증가가 성공을 보인다는 가설은 이 시험에서 지지되지 않았다.

## 문제와 다음 가설

첫 번째 결손은 페인트 분류 하나보다 **경계의 연속성과 경로 맥락의 단절**이다. 짧은 선이 굽이의 유효한 오른쪽 경계일 때도 있고, 벽·교차부의 다른 페인트일 때도 있다. 따라서 길이만으로 제거하면 굽이의 증거까지 잃는다. 기준 실행은 교차부에 도달했으나 횡선 검출 후 후속 차선이 없어 HOLD했고, 후보 실행은 그 이전에 재선택 요구로 LOST했다. 이는 각각 관측/경로 인계가 비는 위치를 좁혀 준다.

다음 실험은 짧은 후보의 **동일 물리 경계 ID, 좌우 폭, odom으로 예측한 재출현 위치, 벽·라이다 가림**을 별도 증거로 기록하고, 경로의 허용 굽이 구간 안에서만 이전 경계를 짧게 유지하는 것이다. 유지 중에는 새 주행 가능 영역을 창작하지 않고, 차체 여유와 시간 제한을 만족할 때만 기존 목표를 사용한다. 검증은 동일 GT 좌표 구간의 목표 오차, 연속 미검출, 깜빡임, CORE HOLD/LOST, 교차부 완료, 장애물 여유를 함께 비교한다. 10/7 원본의 사람 승인 물리 경계 ID가 없으므로 AI 후보 판독은 정답으로 승격하지 않는다. 한쪽 선이 사라지고 반대쪽도 확실하지 않으면 STOP이다.

## 재현 경계

원본 상세 실행 로그와 영상 NPZ는 모델 PC의 격리 작업공간 `~/rosy-ml/scratch/lane-closedloop-24756115/b9runs/`에 남겼다. 공개 저장소에는 요약과 keeper 디버그만 담았다. SIM-only `sitecustomize.py`를 `PYTHONPATH`에 두고 `LEN_GATE=0.06` 또는 `0.07`로 각각 새 Gazebo 프로세스를 실행했다. 같은 프로세스를 이어 사용하지 않았다. 실행 후 해당 격리 프로세스와 CORE 포트 8127이 종료된 것을 확인했다. 이 시험은 학습 모델, 로봇 탑재 이미지, 사람 GT, 현장 주행을 검증하지 않는다.
