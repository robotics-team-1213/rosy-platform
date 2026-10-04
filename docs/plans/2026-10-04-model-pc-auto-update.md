# Model PC Code Auto Update Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-446의 서명 코드 후보 소비·유휴 전환·복귀와 작업 보호를 모델 PC에 설치하고 검증한다.

**Architecture:** 승인 커밋의 perception 코드를 별도 후보로 서명하여 inbox에 넣는다. 설치된 고정 업데이트기와 실행기는 하나의 작업 lock을 공유하며 current symlink만 바꾼다. 기존 checkout·venv·데이터·checkpoint·SSH 설정은 후보 밖에 유지한다.

**Tech Stack:** Python standard library, OpenSSL Ed25519, Linux flock, user systemd, 기존 candidate_signing.

---

### Task 1: ADR와 실패 시험

Create `docs/adr/D-446-model-pc-code-auto-update.md`, ADR Log 행, `test/test_model_pc_autoupdate.py`. 실제 임시 파일·서명 키로 signature/환경/downgrade/archive 경로 거절·작업 보류·원자 전환·복귀·재시작 복구 시험을 작성한다. `python -m pytest test/test_model_pc_autoupdate.py -q -p no:cacheprovider --basetemp X:/DevTemp/rosy-model-update/red`로 미구현 실패를 확인한다.

### Task 2: 후보·업데이트기·작업 실행기

Create `deploy/site/rosy_model_code.py`. build는 Git object만 archive하여 미커밋·ignored 비밀을 제외하고 manifest를 서명한다. run은 고정 공개 키와 환경 fingerprint, 안전 경로, sequence를 확인하고 busy/hold를 보류한다. pending 전환은 다음 run에서 복귀한다. exec는 공유 lock을 유지하고 고정 후보 source를 사용한다. status는 desired/observed/result를 출력한다. Task 1 시험으로 green과 중요한 guard mutation red를 확인한다.

### Task 3: 설치·운영·장비 검증

Create `deploy/site/install-model-code.sh`, updater/watch user service·timer와 `deploy/site/model-code-update.md`. 설치는 user 소유 독립 상태 디렉터리에 수행하며 기존 model-watch 설정을 보존한다. 운영자 PC에만 전용 키를 준비한다. 장비에서 분리된 scratch 시험 후 승인 코드 후보를 전달하여 source 전환과 user timer 상태를 readback한다. model-watch는 별도 설정과 doctor가 검증될 때만 시작한다. 부족한 수용 조건은 구체적으로 기록한다.

### Task 4: 통합

Append `deploy/logs.md`, `docs/logs.md`; run harness generate/lint, affected tests. 변경 파일만 commit한다. 새 main을 브랜치에 합쳐 필요한 시험 후 local main에 fast-forward한다. 동시 세션의 WIP/merge는 건드리지 않는다. push는 이 작업에서 수행하지 않는다.
