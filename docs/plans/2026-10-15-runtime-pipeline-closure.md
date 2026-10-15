# ROSY 전체 실행 흐름 연결 점검

사용자 요청: 미완성 파이프라인을 목록으로 정리하고 끊긴 연결을 처리한다.
브랜치: `fix/runtime-pipelines`. 조사 기준: `c6d52b238`.
계약: README 핵심 계약, D-2/D-38, D-678, D-732, D-752.

`STATUS.md`의 HOLD는 코드 누락과 검증 대기를 함께 포함한다. 이 목록은 현재
소스의 진입점과 결과 소비자를 따라 정리한 것이며, 모든 경로의 실행 통과표가 아니다.
예전 계획의 미구현 표시는 현재 소스와 대조해야 한다. 공유 main의 동시 변경은
이 브랜치의 수정이나 검증으로 계산하지 않는다.

## 경로 목록과 처리

| 번호 | 실행 흐름 | 현재 연결의 소스 근거 | 확인한 미완성/처리 상태 |
|---|---|---|---|
| 1 | 센서·카메라 → 차로 관측 → CORE | `middleware/perception/sensors/line_observation/line_observer_node.py`, `middleware/drive`, CORE bridge | 관측과 최종 writer는 연결돼 있다. 센서 보정·실제 그래프·정지 거리 증거는 별도다. legacy safety publisher를 함께 켜지 않는다. |
| 2 | 천장 관측·pin·odom → World → Fleet 자세 | `operations/world/src/rosy/world/state/projections/map_pose.py`, Fleet `map_pose_service.py` | 현재 자세 projection 연결은 존재한다. `bridged`는 dead reckoning이다. 행동 조건부 미래 World model은 별도 계획이며 임의 구현하지 않는다. |
| 3 | 인증 → Console·채널 접수 → 기명 요청 | Fleet `auth/`, `channel/gateway.py`, `channel/requests.py`, `app.py` | Gateway·요청 원장·설치 연결이 현재 존재한다. 과거 Discord 계획의 Gateway 미구현 문구를 현재 상태로 사용하지 않는다. 실제 수신·계정 회수·배포 수용은 이번에 검증하지 않았다. |
| 4 | 대화 → 후보 → 기존 intent → CORE | `channel/conversation/runtime.py`, `channel/execution/{runtime,worker}.py`, `app.py` | 명시적 설정과 admission으로 연결돼 있다. admission 만료·UNKNOWN은 새 전송 권한이 아니다. 실제 모델 의미 품질과 운영 승인 자료를 만들지 않는다. |
| 5 | navigation Task → native ACK → 이벤트/readback → 자원 해제 | `ledger/task_results.py`, `channel/execution/outcomes/{task_receipt,evidence,reconcile}.py`, `_task_dispatch_loop` | **수정:** 한 owner의 느린 조회가 다른 owner의 종결을 막는 순차 조회를, 기존 20건 한도 안에서 독립 조회로 바꾼다. 동일 boot/run/attempt·2초·quiescence·claim CAS를 유지한다. |
| 6 | Mission·Cell Job → Arm owner → Action 결과 → 목표 증거 | `ledger/mission_dispatcher.py`, `step_dispatcher.py`, `goal_evidence_service.py`, `app.py` | dispatcher와 목표 증거 callback은 연결돼 있다. Action 성공만으로 물리 목표를 완료하지 않는다. 실제 producer/신뢰 자료·물체 파지·장치 수용은 별도다. |
| 7 | 지도 경로 → trip·traffic·lease → CORE → 도착·다음 구간 | `ledger/trip_runner.py`, `traffic/lane_traffic.py`, `traffic/trip_lease.py` | 기존 경로 존재. 현장 지도·교통 설정과 다중 로봇/신호 수용 증거는 이번에 얻지 않았다. |
| 8 | formation → arm → relay → watch → hold/stop | `swarm/session.py`, `swarm/relay.py`, `app.py` | 기존 경로 존재. 참조 소실 HOLD와 최종 CORE writer를 유지한다. 실물 동시 주행은 미검증이다. |
| 9 | stuck·incident → law·rule/AI → admission → owner → 결과/인계 | `stuck/loop.py`, `incidents/automation/{runtime,execution/worker}.py` | 현재 lane recovery candidate와 명시적 `recovery_submit` 연결이 있다. 예전 '읽기만 처리' 기록으로 전체를 미구현이라 판단하지 않는다. door/arm 범용 backend와 자동 실패 분류·재훈련은 이 연결의 계약 밖 후속이다. |
| 10 | 실행 사건 → 피드백 export → 검수 → 후보 비교·registry | `test_incident_feedback_export.py`, `learning/registry/policy`, 기존 reasoning lifecycle 계획 | export·검수·registry 소스가 존재한다. 전체 관측/명령/청구 coverage, 독립 정답·한계, signed 운영 수용이 부족하면 비교/승격 HOLD다. 이를 합성 승인으로 메우지 않는다. |
| 11 | 영상 수집 → 검수 → dataset → train/eval → READY → intake·shadow | `learning/curation/perception`, `learning/training/perception/{review_pipeline,train_job}.py`, `learning/registry/perception/{watch,deliver}.py` | 명시적 owner context 연결이 있다. 실제 검수 mask·원본 픽셀/collection lineage·평가 자료는 별도 입력이다. shadow delivery는 주행 활성화가 아니다. |
| 12 | OMX 시연 → episode → LeRobot → ACT → replay/SIM | `learning/curation/omx`, `learning/training/omx`, 기존 OMX adapter | Gazebo Pilot 경로와 offline 학습은 존재한다. Isaac OMX controller/camera/task 연결은 기존 준비 계획에서도 미구현이다. 실물 driver나 임의 unit 변환으로 대체하지 않는다. |
| 13 | 빌드 → 서명 artifact → 설치 → 장치 readback | `deploy/robot/pinky_pro/{image,release,install-pi.sh}`, `deploy/site` | 소스 연결과 서명/배포/SD 부팅·장치 수용 증거를 구분한다. 이번 작업은 push·배포·runtime 활성화를 하지 않는다. |
| 14 | Fleet 시작 → 모든 background owner → 종료 | `app.py` lifespan 및 각 worker runtime | **수정:** 종료 시 이미 실패한 한 worker가 뒤의 worker 취소·회수를 중단하지 않도록 전체 취소 후 `gather(return_exceptions=True)`로 회수하고 실제 오류를 기록한다. |

