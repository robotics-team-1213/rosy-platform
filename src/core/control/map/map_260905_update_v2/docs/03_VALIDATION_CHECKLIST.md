# MAP 260905 검증 체크리스트

v2 / 2026-09-20

## 1. 완료 구분

**정적 검사와 런타임·실기 검증을 분리합니다.** `reports/package_validation.json`은 파일 검사 결과이며, 아래 Gazebo·Nav2 시험을 대신하지 않습니다.

실제 시험 전에 `config/safety_review_template.yaml`을 채웁니다. footprint·최소 벽 이격·scan freshness·정지 지연 기준이 미확정이면 관련 항목은 `BLOCKED`입니다. 빈 값을 0으로 간주하지 않습니다.

사용 상태: `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`. 실행하지 않은 검사는 PASS로 표시하지 않습니다.

## 2. 공통 사전조건

시험마다 world/map/full Nav2 YAML/전개된 URDF/안전설정의 해시, ROS·Gazebo·Nav2 버전, PC·GPU, domain·namespace·partition, 선택한 패치 단계와 시작 pose를 기록합니다.

실기 모터와 시뮬레이션 명령 경로가 분리되어야 합니다. 아래 의도적 충돌·고장 주입 시험은 **시뮬레이션 또는 구동부가 안전하게 격리된 시험 환경에서만** 합니다.

각 실행은 이전 시험의 goal·recovery·teleop·clock·initial pose가 남지 않게 초기화합니다. geometry 검증의 ground truth와 localization 평가용 추정 pose를 구별해 저장합니다.

## 3. 시험 항목

| ID | 시험·입력 | 통과 기준 | 수집할 증거 |
|---|---|---|---|
| S-01 | 원본과 v2 모델 비교 | 모든 모델의 pose·visual·collision·surface 의미가 동일. 벽 16개 | 정적 검사 JSON, world diff |
| S-02 | PGM/PNG/YAML·원점 검사 | 600×300, 5 mm, 지정 원점. 예전 점유 지도와 픽셀 동일 | 픽셀 hash, probe 결과 |
| S-03 | X 하단 연결성 | 4/8-neighbor 모두 두 빈 영역, X 하단 분리 유지 | 연결성 검사 JSON |
| G-01 | `gz sdf -k` 및 월드 로드 | 대상 parser 검증 성공, 필수 plugin/engine 로드 실패 없음 | stdout/stderr, 버전 |
| G-02 | 로봇 생성 후 정착 | 생성 중 관통·전도·지속 진동 없음. 유효 scan과 odom 확인 후 이동 허용 | 자세·속도·scan 로그, 영상 |
| G-03 | 직선/대각/접합부 충돌 | 시뮬레이션에서 벽 반대편으로 넘어가지 않음. 수치적 접촉 침투 허용한도는 사전 합의 | ground-truth trajectory, 접촉/충돌 시각화, 영상 |
| T-01 | map·scan·TF 중첩 | 축 반전·고정 회전·체계적 오프셋 없음. map→odom 공급자 중복 없음 | RViz, TF, 좌표쌍 오차 |
| T-02 | sim time·clock·domain | 예기치 않은 clock publisher나 실기 motor subscriber 없음. 정지/재개 시 명령 재사용 방지 | graph, topic endpoint, clock 기록 |
| N-01 | 오른쪽 외곽 통로 양방향 | footprint의 벽 교차 0, 승인된 최소 이격 충족, 목표 판정 타당 | 경로·footprint·실제 pose·최소 이격 |
| N-02 | 내부 코너·회전·X 근처 접근 | swept footprint가 벽을 침범하지 않음. 회전·후진 recovery 포함 | 전 구간 pose+orientation, 회전 영상 |
| N-03 | 정상 goal 정밀 도착 | 액션 결과뿐 아니라 요청 goal 대비 최종 XY/yaw 오차가 사전 시험 요구 충족 | goal 원본, path endpoint, final pose, 결과 |
| N-04 | `(-0.7518,-0.54)` 고립 영역 goal | 주 구역에서 연결 경로 생성 불가. 근처 다른 지점 도착을 성공으로 처리하지 않음 | 경로 반환/오류, 최종 goal 차이 |
| N-05 | costmap metadata·성능 | 실제 해상도가 의도와 일치. 설정 주기·프로젝트 지연 기준 충족 | metadata, loop duration, real-time factor, CPU/GPU |
| N-06 | RPP B단계 전후 | 관통 0·최소 이격 유지·정지거리/예측 범위 요구 충족. 성공률만 개선한 변경은 불충분 | lookahead_arc, 명령, 속도·제동·정지 지연 |
| N-07 | Progress C단계 정지/저속/회전 | 실제 정지·끼임이 localization 흔들림 때문에 진척으로 오인되지 않음. 기존 timeout 보존 | checker 상태, ground truth vs odom |
| H-01 | 실기 guard에 sim/replay 입력 주입 | 실기 모드에서 비승인 출처를 거절. frame_id만 같은 데이터도 신뢰하지 않음 | 판정 사유, source endpoint, 모터 출력 차단 기록 |
| H-02 | stale scan·scan 중단·cmd timeout | 승인된 기존 기준 내에 차단/정지. 기준을 이번 패치 때문에 늘리지 않음 | age, trigger 시각, 정지 시각, 원본 값 비교 |
| H-03 | 안전설정 전후 비교 | 실제 footprint·최소 이격·하드웨어 provenance·watchdog 등 승인값 유지 | 원본 hash, runtime dump, 승인 서명 |

