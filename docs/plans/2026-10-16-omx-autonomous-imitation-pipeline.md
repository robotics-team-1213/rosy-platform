# OMX 자동 수집 모방학습 파이프라인 실행 계획

**Goal:** 에이전트가 제한된 OMX 실물 동작으로 실제 데이터를 모으고 모델 PC 학습·재적재까지 연결한다.

**Architecture:** [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 local owner·자동 교사·독립 outcome·데이터 계보를 따른다.
기존 실물 제어 G3–G6와 native reader/ACT를 재사용한다. 장치 초기화나 안전 owner를 새 수집 CLI 안에 숨기지 않는다.

**Tech Stack:** 기존 Python, LeRobot 0.4.4, ROSY OMX owner, native ROS와 user camera services.

## 제약

- 실물 구동은 실측 제한·독립 stop·실물 owner 수용 뒤에 수행한다. 현재 연결 존재는 이 조건의 충족이 아니다.
- Fleet PC에서 실행·수집, 모델 PC에서 학습·독립 평가. main 착지·push·Hub 전송은 이번 실행에 포함하지 않는다.
- source mode, 단위, 관측 시각, 실제 전달 명령과 cycle identity를 보존한다.
- 실제 시연 없이 합성 데이터·정지 관측을 모방학습 데이터셋 완료로 집계하지 않는다.

## 작업 1: 현장 상태와 우선순위 확정

- [x] 격리 브랜치 `feat/fleet-il-readiness`, ADR D-770 선점.
- [x] 인증 Tailscale SSH로 환경·장치·점유·기존 보정·장애 이력 진단.
- [x] 현재 카메라 두 개의 advancing frame·age 확인. 기존 producer 유지.
- [x] 장치 부재라는 오래된 문구와 현재 연결 관측을 분리.
- [x] 현재 실물 readiness와 읽기 전용 관절 관측 재확인; 원문은 private evidence에 보존.
- [x] 새로운 목표·실행 증거를 ADR/Log/logs에 기록하고 harness/문서 계약 검사.

회차 결과: 최초 회차는 원격 시험 결과를 확보하지 못했다. 후속에서 기존 AI PC를 통한
검증된 SSH ProxyJump로 현장/모델 PC 접속을 복구했다. 문서·기존 검토 119개 통과,
자동 출처·검토·학습 연결 45개 통과와 모델 PC 실제 LeRobot CPU 통합 1개 통과를 확인했다.
인증 URL·계정·호스트 주소는 공개 문서에 기록하지 않는다.

## 작업 2: 자동 구동 준비를 닫는다

기존 [실물 제어 G3–G6](2026-10-15-omx-hardware-control.md)가 정본이다.

- [ ] 기존 보정·레지스터를 보존하는 초기화 경로 검증. LeRobot connect의 configure 쓰기와 분리.
- [x] 설치 connect의 자동 torque 활성화와 실제 goal/profile/current/watchdog을 읽기 전용 확인. 수용된 초기화 구현은 미완료.
- [ ] 측정한 좁은 구간·workspace/기구 간섭·그리퍼·하중과 독립 stop을 확인.
- [ ] hardware owner의 실제 feedback/terminal/HOLD/timeout/재시작 readback 연결.
- [x] 기존 stream 두 영상과 실제 관절 관측 기록·재독출·모델 PC 원본 수신/hash 검증.
- [x] localhost 웹에서 최신 영상·관절 표시와 stale 제거를 실물 관측으로 확인.
- [ ] 실제 명령을 더해 영상-관절-명령 동기화를 측정; producer 중복 금지.
- [ ] 제한 자동 교사 단일 목표·상태 전이·중단·개입·독립 outcome에 RED→GREEN 및 독립 safety review.

실물 한계·stop 수용이 누락되면 해당 항목을 그대로 미완료로 둔다. 임의 숫자나 SIM 값으로 채우지 않는다.

## 작업 3: 수집·학습 자동화

- [ ] automatic teacher episode의 명령/실제 피드백/영상/terminal을 원자적 종료 기록에 묶는다.
- [x] 기존 `native_review.py`의 `leader_native` 고정 출처와 분리해 teacher revision·parent cycle을 검사한다.
- [ ] 실제 5회 시도 수집, reader 재독출, 영상·결과 검토. 실패도 별도 보존한다.
- [ ] 성공 시연 50/10/10 목표로 세션/cycle 독립 train/validation/final-test 확장; 부족하면 실제 수량 보고.
- [ ] 모델 PC로 immutable copy/hash 검증, ACT train-only 정규화·고정 config·로그·저장 모델/processor 재적재.
- [ ] 별도 실물 teacher/learner 비교. offline 오차와 실물 성공률을 따로 보고한다.

실물 observation-only 원본 수신은 완료했으나 명령을 포함한 시연 데이터 수신·학습은 미완료다. 해당 단계에서 사용할 `native_cycle.py`와 모델 PC 전용 환경은
구현했고, 합성 fixture로 실제 저장·세 분할·ACT·새 프로세스 재적재·eval까지 검증했다.
분할 중 원본 변경·학습 전 출처 재검사 회귀도 RED→GREEN으로 확인했다.

## 검증 및 현재 중단점

`git diff --check`, harness generate/lint, 원격 문서 계약 검사를 수행한다.
pytest는 노트북에서 실행하지 않는다. 접속은 복구했으며 SSH host verification을 유지한다.
작업대 조명은 밝은 영상으로 해소했다. 현재 남은 조건은 실물 구동/owner·보정·독립 정지 검증과 실제 명령 기록이다.

첫 실물 동작은 아직 실행하지 않았다. 작업 2의 미완료 조건은 자동 수집의 실제 선행 조건이며,
계획 작성이나 source 시험 통과로 해소되지 않는다.