## 구현 범위

5번·14번은 기존 계약을 집행하는 결함 수정이다. 새 command writer, 외부 API,
모델 권한, 서비스, 재시도 정책을 추가하지 않는다. 결과 조회의 병렬성만 바꾸며
SQLite 적용은 await 없는 기존 `BEGIN IMMEDIATE`/원장 재검증 안에서 수행한다.
조회 오류는 해당 Task의 UNKNOWN/점유를 유지한다. 종료 오류를 성공으로 숨기지
않고 로그에 남긴다. background 종료는 물리 정지 receipt가 아니다.

## 검증 기록

- 종료 회귀: `e4804ba77`에서 원격 RED. 실패한 trip worker를 await하다 종료가 중단됐다.
- 최초 readback 시험은 준비 코드가 두 번째 service 생성으로 startup fence를 닫아
  원하는 경계에 도달하지 못했다. 결함 재현 증거로 사용하지 않는다.
- 준비 수정 후 `b73b04577`에서 원격 RED: 선행 owner가 후행 owner를 기다리는 동안
  순차 조회가 timeout을 만들고 선행 Task가 `UNKNOWN`에 남았다.
- 원시 로그: X: 세션 `2026-10-15--042319--runtime-pipelines--0fd8e5/logs/`.
  각 pytest 결과는 `test/known_failures.py`로 판정한다.
