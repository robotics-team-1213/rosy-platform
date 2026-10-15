# Pipeline resource cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fleet 종료에서 worker와 개별 리소스 정리를 끝내고, 종료 오류를 호출자에게 보존한다.

**Architecture:** 기존 lifespan·worker·resource 소유권을 유지한다. 표준 라이브러리
`AsyncExitStack`으로 모든 close callback을 등록한 뒤 worker를 취소·회수하고,
리소스를 닫는다. 하나의 close가 실패해도 나머지 callback을 실행한다.

**Tech Stack:** Python asyncio/contextlib, 기존 FastAPI lifespan, 원격 pytest.

## Task 1: 실패 재현

- 수정/시험: `operations/fleet/test/test_server_app.py`.
- power display의 async close와 start-points의 sync close 실패를 각각 주입한다.
  worker 종료가 먼저 확인되고, 두 리소스 모두 close되며, 오류가 호출자에게
  전달돼야 한다. FakeRobot만 쓰고 모델·장치 명령을 보내지 않는다.
- 시험만 커밋한 HEAD를 원격 실행하고 known_failures로 RED를 확인한다.

## Task 2: 기존 lifespan 수정

- 수정: `operations/fleet/fleet/server/app.py`.
- power display, notification HTTP client, calibration drift reader,
  post-action source와 start-points의 기존 close callback을 등록한다.
- 모든 background worker의 취소·회수 후 callback을 실행한다.
  기존 worker 오류 로그와 close 오류 전파를 보존한다. 기본 admission이나
  장치 stop·E-stop을 바꾸지 않는다. 새 dependency와 크기 예산 증액은 없다.
- 커밋 HEAD에서 server app·native outcome·harness·구조 회귀를 원격 실행한다.

## Task 3: 잔여 파이프라인 확인과 착지

- 기존 14개 경로 목록에 후속 결과와 실제 SIM 선행 조건을 기록한다.
- 현재 비현장 후보 두 호스트의 Docker/Compose 읽기 요청은 성공하지 않았다.
  동시에 sim 배치의 가용 메모리 기준을 만족하는 호스트도 없었다. 원시
  읽기 전용 결과는 앞 세션 `runtime-pipelines--0fd8e5/evidence/sim-prerequisites.json`이다.
  Docker 설치/접근 준비와 적격 자원을 확인하기 전 live OMX SIM은 미검증이다.
- 검수·운영 승인을 합성하지 않고 모델/물리 동작을 활성화하지 않는다.
  사용자 승인된 로컬 착지는 `python tools/land.py --tests auto`로 처리한다.
  push는 요청되지 않았다.