N/H 항목의 기준은 [파라미터 문서](02_PARAMETER_REFERENCE.md)와 실제 프로젝트 안전 요구를 함께 사용합니다. 여기서는 아직 모르는 실기 기준값을 만들어 채우지 않았습니다.

## 4. 측정 방법

**최소 이격:** 로봇 중심에서 벽까지 거리만 측정하지 않습니다. 각 pose에서 실제 footprint polygon과 world collision polygon의 표면 간 최단거리를 계산합니다. 회전 중에는 pose 샘플 간의 swept volume 누락 여부도 확인합니다. sparse pose 기록만으로 전체 구간의 무충돌을 증명하지 않습니다.

**정지거리:** 제어 명령이 0이 된 순간과 실제 바퀴/몸체가 멈춘 순간을 구분합니다. latency와 braking 측정값을 분리하고, 기존 안전 margin을 차감해서 시험을 통과시키지 않습니다.

**목표 오차:** 요청 goal과 마지막 path waypoint를 모두 남깁니다. goal checker의 tolerance를 실제 정확도 보장값으로 사용하지 않습니다. 최종 자세에서의 XY/yaw 오차를 다시 계산합니다.

**진척도:** ground truth상 정지인데 odom/AMCL이 흔들려 이동 반경을 넘는 경우를 별도 기록합니다. C단계 반경 축소에 따른 오판을 숨기지 않습니다.

## 5. 반복·환경 제안

초기 확인은 각 방향 한 번으로 시작할 수 있지만, 종료 판단에는 동일 조건 반복과 초기 자세 편차를 포함합니다. 예를 들어 각 방향 10회는 파일럿 비교용 제안이지 신뢰성 인증 기준이 아닙니다.

카메라/시각화 부하를 끈 기준시험과 실제 예정 부하를 켠 시험을 구분합니다. 저속 성공만 확인한 뒤 높은 속도로 실기에 적용하지 않습니다.

## 6. 증거 폴더 예시

```text
docs/validation/run_YYYYMMDD_HHMM/
  result.md
  versions.txt
  hashes.txt
  effective_params/
  tf/
  rosbag/
  screenshots/
  video/
  metrics.json
```

rosbag 토픽은 실제 namespace와 명령 경로를 확인한 뒤 정합니다. 다음은 대표적인 기록 대상입니다.

```text
/clock, /tf, /tf_static, /scan, /odom, /map
실제 controller output, smoother output, 최종 motor/sim cmd_vel
/global_costmap/costmap, /local_costmap/costmap
local/global published_footprint
planner path, goal request/result, guard status/reason
```

부재한 토픽을 임의로 있다고 가정하지 않습니다. 센서 정보와 graph 기록은 프로젝트 접근권한에 맞춰 보관합니다.

## 7. 종료 기준

파일 정합, 시뮬레이션 기능, 실기 안전을 각각 승인합니다. 모든 기능시험을 통과했더라도 실제 안전 원본·로봇 모델이 미확인이라면 **실기 적용 승인은 보류**합니다.

현재 패키지에서 G/T/N/H 런타임 항목은 `NOT_RUN`입니다. 담당자가 결과 양식을 채우고 증거를 연결한 후에만 상태를 변경합니다.
