# 두 유한 trip의 차선 중간 정지 회귀 검증, 2026-10-10

**판정: SOURCE 통과, ROS-SIM·DEVICE·FIELD HOLD.** 앞선 [현장 읽기](../two-robot-one-lap-2026-10-10/result.md) 뒤에 발견한 실행 계약 불일치를 고친 후보에 대한 기록이다.

`map_v2_fleet`의 `W_mid`와 `E_mid`는 차선 끝이 아닌 이름 있는 정지 장소다. 계획기는 이 장소로 돌아가는 경로를 만들었지만 Fleet 실행기는 마지막 구간이 차선 끝에 닿지 않는다는 이유로 `TRIP_MODE_UNSUPPORTED / LANE_END_NOT_A_PLACE`를 반환했다. 처음 추가한 두 로봇 시험도 이 오류로 실패했다. 후보는 마지막 계획 action에 선택 장소 ID를 보존하고, 유한 trip에서만 그 장소에 `stop_after_m`을 보낸다. 기존 반복 lap은 차선 끝 장소 기준을 유지하며 좌표만 지정한 차선 중간 종료는 계속 거절한다(D-613).

| 실행 | 결과와 범위 |
|---|---|
| 원격 `operations/fleet/test/{test_lane_traffic,test_routing,test_trip_runner,test_site_map_trip}.py -q` | 코드 SHA `bacc3d8dd9`, 183개 통과. 두 로봇의 별도 유한 trip, 자기 출발 장소를 대상으로 한 `stop` 명령과 가짜 CORE의 `arrived`, 기존 반복 lap 회귀를 포함. `known_failures.py`: NEW 0, KNOWN 0 (`X:/DevTemp/one-lap-midstop-2/run-1.txt`) |
| 원격 `operations/fleet/test operations/situation/test test/architecture/test_document_placement.py test/architecture/test_folder_layout.py -q` | 코드·문서 SHA `fbf9991bb3`, 종료 코드 0. 실제 브라우저와 장치가 필요한 선택 시험은 skip. `known_failures.py`: NEW 0, KNOWN 0 (`X:/DevTemp/one-lap-broad/run-1.txt`) |
| `python tools/harness/rosy_harness.py lint` | 이 브랜치에 아직 없는 동료 선점 ADR D-610·D-611·D-612 때문에 3 errors. 이 변경의 로그·생성 문서 오류는 없음 |
| `python tools/remote/remote_pytest.py --pick sim` | 모델 PC의 가용 메모리 3.0 GB가 SIM 최소 8 GB보다 낮아 호스트를 고르지 못함. Gazebo 실행·합격 증거 없음 |

가짜 CORE의 `arrived`는 실제 바퀴 수, 차체 경계, 정지 거리, 영상 동기화를 증명하지 않는다. 현장 설치판은 이 후보를 포함하지 않았고 `rosy_40`의 회전 근거와 두 출발 위치도 해소되지 않았다. 다음 수용은 격리된 동시 Gazebo 재생, 설치 SHA·센서 근거 확인, 감독 아래 단일 로봇 주행, 마지막으로 두 로봇 동시 한 바퀴의 독립 계측 순서다.
