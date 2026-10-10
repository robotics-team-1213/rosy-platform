# 두 로봇 한 바퀴: 소스·현장 읽기, 2026-10-10

**판정: SOURCE 시험 통과, ROS-SIM·DEVICE·FIELD 주행 수용 HOLD.** 이 기록에는 주행 명령이나 현장 설치가 없다. 두 로봇의 동시 한 바퀴와 원위치 정지는 아직 관찰되지 않았다.

## 후보와 시험

- 후보 브랜치 `feat/one-lap-console`, 읽기 시 HEAD `9c2059fb9`. 관제에서 로봇별 출발·복귀 장소와 경유 장소를 정하고, Fleet은 `repeat:false` 경로를 계획·실행한다. Fleet이 계획 경로 이탈을 감시하고, AI PC의 `trip_route_check`는 그림자 사실로 기록한다.
- AI PC 원격 시험은 코드 SHA `9854686fe5`에서 Fleet trip·site map·AI facts와 situation analyzer·service를 함께 실행해 **161 passed**, `test/known_failures.py`는 NEW 0, KNOWN 0이었다. 이후 커밋 `9c2059fb9`는 생성 문서만 갱신했다. 관제 경로 Node 시험 5 passed, `git diff --check` 통과.
- `python tools/harness/rosy_harness.py lint`는 이 브랜치에 없는 동료 선점 ADR D-610·D-611·D-612 때문에 3 errors였다. 이 브랜치의 로그 형식·생성 문서 오류는 해소됐다. 이 결과를 전체 lint 통과로 부르지 않는다.

## 현장 읽기 (2026-10-10 16:08 KST)

AI PC의 기존 `ai_observer` 읽기 권한으로 Fleet `GET /api/fleet/state`, `/api/fleet/trips`, `/api/fleet/ai`, `/api/fleet/robots/{id}/map-pose`, `/api/fleet/site-map/active`를 조회했다. 현장 PC의 컨테이너 태그도 읽었다. 주소·토큰은 기록하지 않는다.

| 항목 | 관찰 |
|---|---|
| 설치 Fleet | 이미지 태그 `b45e9a36c17659e0bc64f3cc67474c08dacb5629`; 로컬 Git에서 이번 브랜치의 첫 구현 `71ad37f8c`는 그 이미지의 조상이 아님 |
| 활성 지도 | `map_v2_fleet` v5, SHA-256 `cd13474068721637c1824f7b97422eef6370fd3ca5c3788433d060b159acf94f`; `W_mid`=(-1.2953,-0.0037), 파란 B `E_mid`=(0.8559,-0.5134), 둘 다 `kind:stop` |
| Fleet trip | 열린 trip 0개 |
| AI PC | `rosy-situation` heartbeat v0.2.0, `owner_mode:shared`, 상태 `present`; 그림자 사실 0개. 후보 v0.3.0은 미설치 |
| `rosy_40` | 온라인, IDLE, line-follow OFF, E-Stop false, 지도 자세 (-1.3289,0.0588) LOCALIZED, `junction_turn:false`, `junction_pivot:true`, `site_floor_map_id` 미광고. `W_mid`까지 약 0.071 m로 후보의 0.05 m 출발 허용 거리를 넘음 |
| `rosy_41` | 온라인, IDLE, line-follow OFF, E-Stop false, 지도 자세 (-0.1845,0.3558) LOCALIZED, `junction_turn:true`, `site_floor_map_id:map_v2_fleet`. `E_mid`에서 멀리 있음 |
| 차로 적합성 | 정지 중 Fleet `lane_compliance`: `rosy_40` WARN, `rosy_41` ACT. 이 경고는 실제 주행 이탈 증거가 아니지만 출발 전 위치·교정 점검 근거임 |

Fleet의 차로 trip은 `junction_turn`이 참이어야 시작한다. CORE의 이 값은 신선한 keep 관찰과 회전 motion basis로 계산된다. `rosy_40`에서 어떤 근거가 빠졌는지 이번 REST 읽기만으로 특정할 수 없으며, 능력 값을 강제로 바꾸지 않는다. 두 로봇은 관제에서 선택할 출발 장소에 놓이고 방향·몸체 여유가 확인돼야 한다.

## ROS-SIM과 다음 수용 조건

`python tools/remote/remote_pytest.py --pick sim`은 모델 PC의 여유 메모리 3.0 GB가 요구 8 GB보다 적어 실행 호스트를 고르지 못했다. 이전 [Fleet 한 바퀴 시뮬레이션](../lane-trip-lap-sim4-2026-10-09/result.md)은 도착 사례가 있으나 링 반경 합격선을 넘지 못했고, [몸체 경계 검사](../lane-bend-map-footprint-2026-10-10/result.md)는 페인트 접촉 반례를 남겼다. 이 기록들은 이번 후보의 동시 주행 안전 증거가 아니다.

다음은 설치 후보 SHA와 `rosy_40`의 회전 근거, 두 출발 장소·방향, 최신 카메라·IR·LiDAR·지도 자세를 확인한 뒤 격리된 Gazebo에서 두 로봇 동시 주행·몸체 간격·이탈 정지를 재생하는 것이다. 이후 현장 감독 아래 단일 로봇 저속 검증과 동시 한 바퀴를 각각 계측한다. 두 trip `arrived`, 각 출발 장소에서 실제 정지, 차체 경계 침범 0, Fleet/AI/CORE 기록과 독립 영상의 시각 일치가 있어야 FIELD 완료다.
