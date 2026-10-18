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

- [ ] 기존 API 입력·출력과 session authority/renew 요구를 독립 검토로 확정한다.
- [ ] scope·clock·RTT·재정렬·expired renewal·network failure의 실패 시험을 먼저 커밋하고 원격 RED를 확인한다.
- [ ] 최소 HTTP client와 검증된 local lease cache를 구현한다. callback에는 network가 없다.
- [ ] 원격 GREEN 및 기존 session 회귀를 확인하고 독립 안전 리뷰를 받는다.

## 2. 명시적 SIM composition과 실제 Fleet 경계

Files: `middleware/robot_execution/local/src/rosy/execution/local/policy_chain.py`, `middleware/robot_execution/local/test/test_policy_chain.py`, 필요한 기존 CORE/LeRobot 안내.

- [ ] 실제 Fleet app/auth/SQLite 승인 창을 사용한 bootstrap·renewal·창 폐쇄·연결 단절 통합 시험을 먼저 작성해 원격 RED를 확인한다.
- [ ] trusted installation/identity/camera/fence/journal/runtime를 받는 기본 비활성 composition을 구현한다.
- [ ] 명시적 context 종료는 worker를 회수하고 session을 닫는다. 정지는 늦은 HTTP에 막히지 않는다.
- [ ] 원격 GREEN 및 affected selection, independent review를 확인한다.

## 3. 전체 vendor Gazebo 시험과 착지

Files: 소유 모듈 시험용 SIM probe, `docs/validation/omx-policy-chain-2026-10-19/result.md`, 관련 module logs/index.

- [ ] 실제 Fleet HTTP·장치 worker·CORE HTTP·실제 LeRobot subprocess·vendor ActionServer를 같은 execution에서 연결한다.
- [ ] camera source, command ID, native goal UUID, window/lease/episode, joint readback을 연계한 receipt를 기록한다.
- [ ] 이동 완료, lease 갱신, 이동 중 창 폐쇄→renew 거절→CANCELED/HOLD, 재연결 거절을 측정한다.
- [ ] teardown 문제도 보존하고 scope를 명확히 기록한다. 실물/학습 정확도/작업 성공은 별도다.
- [ ] committed revision의 원격 affected·native·browser 필요 검사를 비교해 NEW 0을 확인하고 `tools/land.py --tests auto`로 로컬 main에 착지한다.
