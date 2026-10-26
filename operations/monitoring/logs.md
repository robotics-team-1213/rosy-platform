# monitoring 작업 기록

## 2026-10-26 · uncommitted · 독립 관측 기반과 모듈 등록

- 변경: 관측 모델·범위·자격·시간 보존 캐시와 독립 wheel/CI를 먼저 만들고, 후속 서비스 구현 전에 `monitoring` 소유 모듈·실제 시험 경로·현재 blocker를 등록했다.
- 증거: `efdddebe30` 원격52시험이 통과했다. 원천 역순·누락/unknown·이름 변경·동일 capture 내용 변경의 RED와 수정, 설치 wheel의 Fleet/ROS 비의존성을 확인했다. 실제 서비스·UI·현장 수용은 포함하지 않는다.
- gate 변화: SOURCE/LOCAL/ARTIFACT/DEVICE/FIELD는 HOLD, ROS-SIM은 프로필상 N/A다. CE: 해당 없음 — 규칙을 코드·회귀·모듈 문서에 직접 고정했다.

## 2026-10-26 · uncommitted · 기존 원천 수집과 독립 읽기 API

- 변경: CORE viewer identity/diagnostics, Fleet 수동 캐시, 기존 host 보고 파일과 peer의 관측을 제한된 독립 수집 루프에 연결했다. API는 등록 reader의 사이트 범위만 조회한다. SQLite는 정규화 관측·수명 anchor·peer cursor를 게시 전에 저장하며, 원천이 없어도 7일/사이트4096건 이력을 유지한다. 단일 writer lease를 store 수명 동안 유지한다.
- 증거: `5a5355aa69` 원격89 PASS/0 SKIP, 구조·harness·affected247 PASS/0 SKIP, 두 비교 NEW/KNOWN/FLAKY0. 실제 HTTP 원천 종료, 수신 재시작·역순·동시 writer 거부·저장 실패·8192 durable 한도·JSON 깊이/자료형/UTF8·응답 aging·task 종료503을 검증했다. 최종 독립 재검토 차단 없음. 별도 프로세스/Windows lease·CLI·브라우저·native 설치·현장은 포함하지 않는다.
- gate 변화: 미완료 gate를 유지하고 blocker를 실제 남은 항목으로 갱신했다. CE: 해당 없음 — 원칙을 구현과 회귀에 직접 기록했으며 운영 장애 해결 기록이 아니다.

## 2026-10-26 · uncommitted · 독립 실행기와 프로세스 경계

- 변경: `rosy-monitoring` CLI를 wheel에 등록하고 loopback/단일 worker/비공개 state-dir를 고정했다. POSIX 권한을 보장할 수 없는 환경은 시작을 거부한다. Fleet 캐시 미구축과 실제 빈 목록을 구별하며, peer 수신의 로컬 저장·시계·재전송 거절을 Collector에 보존한다.
- 증거: `6b0f7568f5` 원격98 PASS/0 SKIP, 구조/harness/affected247 PASS/0 SKIP, 두 비교 NEW/KNOWN/FLAKY0. 실제 subprocess의 개별·peer 집계·중앙 직접 수집·중앙 종료 후 현장 지속·중복 writer 거부·재시작 수명 비증가와 private-state RED/수정을 확인했다. 최종 독립 재검토 차단 없음.
- gate 변화: SOURCE GO, LOCAL/ARTIFACT/DEVICE/FIELD HOLD. 화면·native/TLS 묶음·실제 PC 수용을 포함하지 않는다. CE: 해당 없음 — 새 실행 경계와 회귀에 직접 기록했다.

## 2026-10-26 · bc730ac631 · 후속 원천 시험의 초기화 훅 호환성

- 변경: service의 setup 이름 충돌 수정을 CLI 후보에도 반영하고 추가 Fleet 캐시 회귀의 호출도 source_context로 바꿨다. 제품 동작과 시험 조건은 유지한다.
- 증거: 원격 원천 어댑터22 PASS/0 SKIP, NEW/KNOWN/FLAKY0. service 수정과 함께 들어가면 새 nose 훅 검사에서 보조함수를 잘못 초기화하지 않는다.
- gate 변화: 없음. 공식 병합 전체 검증은 후속이며 장치·현장 수용을 올리지 않는다. CE 해당 없음 — 기존 검사·회귀가 해당 조건을 직접 설명한다.