- `0bc2a16c1`의 적격 AI PC 원격 GREEN: Task native outcome·channel native
  outcome·server app 3개 파일 117 passed, terminal exit 0, NEW 0.
- 독립 source 검토: critical/important 지적 없음. 조회 한도와 취소 전파,
  기존 CAS·identity·quiescence 보존 및 종료 오류 기록을 확인했다.
  취소를 무시하는 worker나 개별 `aclose()` 자체의 실패는 이 변경의 보장 밖이다.
- 영향 선택: 기준 `c6d52b238`, affected 57개 경로, FULL escalation 없음.
  중간 커밋 `fc7cd8aea` 원격 영향 시험은 6,278 passed, 330 skipped,
  3 failed, terminal exit 1이었다. 실패는 기록 heading 형식 2개 검사와
  outcomes 모듈 크기 판정 1개이며 기존 실패로 분류하지 않았다.
- 기록 형식과 한 줄 초과를 수정한 `30b06737a`에서 위 실패를 포함한
  기능·계약·구조 7개 파일을 다시 원격 검사했다. 273 passed, terminal
  exit 0, NEW 0. 허용 크기와 검사 기준은 바꾸지 않았다. 영향 전체를 최신
  SHA에서 다시 실행한 결과로 합산하지 않는다. skipped 330건은 미검증이다.
- local lint: exit 0, 오류 0개. last_verified drift 경고 29개는 gate
  승격의 근거가 아니며 기존 모듈 전체 검증으로 처리하지 않았다.

## 전체 완성을 막는 남은 입력과 증거

코드 존재와 운영 연결 완료는 다르다. 실제 검수/평가 자료, 운영 수용 receipt,
현장 overlay·설치 revision, 적격 시뮬레이션과 장치 readback이 있어야 1~13의
운영 완료를 판정할 수 있다. door/arm 범용 자동 개입과 Isaac OMX 학습 환경은
해당 실행 owner·입출력·성공 기준을 먼저 확정해야 한다. 이 작업은 미완성 항목을
숨기거나 PARKED/HOLD gate를 자동 해제하지 않는다. 사용자 지시 전 main 착지와
push를 하지 않는다.

## 사용자 승인 후 후속 · 2026-10-15

사용자가 로컬 병합과 나머지 작업의 계속 진행을 요청했다. 기존 브랜치의
착지는 `tools/land.py --tests auto`로 진행하며 push·운영 활성화 요청으로
확대하지 않는다. 후속 브랜치는 `fix/pipeline-resource-close`다.

- 14번의 추가 누락: async/sync close 실패가 나머지 정리를 막는 것을 원격
  RED 2건으로 확인했다. 기존 lifespan을 `AsyncExitStack`으로 연결해 worker
  회수 후 모든 close를 실행하고 오류를 보존한다. 관련 원격 281 passed,
  exit 0, NEW 0과 독립 검토로 확인했다. 상세는
  [후속 계획](2026-10-15-pipeline-resource-close.md)을 따른다.
- 12번의 실제 선행 조건: 비현장 후보 두 대를 읽기 전용으로 확인했다.
  한 대는 Docker daemon 접근 거절, 다른 한 대는 Docker 미설치였으며
  현재 확인한 기존 context로 live SIM을 실행할 수 없었다. 배치 검사에서도
  그 시점 sim 최소 가용 메모리를 충족하지 못했다. source-only를 SIM 통과로
  올리지 않았고 현장 PC를 대체 simulator로 사용하지 않았다.
- 10·11번은 검수·평가·독립 수용 자료를 임의로 채울 수 없다. 실제 입력을
  기존 owner에게 공급하고 readback해야 하는 관문으로 남긴다. 2·9·12번의
  미래 World/범용 door·arm/Isaac 학습 환경 확장은 기존 실행 연결 결함과
  구별하며 입출력과 성공 계약 확정 뒤 구현한다.
