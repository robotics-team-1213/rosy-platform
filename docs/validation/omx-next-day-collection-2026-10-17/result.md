# OMX 다음 날 실물 수집을 위한 연결 검증

2026-10-17, D-770 후속. 내일 실물 시험을 한다는 사용자 요청에 따라 오늘은 장치 구동 없이
수집·원본·전송·검토·학습 경로를 준비했다. 전체 제품 소스 고정 커밋은 `b88eee5f18`이다.
실제 시연0회, powered stop·실측 범위·집게/작업공간 수용·실데이터 학습은 미완료다.

## 구현과 경계

Fleet collector는 기존 ROS Action owner만 사용한다. 독립 supervisor가 환경·원본 시각·단독 publisher·
controller/watchdog 생존·acceptance 만료·세션 deadline을 감시한다. 오류 때 HOLD/cancel을 요청하고
미완료 원본을 보존한다. 직렬 버스 열기, torque ON, 기존 controller 시작, 자동 복귀는 수행하지 않는다.
허용되는 새 영상 쌍만 저장하며 실제 controller reference·관절 관측·RGB 원본·요청 목표를 구분한다.
목표 수용·native 결과·종료 이벤트와 원본 환경·profile/teacher/acceptance를 함께 보존한다.

intake는 hardware/CLOSED, 모든 파일 hash, teacher hash, 단계별 native 수용/결과,
ABORT 부재와 owner 종료 사실을 다시 검사한다. complete flag 수정만으로 중단 기록을 채택할 수 없다.
실제 LeRobot reader와5개 int64 원본 시각 feature를 사용하며 시간축을 복제/보간하지 않는다.
pipeline은 사람 검토와 독립 session/cycle 분할 뒤 기존 ACT 학습·별도 재적재로 연결한다.
unknown/exclude 기본 판정으로는 학습을 시작하지 않는다. 물체 과제 성공은 사람이 판정한다.

## 커밋에 결합한 원격 검사

노트북 pytest는 실행하지 않았다. `tools/remote/remote_pytest.py`로 커밋된 소스를 시험했다.

| 소스 | 범위 | 결과 |
|---|---|---|
| `b88eee5f18` | `test/test_omx_collection_ros.py`, `test/test_omx_collection_session.py`, `test/test_omx_collection_deployment.py` | 28 passed |
| `595016f52e` | intake·pipeline·전송 및 실제 LeRobot 왕복 통합 묶음 | 48 passed, 1 skipped |

둘째 묶음의 기본 runner interpreter에서는 선택적 LeRobot 직접 import 검사1개가 skip됐다.
실제 분리된 LeRobot0.4.4 interpreter를 지정한 왕복 검사는 통과했다. RawCollection journal을 만든
**합성 fixture**로 strict intake → 실제 reader/writer → 독립 train/eval/test → ACT2step →
별도 process model/preprocessor/postprocessor 재적재를 실행했다. 성공한 로봇 시연의 증거가 아니다.
다섯 int64 시각 feature와 capture ns 보존도 확인했다. 최초 timestamp 시험이 scalar shape 가정으로
실패한 기록을 보존했고, 실제 parquet int64 scalar를 확인한 뒤 assertion을 수정해 재실행했다.

원격 로그는 외부 scratch `rosy-il-python312/collection-final-source/run-1.txt`와
`omx-closed-chain-green-2/run-1.txt`에 보존했다. `test/known_failures.py` 비교는 NEW0/known0/flaky0.
독립 계약 리뷰는 acceptance 만료, 종료 event drain, 동일 Action lock, deadline,
중단 기록 승격, native terminal 뒤 owner READY 전환을 수정한 최종 소스에서 material finding0건이었다.
리뷰와 소프트웨어 검사는 물리 정지·하중·clearance 수용을 대신하지 않는다.

## 실제 Fleet·모델 PC 소프트웨어 배치

`git archive b88eee5f18`에서 OMX deploy·adapter·foundation/learning 계약·curation/training 경로를
선별해 두 PC의 `~/rosy-test/omx-collection-b88eee5f18/`에 새로 배치했다.
Archive SHA-256: `9fdc031d15aec03887117d39a9928afaff9b19f076d6aa45669a70443d4bd783`.
각 PC의 `source.json`은293개 원본 파일 hash를 기록하며 모의 실행 뒤에도 전부 일치했다.

| 실제 호스트 역할 | 확인한 결과 |
|---|---|
| Fleet PC | 모의6개 pass, hardware connections0, 실제 ROS/owner/DynamixelState import pass, disabled profile check 거부, collection unit inactive |
| 모델 PC | 모의6개 pass, hardware connections0, 실제 LeRobot0.4.4/pipeline import pass, `model-il` 진입점 배치 |

모의 시나리오는 정상·암실·센서 단절·reference 만료·owner 거절·terminal 실패다.
각 PC의 `staging-receipt.json`, `rehearsal/rehearsal.json`, import stdout/stderr를 보존했다.
Fleet private profile/teacher/acceptance는 비활성 예시이며 측정값을 꾸며 채우지 않았다.
기존 카메라 서비스는 변경하지 않았다. ROS node/backend 생성·직렬 연결·모터 목표 발행은0개다.
배치는 user unit 설치와 daemon-reload까지만 수행했으며 enable/start하지 않았다.

실제 전송과 같은 strict SSH/scp-3 옵션으로52byte `transport-probe.json`을 Fleet에서 모델 PC로
복사하고 수신 hash 일치를 확인했다.
Probe SHA-256: `bf38510d1a3c38e8511665955ef3684c6f2bb7ca3f9fc8304b48211ba53b47e9`.
이 시험 파일은 collection 루트 밖에 있으며 실제 collection 전송/reader 검증으로 집계하지 않는다.
전송 도구의 원본/수신 hash·containment·새 destination·변경 감지 검사는 원격 단위 시험으로 확인했다.

## 내일 진행할 작업

[실행 절차](../../plans/2026-10-17-omx-next-day-collection.md)에 실측 입력·기존 controller/watchdog
준비·check/preflight·첫1회 수집·새 session 반복·검증 전송·사람 판정·학습 명령을 연결했다.
실제 관절/집게 제한과 normalization, 시야·작업공간·하중·powered stop을 확인하고 private 설정과
유효한 acceptance를 채워야 한다. 조도 저하·과노출·source 만료 때는 중단하며 자동 재개하지 않는다.
실물 시연/환경별 성공률/실데이터 학습/학습 정책의 물리 실행은 오늘 검증 범위 밖이다.
