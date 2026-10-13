# Learning center owner controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 학습 관리 센터에서 구성된 소유 pipeline의 시작·중지·재시도를 버튼과 키보드로 실행하고 직접 readback한다.

**Architecture:** 기존 검수 서버 인증과 signed ReviewPipeline 실행기를 사용한다. private binding으로 같은 workspace/서비스/config/out만 연결하고 generic report 링크에는 제어 권한을 주지 않는다. systemd 상태를 실제로 읽고 학습 수용·시도 한도·품질 거절은 유지한다.

**Tech Stack:** 기존 Python 표준 라이브러리, SQLite/HTTP, 사용자 systemd, 공용 ui-button, 원격 pytest/Chromium, 기존 모델 PC GPU 환경.

### Task 1: 계약과 제어 경계

- learning/curation/perception/learning_control.py와 test/learning/perception/test_learning_control.py.
- 먼저 private binding, workspace/argv/unit 변조, 상태 version, start/stop/retry, terminal budget 보호 시험을 작성·커밋하고 원격 RED를 확인한다.
- 고정 systemctl argv만 사용한다. source/config/unit 바이트를 재검사하고 요청 뒤 실제 상태를 읽는다. OS 프로세스 kill이나 arbitrary CLI 입력을 만들지 않는다.

### Task 2: 서버와 UI

- review_app.py, learning_workspace.py, review_app_web/learning.js 및 learning.html, install_review_release.py, 해당 HTTP/browser/release 시험.
- 기존 인증 뒤에 제어 요청을 배선한다. 없으면 기존 결과 링크 동작을 유지한다. optional control binding을 설치 unit에 전달한다.
- 구성된 결과 카드에 3개 버튼, 상태, 비활성 이유를 표시한다. Ctrl+K/Enter로 제어하고 실제 상태를 재조회한다. 화면 reader와 작은 화면 검증을 포함한다.

### Task 3: 운영 및 실제 시험

- 서명 후보와 기존 DB 백업/결정 비교로 갱신한다. private control binding을 현재 운영 workspace와 unit에 고정한다.
- 운영 승인 0장에서 시작·중지·재확인을 직접 UI로 확인하고 auto timer를 원래 켜진 상태로 마친다. 다른 GPU/Isaac 작업을 중지하지 않는다.
- 별도 unit 및 synthetic 자료에서 실제 signed GPU 실행 중지, 잠금 반환, 시도 한도 안 재시도와 READY/중복 차단을 검증한다.
- 모든 pytest는 committed HEAD 원격 runner로 실행하고 known_failures를 비교한다. 로컬 main 착지와 runtime, push/CI, 실제 정답 품질을 구분한다.
