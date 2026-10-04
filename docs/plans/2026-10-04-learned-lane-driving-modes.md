# Learned lane driving modes implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 운전 모드와 차선 인식 방식을 화면에서 구분해 선택하고, 기존 학습 마스크 차로 유지 경로를 실제 기기에서 확인한다.

**Architecture:** 기존 수동·차선 보조 자율·지도 목표 경로와 CORE 최종 명령 권한을 유지한다. 차선 인식은 threshold / denoise / learned 선택이며 learned 실패·지연은 D-408 denoise 예비로 떨어진다. 설정 변경은 인증된 CORE API → 제한된 Host Agent 명령 → 기기별 observer overlay이며 정지 상태에서만 적용한다.

**Tech Stack:** ROS 2 Jazzy, FastAPI, native Host Agent, static Pilot/dashboard, ONNX Runtime.

## Task 1: Persistent observer selection

Files: `control/ir_overlay.py`, `control/line_observer_overrides.py`, their sensing tests.

1. 기존 설정 도구의 학습 paint 선택 부재를 실패 시험으로 재현한다.
2. keep 모드·절대 모델 pointer·제한된 cadence/thread 값만 허용한다.
3. 기존 기본 설정을 유지하고 학습/denoise/threshold CLI 선택을 추가한다.
4. 기존 overlay와 mask freshness/회전/실패 예비 시험을 실행한다.

## Task 2: Device configuration API

Files: native Host Agent dispatch/commands, new narrow lane configuration subject, CORE line-follow router, related tests and API/Host Agent references.

1. `GET/PUT /api/v1/line-follow/perception`을 명시적으로 계약에 등록한다.
2. GET은 viewer, PUT은 administrator. PUT 본문은 `paint_source` enum만 받는다.
3. Host Agent는 정지·fresh velocity·차선 OFF·내비/도킹/보정 비활성 상태를 자체 재검사한다. 임의 경로·shell을 요청받지 않는다.
4. 기존 기기 geometry 설정을 보존하고 모델 부재·손상 거부, 원자 저장, 적용 실패 복구를 시험한다.
5. 사용자 운전 모드를 켜지 않으며 카메라만 재시작한다. 성공 응답은 적용 readback과 설정값을 구분한다.

## Task 3: Screen selection

Files: existing Pilot drive screen/modules and appropriate dashboard operation panel, their tests.

1. 수동/차선 자동을 명시적으로 구분하고 목표 지점은 기존 지도 화면으로 연결한다. 지도 능력이 없는 기기에서는 이유를 표시한다.
2. 차선 인식 selector는 학습 모델/OpenCV 반사 제거/기존 검출. 권한·정지 조건과 적용 상태를 표시한다.
3. 설정 변경 중 진행을 막고 실패 응답을 선택 성공으로 표시하지 않는다.
4. 운전자 hold·수동 takeover·hidden release를 유지하고 브라우저 회귀 시험을 실행한다.

## Task 4: Release and device readback

1. source 관련 시험과 quick tier 및 필요한 full suite를 실행한다.
2. 서명 ARM64 payload로 전달하고 runtime/parameter readback을 남긴다. 기존 서명 release를 직접 수정하지 않는다.
3. 실카메라에서 모델 latency, 실제 paint 출처, 차로 목표, 예비 비율, CORE/IO health를 측정한다.
4. 첫 대상은 차선 없음이 재현된 기기 한 대. 실제 주행은 운전자가 진행을 누르는 기존 보조 자율 경로다. 아직 움직이지 않은 상태를 실제 주행 성공으로 표시하지 않는다.
