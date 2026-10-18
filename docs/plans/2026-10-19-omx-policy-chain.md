# OMX SIM policy chain implementation plan

> 실행: `superpowers:executing-plans`로 현재 세션에서 순서대로 구현한다. 독립 계약 검토는 기존 `core_arm_review`를 재사용한다.

**Goal:** Fleet 승인 lease부터 CORE·LeRobot·Gazebo 이동과 철회 정지까지 동일 SIM 실행에서 연결한다.

**Architecture:** 기존 Fleet governance HTTP 계약을 장치의 선택적 consumer가 읽고, 기존 installed SIM session·watchdog와 CORE arm port에 결속한다. ROS callback에서 network를 호출하지 않고 기존 admission·HOLD·stop fence를 보존한다.

**Tech Stack:** 기존 Python 표준 라이브러리, FastAPI/uvicorn, ROS 2 Jazzy, LeRobot 0.4.4, vendor Gazebo.

**Spec:** [설계](2026-10-19-omx-policy-chain-design.md).

## 공통 제한과 검토 초점

- 기본 비활성·SIM 전용. 학습 checkpoint 부재를 고정 목표로 숨기지 않는다.
- Fleet window/revision/rig/calibration 및 local AttemptIdentity/owner/installed digest 경계는 별개로 검증한다.
- RTT를 차감하고 기존 최대 lease 1초를 늘리지 않는다. expired renewal과 지연 응답은 HOLD를 해제할 수 없다.
- 네트워크 failure는 기존 ROS watchdog과 별도로 fail closed이며, stop은 network worker lock을 기다리지 않는다.
- pytest는 원격 committed SHA, Gazebo는 remote_sim, 실물 활성화·push는 하지 않는다.

## 1. 장치 lease consumer

Files: `middleware/robot_execution/local/src/rosy/execution/local/policy_lease.py`, `middleware/robot_execution/local/test/test_policy_lease.py`.

- [x] 기존 API 입력·출력과 session authority/renew 요구를 독립 검토로 확정한다.
- [x] scope·clock·RTT·재정렬·expired renewal·network failure의 실패 시험을 먼저 커밋하고 원격 RED를 확인한다.
- [x] 최소 HTTP client와 검증된 local lease cache를 구현한다. callback에는 network가 없다.
- [x] 원격 GREEN 및 기존 session 회귀를 확인하고 독립 안전 리뷰를 받는다.

## 2. 명시적 SIM composition과 실제 Fleet 경계

Files: `middleware/robot_execution/local/src/rosy/execution/local/policy_chain.py`, `middleware/robot_execution/local/test/test_policy_chain.py`, 필요한 기존 CORE/LeRobot 안내.

- [x] 실제 Fleet app/auth/SQLite 승인 창을 사용한 bootstrap·renewal·창 폐쇄·연결 단절 통합 시험을 먼저 작성해 원격 RED를 확인한다.
- [x] trusted installation/identity/camera/fence/journal/runtime를 받는 기본 비활성 composition을 구현한다.
- [x] 명시적 context 종료는 worker를 회수하고 session을 닫는다. 정지는 늦은 HTTP에 막히지 않는다.
- [x] 원격 GREEN과 independent review를 확인한다. 착지 affected selection은 최종 단계에서 수행한다.

## 3. 전체 vendor Gazebo 시험과 착지

Files: 소유 모듈 시험용 SIM probe, `docs/validation/omx-policy-chain-2026-10-19/result.md`, 관련 module logs/index.

