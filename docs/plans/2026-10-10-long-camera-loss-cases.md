# 장기 CAMERA_LINE LOST의 처리와 사례 기록

상태: 현장 사례 분석 및 후속 구현 계획. D-617 조향 수정은 두 장치 release 2026.10.10-131에 적용됨. 아래 기록 자동화·진전 감지 전체가 설치됐다는 뜻은 아니다.

## 현장 원인 구분

`camera_reselection_required`는 LOST latch의 표시다. 원인을 그대로 설명하는 이름은 아니다. 같은 모델의 최신 receipt가 있어도 `drivable_closed`, IR 중앙선, freshness, confidence 또는 containment 조건 때문에 복귀하지 못할 수 있다. 이를 모델 미적용이나 재시작 필요로 곧바로 해석하지 않는다.

- 8kcn 초기 600초: 카메라 visible 4,803/4,803, IR 중앙선 판정 11,068/12,007. 정지의 대부분은 `lane_departure`; 관제 거부 `no_motion_hold:local_disabled`.
- 뒤의 장기 LOST: 측면 LiDAR 0.145m인데 고정 0.20m로 출구를 닫아 `drivable_closed`. 몸 바깥 0.05m 기준 수정 후 `drivable_centre`와 실제 TRACKING 복귀를 관찰했다. 이후 다시 LOST/회전도 나타나 전체 문제가 해결됐다고 보지 않는다.
- 9dfk: 차선 너머로 거부한 출구를 기억이 다시 살려 pivot. 앞 물체 약 0.22m에서 시작할 수 있었던 조기 회전도 분리해 수정했다. 실제 CORE는 몸 여유 약 0.02m에서 정지했다.

## 처리 순서

1. 첫 LOST 순간에 원래 관측 실패 사유, 전략, 양쪽/앞 LiDAR 거리, IR 판정, mask/frame age, 모델 revision, mode/hold, pose/velocity를 같은 시각과 stuck ID에 묶는다.
2. 기존 자동 재획득은 최신·신뢰 가능한 차선 3프레임 이상이 1초 동안 이어지고 IR guard가 clear일 때 같은 CAMERA_LINE 안에서 해제된다. IR 또는 CORE 장애물 정지를 자동 재획득이 덮지 않는다. 모드 OFF/ON 반복으로 latch나 복구 횟수를 지우지 않는다.
3. 5초 지속되면 관제에 한 사건으로 보낸다. zero-command의 기존 `stuck_report_s: 5`와 비제로 pivot·진전 없음은 다르다. 뒤의 것은 D-607 진전/왕복 검출이 필요하며 설치 proof를 따로 요구한다.
4. 관제는 최신 전후방·차선·횡단보도·지도 자세 근거를 재조회하고 기존 BACK_AND_RETRY 등 허용 답만 고른다. CORE는 뒤 띠·주행 trail·후진 횟수를 재검증한다. `local_disabled`, `crosswalk_unknown`, rear/trail 거부는 사건에 기록하며 무조건 RESUME하지 않는다.
5. 답을 보낸 뒤 실제 복귀·진전이 있는지 확인한다. 명령 수락만 해결로 기록하지 않는다. 동일 위치에서 재발하면 같은 사례의 재발로 집계하고 재시도 예산을 유지한다.
6. 횡단보도는 별도다. 5초 연속 비움과 최소 40 scan 근거로 통과하고, 점유/불확실성/낡은 근거가 있으면 기다린다. 막힘의 5초 시한을 횡단보도 통과 승인으로 사용하지 않는다.

## 지금 남는 로그와 보강할 곳

| 기록 | 현재 증거 | 제한/후속 작업 |
|---|---|---|
| operator console | `X:/DevTemp/lane-pair-analysis/*-d617-console.log`: 시각·mode/state/reason·명령·confidence·gap·stuck | 텍스트 로그다. 구조화 사건 export와 연결할 필요가 있다 |
| robot Pilot MCAP | camera, IR, LiDAR, odom, 최종 cmd_vel, observation, keep_debug | 작업당 600초, 카메라 재시작 시 녹화 종료. 연속 시험에서 idle을 읽어 새 녹화를 시작하고 이전/새 recording ID를 사건에 연결해야 한다 |
| Fleet 판단 로그 | 현장 container log의 stuck ID·거부 사유·사람에게 올림 확인 | D-610 `fleet.stuck.episodes`는 점검 시 설치되지 않았음. 소스의 30일 SQLite 사례 기록·결과 확인을 현장에 있다고 보고하지 않는다 |
| 사례 원본 | 600초 녹화 추출과 분석 JSON을 `X:/DevTemp/lane-pair-analysis/`에 보존 | 영상 위치와 로봇 ID 독립 확인, 단독/동시 동일 출발점 비교가 아직 필요하다 |

후속 우선순위는 (1) 녹화 재시작 및 사건 ID 연결, (2) 관제 사례 저장/복구 결과 확인 설치, (3) 비제로 회전의 5초 진전 판단, (4) 단독/동시 동일 조건 재현이다. 속도 2배는 8kcn 회전 응답과 mask 지연 근거를 확인한 뒤 별도로 적용한다.
