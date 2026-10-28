# 업무 앱 실행 계약 구현계획

> **For agentic workers:** `superpowers:executing-plans`로 현재 세션에서 순차 구현한다. 사용자 승인 범위는 ADR·구현·시험이며 장치 활성화·배포·push는 제외한다.

**Goal:** 독립 앱의 공정 문서 소비와 Fleet 후보 배정, 근거에 따른 업무 완료를 연결한다.
**Architecture:** D-836 및 D-827~829. 공정은 기존 cell-app HTTP, 자원은 기존 TRIP lease/claim, 업무 판단은 독립 앱에 둔다.
**Tech Stack:** 현재 Python/Pydantic/FastAPI/SQLite, 앱은 표준 라이브러리. 새 runtime dependency 없음.
**Spec:** [D-836](../adr/D-836-application-process-and-candidate-admission.md).

## Global Constraints

- 기존 named operator·simulation profile·stop epoch·장치 owner·미확인 점유를 유지한다.
- 앱은 platform import·DB·ROS를 사용하지 않는다. 합성 근거를 물리 사실로 게시하지 않는다.
- 플랫폼 시험은 commit SHA의 원격 실행만 인정한다. 앱 표준 라이브러리 시험은 로컬에서 실행한다.
- 사용자가 이번 작업 한 개의 worktree 슬롯 예외를 승인했다. 완료 후 branch·시험 기록을 보존하고 회수한다.

## 작업 1: ADR와 공유 요청 계약

- [ ] 후보/단일 지정의 배타성, ID 형식·중복·개수, request key 검증 시험을 쓴다.
- [ ] 원격 RED 확인 후 foundation `protocol/trip_jobs.py`와 `schemas.py` export를 구현한다. 기존 TripJobStep/Request import는 route에서 재노출한다.
- [ ] API reference v1.292와 세 version pin, ADR index·logs/index를 갱신하고 계약 시험을 실행한다.

## 작업 2: Fleet 후보 배정과 재접수

- [ ] 기존 `test_job_trip_steps.Rig`와 route fixture를 재사용해 busy 후보·전체 busy·중복 key·본문 충돌·동시 요청·부분 확보 실패·정지·재시작을 먼저 시험한다.
- [ ] `trip_job_routes.py`, `job_trip_rows.py`, `job_trip_steps.py`에 기존 admission과 DB write transaction을 재사용한다. busy 이외 거절은 재시도하지 않는다.
- [ ] 선택된 robot은 기존 `{job}` 원장 응답으로 확인한다. 같은 key는 오래된 작업을 그대로 반환한다. source와 caller를 같은 커밋으로 검증한다.

## 작업 3: 독립 항만 앱의 첫 연결

- [ ] 앱의 세부 ADR/계획과 실패 시험을 먼저 작성한다.
- [ ] 이동별 문서 binding, 순차 공정 proposal HTTP 소비, 후보 요청과 불명 POST 복구, 업무 장부의 task/attempt·관측 근거 대조를 구현한다.
- [ ] 접수·action 성공만으로 다음 단계나 업무 완료가 생기지 않는 시험, 오래된 결과·중복·재시작·문서 변경·binding 누락 시험을 실행한다.
- [ ] 현재 설정의 역할은 장치 능력을 생성하지 않음을 유지한다. 실제 도달/공유구역/퇴피의 설치 검증을 가정하지 않는다.

## Review Focus

후보 접수 중 lease·stop 경합, 같은 key를 다른 principal/본문이 사용하는 경우, 재시작 뒤 재접수, HTTP timeout 후 무조건 재전송, 계획과 관측의 혼동, 출처·시도·revision이 다른 근거, 외부 앱의 숨은 platform 의존을 확인한다.

## 완료 증거

각 저장소의 커밋 SHA·원격 로그·실행/skip 수·known failure 비교와 독립 최종 검토를 기록한다. 실제 서버 소비와 합성 transport 시험을 구별한다. 기능 구현을 실물 수용으로 표시하지 않는다.
