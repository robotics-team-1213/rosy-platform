# Review pipeline connection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 검수 앱의 현재 결정과 봉인 자료를 기존 ReviewPipeline에 연결하고 운영 설치·격리 전체 경로를 검증한다.

**Architecture:** D-464의 기존 owner admission을 재사용한다. 사설 검수 화면과 별도로 loopback의 읽기 전용 결정 조회를 제공하고 같은 PC의 원자적 전달에서 기존 highwater와 TTL을 보존한다. 승인·출처·평가 검증과 서명된 운영 코드 조건은 우회하지 않는다.

**Tech Stack:** 기존 Python HTTP/SQLite, 표준 라이브러리, 사용자 systemd, 원격 pytest와 기존 GPU 환경.

### Task 1: 로컬 결정 조회와 전달

Files: review_app.py, review_bridge.py, install_review_release.py; 해당 기존 테스트.

1. loopback 결정 조회의 GET/Host 검사 및 쓰기 거절 시험, local transport의 실제 봉인 전송·중복·변조·경로 링크 거절 시험을 먼저 추가한다.
2. 커밋된 HEAD를 원격 pytest로 실행하고 NEW 실패를 확인한다.
3. 기존 snapshot/verify_bundle/bridge 기록을 재사용해 구현하고 같은 시험을 다시 실행한다.

### Task 2: 실행과 출처 표시

Files: deploy/model_pc의 사용자 서비스 템플릿/안내, pixel_label_job.py와 기존 시험.

1. 기존 ReviewPipeline CLI를 호출하는 서비스와 기존 bridge CLI를 호출하는 서비스를 작성한다. private config/state는 릴리스 밖에 둔다.
2. AI 초안의 model revision/receipt 출처를 annotation_source/note로 전달한다.
3. 원격 회귀와 syntax/lint를 확인한다. 운영 갱신은 D-446/D-561의 서명 후보와 이전 릴리스 복구 경로를 사용한다.

### Task 3: 전체 실행 검증

1. 검수 대기 실제 자료에서 source → current 전달 → 봉인 → owner HOLD와 UI 결과 연결을 확인한다.
2. 격리 승인 fixture는 실제 데이터 품질 수용과 구분한다. 기존 builder/IndexedReview/실제 trainer 경계, 중복 실행·철회·TTL·평가 중복 차단을 검증한다.
3. 실제 사람 승인·독립 평가·서명 키가 없는 단계는 성공으로 기록하지 않는다. 요청한 자료가 오면 실제 수용 경로를 이어 실행한다.

소스는 task worktree에서만 변경한다. X:의 이번 세션에 로그·스크린샷·개인 설정·후보를 둔다. 주행·모델 승격은 범위 밖이다.
