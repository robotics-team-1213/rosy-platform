---
module: fleet
tags: [cell, palletizing, operator-checkpoint, D-450]
---

# 작업자 슬립시트 삽입 확인

사용자 선택은 작업자가 슬립시트를 넣고 확인한 뒤 다음 층을 진행하는 방식이다. 기존 자동 집기 recipe/1의 뜻을 바꾸지 않고 별도 recipe revision에 수동 취급을 명시한다. 구현·시뮬레이션 수용을 진행하되 실물 접근 수용은 별도다.

## 계약과 책임

- PROCESS가 층 경계, 슬립시트 두께를 포함한 다음 층 높이, 팔레트와 요구 작업을 계산한다. 수동 sheet는 로봇 transfer Skill이나 grant로 만들지 않는다.
- 실행 PlanBundle에는 로봇 box transfer만 포함하고, 원래 Job에는 명시적 operator-sheet checkpoint를 남긴다. recipe/cell/process/Job 해시가 수동 취급과 각 checkpoint를 함께 묶는다.
- Fleet은 같은 SQLite Job·단계·원장의 checkpoint 상태를 소유한다. 새 실행 원장 또는 별도 자동 실행기를 만들지 않는다. 이전 층의 독립 목표 확인 뒤 다음 transfer를 READY로 만들기 전에 체크포인트에서 HOLD한다.
- 실행 owner가 미해결 명령·운전석·hold preload·정지 상태를 관측한다. Fleet의 문서나 operator 버튼만으로 장치 상태를 만들어 내지 않는다. 안전한 작업자 접근 조건을 판정할 owner 계약이 없으면 확인 경로는 닫힌다.
- named operator가 현재 Job/checkpoint/recipe/cell/정지 세대와 owner readback에 묶인 요청으로 삽입·접근 종료를 명시적으로 확인한다. service/viewer와 이전 확인 재사용을 거절한다. UI의 일반 HOLD 재승인 경로는 미확인 sheet checkpoint를 통과하지 못한다.

## 필요한 버전 변경

recipe/2에 수동 sheet handling을 추가하고 recipe/1 자동 형식은 유지한다. Job에는 `operator_sheet` 단계와 확정된 위치·층·팔레트·요구 두께를 포함한다. canonical 재컴파일에서 동일성을 확인하고 PlanBundle mapping은 checkpoint를 실행 grant로 변환하지 않는다.

checkpoint 확인용 요청·응답과 API Reference를 같은 변경에서 확정한다. 필수 항목은 Job/checkpoint identity, recipe/cell digests, 기대 stop generation, 실제 owner journal/session/readback sequence, 명시 확인과 request key다. 확인은 단순 satisfied boolean 또는 caller가 제공한 정지 주장으로 받아들이지 않는다. 실제 owner 관측을 서버가 확인한다.

## 구현 순서

1. recipe/2와 canonical Job/PlanBundle의 수동 checkpoint를 실패 테스트로 고정한다. 자동 sheet recipe는 기존 결과를 유지한다.
2. Fleet의 단계 전진·start·resume 경로를 같은 durable checkpoint guard에 묶는다. 완료 관측과 checkpoint 생성은 같은 트랜잭션에서 처리한다.
3. owner-local 접근/정지 readback 계약을 기존 local-stop 및 운전석 상호 배제와 대조한다. 안전한 접근을 증명하지 못하는 구성을 명시적으로 거절한다.
4. operator 확인 API와 Console 입력을 연결한다. 확인 전에는 다음 층 grant가 없음을 실제 UDS 수신으로 검증한다.
5. 현재 세대 정상 확인, 미리 온 확인, 잘못된 사용자·층·문서, stop 변경, 재시작, 응답 유실·중복 확인, 확인과 다음 하달 경합을 검사한다.
6. 모델 PC의 독립 관측으로 이전 박스·수동 sheet·다음 층 높이와 마지막 Job 목표를 확인한다. simulation aid와 실제 작업자 삽입 수용을 구분한다.

## 현재 상태

recipe/2와 canonical Job의 수동 checkpoint, box-only PlanBundle, Fleet durable 보류, 관제 대기 표시를 구현했다. PROCESS 소스 219 tests 및 설치 wheel 호환 169 tests, Fleet 보류 105 tests와 독립 48 tests, 읽기 전용 계약 19 tests를 검증했다. 기존 recipe/1을 유지하며 수동 간지 두께를 다음 층 높이에 반영한다. 관제의 일반 재승인은 간지 대기를 통과시키지 않는다.

owner-exclusive 작업자 접근 허용과 확인 API는 아직 연결하지 않았다. 따라서 실제 수동 작업은 `OPERATOR_SHEET_ACCESS_UNAVAILABLE`로 HOLD하며 작업자의 확인으로 다음 층을 재개하는 전체 경로·ROS-SIM·현장 수용은 NOT_RUN이다. 기존 박스 전용 G2 실행이나 draft 화면의 sheet 설정 해제를 수동 checkpoint 완료로 표시하지 않는다.
