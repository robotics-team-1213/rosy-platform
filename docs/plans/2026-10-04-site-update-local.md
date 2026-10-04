# Site Update Local Safety Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 로컬 수동 설치와 작업 중 변경을 보존하면서 검증된 자동 업데이트를 수행한다.

**Architecture:** 기존 root 설치 updater와 서명 PC의 AutoSigner를 확장한다. journal 복구, 보류, 현재 설치 검증, 기록 동기화, 후보 선택, 기능 검사 및 rollback 순서를 고정한다.

**Tech Stack:** Python, pytest, Docker Compose, systemd, GitHub Actions, Ed25519.

---

### Task 1: 실제 설치 기록 및 보류

Modify `deploy/site/rosy_site_autoupdate.py`, `deploy/site/site_update_io.py`; test `test/test_site_autoupdate.py`.
1. 수동 설치와 installed 기록 불일치, 보류 중 무변경, 보류 중 journal 복구 우선 시험을 작성하고 RED 확인.
2. 검증 후 기록 동기화 및 hold/resume CLI를 잠금 안에서 구현.
3. GREEN과 기존 전환·rollback·prune 회귀 확인.

### Task 2: 실행 설정 변경

Modify 동일 updater/I/O; test `test/test_site_autoupdate.py`.
1. 같은 이미지지만 Compose hash/readonly/privileged 불일치 시험 RED.
2. 실제 Docker inspect와 현재 Compose hash 비교; 변경 시 전환 거부.
3. GREEN; 표준 Compose와 pairing 설정도 검증.

### Task 3: 필수 CI 승인

Modify `deploy/site/auto_sign_candidates.py`; test `test/test_site_auto_sign.py`.
1. 실패·미완료·누락·다른 SHA·최신 재실행 실패·API 오류 후 재시도 시험 RED.
2. 정확한 main SHA의 ci.yml 실행과 ci-result 성공을 서명 직전에 요구.
3. GREEN; provenance/서명 기존 회귀 유지.

### Task 4: 기능 검사 및 운영 기록

Modify updater/I/O/`deploy/site/README.md`; test updater suite.
1. 기능 API 구조·필수 ID 실패 시 rollback, 토큰 출력 금지 시험 RED.
2. 별도 토큰 파일과 동일 HTTPS origin의 고정 GET API만 허용해 구현.
3. GREEN; Linux affected 및 pre-push gate, 독립 코드 재검토.
4. 배포 승인 범위 확인 후 정확한 후보 SHA의 CI·서명·실제 host readback을 구분해 기록. 운영 장애 주입은 수행하지 않는다.
