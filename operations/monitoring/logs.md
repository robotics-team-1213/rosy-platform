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

## 2026-10-26 · uncommitted · 독립 앱 경계와 실제 backend 브라우저 경로 등록

- 변경: `applications/monitoring`의 소유·표면·상태/뷰포트 기준을 기록하고 source part·측정·browser scope·CI 실행 경로를 등록했다. 원격 Chromium은 실제 독립 backend의 인증·사이트 범위·이력 API를 읽으며 API를 가로채지 않는다.
- 증거: `1a9cd5b164` 실제 Chromium3 PASS/0 SKIP, 구조/harness/affected/browser-scope262 PASS/0 SKIP, 두 비교 NEW/KNOWN/FLAKY0. 화면 HTML/JS·G1/G2/G3는 아직 구현/수용하지 않았다.
- gate 변화: 없음. UI와 배포·DEVICE/FIELD HOLD를 유지한다. CE: 해당 없음 — 등록과 실제 경로 시험에 직접 기록했다.

## 2026-10-26 · 42404e6d6c · 독립 상태 화면과 실제 근거 검증

- 변경: canonical shell/control/theme/evidence 어휘로 scoped 항목·연결·이력 화면을 구현했다. 키는 메모리만 사용하며 epoch 격리와 자체 만료로 이전 로그인 응답·API 단절을 처리한다. prefixed common 자산도 Fleet와 독립이다.
- 증거: 실제 backend Chromium16+G1 원격151 PASS/0 SKIP, scope 거부 포함 상태 회차8e92f7f658 원격6 PASS/0 SKIP, 비교 NEW/KNOWN/FLAKY0. 40 PNG와 G3 차단 없음 검토를 docs/validation/uiux-surfaces-2026-10-26/monitoring에 보존했다. detector []이나 배포 common 해석 제한은 검증 기록에 명시했다.
- gate 변화: LOCAL GO. ARTIFACT/DEVICE/FIELD HOLD. CE 해당 없음 — 판단 근거는 코드·회귀·검증 기록에 직접 남는다.

## 2026-10-26 · 7a699b1e25 · 독립 native 배포 입력과 canonical UI 묶음

- 변경: 고정 allowlist의 새 UI 묶음 builder, 전용 사용자 systemd unit, 개별·peer집계·중앙직접 설정과 독립 TLS proxy 예시/운영 절차를 추가했다. 기존 출력 덮어쓰기와 누락 자산의 부분 게시를 거부한다.
- 증거: 원격 Monitoring104 PASS/0 SKIP, NEW/KNOWN/FLAKY0. 3프로필의 scope·분리 자격과 bundle byte 일치·기존 출력 보호를 검사했다. 읽기 전용 계약 검토 차단 없음. 실제 설치·활성화·대상 systemd 검사·LAN/TLS는 수행하지 않았다.
- gate 변화: SOURCE/LOCAL GO, ARTIFACT/DEVICE/FIELD HOLD. CE 해당 없음 — 경계와 한계는 코드·시험·배포 절차에 직접 남는다.
