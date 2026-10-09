# D-507 실제 맵 굽이의 몸체·페인트 샘플 감사 (2026-10-10)

## 범위와 재현

- 감사 기준 소스: `4a34c0a97` (로컬 `main`, 2026-10-10). 주행 로그는 모델 PC의 이전 D-507 Gazebo 실행 `runs_final_a` 23회와 `runs` 15회를 읽기 전용으로 복사했다. SIM 재실행이나 현재 이미지 실행 기록이 아니다.
- 로그 원본은 `X:/DevTemp/lane-bend-map-audit-20261010/{runs_final_a,runs}`에 보관한다. 각 `log.jsonl`의 SHA-256과 실행별 결과는 [sampled-footprint.json](evidence/sampled-footprint.json)에 있다. 공개 저장소에는 원본 로그와 사설 장치 주소를 넣지 않았다.
- 지도 STL SHA-256: `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b` (로컬과 모델 PC 파일 일치). 모델 PC에서 복사한 `urdf_nominal.py` SHA-256: `c2429520238f1218880c8d0bb90d4ef30e54cd7443aba7463195e26c7308de34`. `rosy.urdf.xacro` SHA-256은 JSON에 있다. 현행 저장소의 두 파일과 해시가 달라 감사에는 복사한 URDF·메시를 사용했다. 다만 해당 소스가 과거 로그 실행 당시의 빌드와 동일했다는 서명 기록은 없다.
- 재현: `python docs/validation/lane-bend-map-footprint-2026-10-10/evidence/audit.py --urdf-root X:/DevTemp/lane-bend-map-audit-20261010/old_repo X:/DevTemp/lane-bend-map-audit-20261010/runs_final_a X:/DevTemp/lane-bend-map-audit-20261010/runs`. Gazebo GT의 `junction_bending`·`junction_reacquiring` 시점에서 SIM URDF 충돌 형상의 2D convex hull을 1 mm STL 페인트 래스터에 올린다. 명령의 바퀴 궤적이나 카메라 예측 마스크로 몸체를 대체하지 않았다.

## 관측

| 실행 묶음 | 굽이 GT 샘플 | 페인트 접촉 샘플 | 최소 샘플 간격 | 최대 연속 샘플의 몸체 꼭짓점 이동 | 결과 |
| --- | ---: | ---: | ---: | ---: | --- |
| `runs_final_a` 남쪽 13회 | 783 | 0 | 1.4 mm | 11.18 mm | 원형 구간 도달 9회, LOST 4회 |
| `runs_final_a` 서쪽 10회 | 118 (2회만 진입) | 20 (2회 각 10) | 0 | 8.60 mm | 진입 2회 aborted, 나머지 8회 LOST |
| `runs` 남쪽 5회 | 301 | 0 | 2.20 mm | 10.30 mm | 원형 구간 도달 5회 |
| `runs` 서쪽 10회 | 0 | 해당 없음 | 해당 없음 | 해당 없음 | 모두 굽이 전 LOST |

첫 서쪽 접촉 후보(`west_01`)는 GT `[-0.6571, -0.4845, 0.4336]`, `sim_t=232.178`에서 몸체 hull이 페인트에 닿았다. 당시 로그는 `reason=junction_bending`, 전방 IR 3개 600 mm, `body_gap_m=0.1516`으로 기록한다. 따라서 장애물 통과 여유만으로 차선 페인트 여유를 보증할 수 없다는 반례다. [앞선 합성 급굽이 폐루프](../lane-keep-core-bend-loop-2026-10-10/result.md)의 몸체 접촉과 같은 종류의 취약점이며, 실제 지도 남쪽 경로에 그 합성 결과를 그대로 일반화하지 않는다.

## 판정과 다음 검증

샘플에서 접촉한 서쪽 두 실행은 차선 추종 성공으로 수용할 수 없다. 남쪽은 샘플 접촉이 없어도 최소 간격 1.4–2.20 mm보다 샘플 사이 이동이 최대 10–11 mm로 크다. 연속 궤적의 비접촉은 증명되지 않았다. STL의 흰 칠에는 차선 이외의 표식도 포함되므로, 접촉 화소를 승인된 물리 경계 ID나 차선 침범 정답으로 부르지 않는다([D-475](../../adr/D-475-human-reviewed-fixed-eval-truth.md)). 서쪽의 나중 실행은 굽이 자체에 들어가지 않아 안전한 주행 성공의 근거가 아니다.

차선 주행 목표의 다음 SIM 수용 조건은 같은 지도·URDF·제어 버전으로 서쪽과 남쪽 재실행, 1 mm 미만 오차의 연속 몸체 swept-envelope 검사, 선 소실/재획득과 STOP 원인 분리, 사람 검수 경계 ID와의 대조다. 기존 [D-507](../../adr/D-507-lane-trip-leg-structure-and-site-floor.md)의 CORE odom 굽이 소유와 [D-531](../../adr/D-531-route-context-to-lane-keeper.md)의 keeper 문맥 veto를 유지한다. 경계 정답이 없는 페인트 화소를 근거로 제어 권한이나 단일선 추종을 확대하지 않는다. 장치·현장 수용 근거는 아직 없다.
