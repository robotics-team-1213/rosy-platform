# Site functional verification activation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 현장 Fleet/Vision 기능 검사와 실제 카메라 프레임 증거를 활성화하고 로봇 연결 문제를 확인한다.

**Architecture:** 기존 검증된 updater GET gate는 유지하고, 최소 권한 viewer provisioning과 복구 가능한 config-only 설치를 추가한다. 기존 enrollment/키는 보존하고 물리 인수와 API 검증을 구분한다.

**Tech Stack:** Python, systemd, Docker, HTTPS, Ed25519, pytest.

1. 기존 credential 파일 위치와 Fleet/카메라 실제 요청을 재확인한다. raw token과 lease는 출력하지 않는다.
2. 기능 검사 설정·viewer 사용자 추가·중단 복구를 작은 설치기로 준비하고 토큰 비노출/기존 사용자 보존/동시 수정 거부를 격리 시험한다.
3. 독립 코드 재검토 후 sudo 입력만 운영자 터미널에서 받아 적용한다. 기존 타이머·hold·등록·키를 보존한다.
4. 새 viewer로 두 GET 검사와 advancing JPEG 프레임을 실제 확인한다. robot online와 실제 안전 상태를 따로 기록한다.
5. 정적 roster 충돌과 응답 없는 로봇은 승인된 신원·주소와 실제 상태를 확인한 뒤 처리한다. 물리 환경 없이는 FIELD를 통과로 쓰지 않는다.