- [x] 실제 Fleet HTTP·장치 worker·CORE HTTP·실제 LeRobot subprocess·vendor ActionServer를 같은 execution에서 연결한다.
- [x] camera source, command ID, native goal UUID, window/lease/episode, joint readback을 연계한 receipt를 기록한다.
- [x] 이동 완료, lease 갱신, 이동 중 창 폐쇄→renew 거절→CANCELED/HOLD, 재연결 거절을 측정한다.
- [x] teardown 문제도 보존하고 scope를 명확히 기록한다. 실물/학습 정확도/작업 성공은 별도다.
- 최종 착지는 committed revision의 원격 affected·native·browser 필요 검사와 NEW 0을 확인하는 `tools/land.py --tests auto`로 수행한다. 해당 runner의 완료 출력과 git main 포함 여부를 착지 결과의 정본으로 사용한다.

## 실행 기록

- Ruling: 생성 상수와 비공개 anchor를 포함한 safety manifest 분류는 별도 `refactor/omx-policy-safety`로 먼저 착지한다. 제품 source에 분류를 빠뜨리거나 FULL을 축소하지 않기 위한 분리다.
- Ruling: 제품 변경은 15개 파일을 넘지만, 단일 OMX 관측·권한·실행 경로와 그 호출자·시험·증거가 한 단위다. 공유 safety manifest는 별도 착지했고, 카메라 pin 계약의 CORE·ROS·SIM 호출자 수정을 따로 착지하면 중간 상태가 깨지므로 함께 유지한다.
- Ruling: 실제 checkpoint가 없어 사용자 선택대로 고정 SIM 정책을 사용한다. 훈련·학습 정확도와 물리 구동은 검증하지 않는다.
- 소비기 첫 RED는 module 부재, 후속 리뷰 RED는 만료/미래 응답·proxy·발급 후 차단 근거에 대해 5 failed/23 passed였다. 수정 뒤 28 passed.
- 실제 Fleet 통합과 기존 session/runtime 회귀는 commit `e622829278`에서 134 passed. 관리자와 운영자의 권한을 분리했고, 실행 전 승인 준비의 HTTP deadline은 실행 중 장치 lease budget과 구분했다. 장치 runtime의 0.2s 전송·1s lease·기존 freshness는 유지했다.
- Ruling: 초기 소비기 source commit에 Safety-Review trailer가 없으므로 원래 branch를 보존하고 `feat/omx-policy-chain-reviewed`에서 RED 시험과 최종 리뷰된 소비기 source를 손실 없이 다시 커밋했다. 중간의 검토 전 구현은 착지 이력에 넣지 않는다. 재구성 완료 tree는 commit `28cb02e233`과 동일했다.
- commit `39a42e94d5`에서 drip HTTP deadline 회귀는 실패를 재현했다. 같은 실행의 카메라 시험은 잘못된 calibration digest로 실패했으므로 source-age RED의 증거로 사용하지 않는다. digest와 시험 source path를 수정했다.
- commit `87abee0f43`에서 원격 136 passed, known-failures NEW 0. 실제 HTTP body drip의 전체 교환 timeout, 환경 proxy 차단, 실제 Camera 클래스의 source-age 차감과 기존 Fleet/session/runtime 회귀를 포함한다. 독립 소스 리뷰는 통과했으며 Gazebo 결과는 별도로 기록한다.
- 실제 owner_clock_jumped_back을 계측하고 역행하는 source-age 관측을 입력에서 거부한 뒤 원격 215 passed. 이어 실제 403의 lease 만료를 HTTP 교환 시각으로 확인하고, 남은 예산 기반 갱신과 stdlib `-S` 교환으로 수정했다. commit `c7792975d0`에서 217 passed. 만료된 old authority를 새 응답으로 연결하지 않는 회귀도 포함한다.
- Ruling: 실제 stdlib 적재 0.0759초, 준비된 Fleet 조회 0.0297초로 매 요청의 프로세스 시작 비용이 확인됐다. lease 전에 명시적 POSIX context에서 helper를 준비하고, 각 요청은 기존 0.2초 절대 기한으로 교환한다. 준비 2초는 HTTP·lease 예산에 합치지 않는다. consumer authority 폐쇄는 메모리에서 즉시 수행하고 helper 회수는 소유 context가 담당한다.
