# Fleet frontend development log

## 2026-10-21 · 7983f783c8 · D-830 independent frontend development

- 변경: Added sample/connected loopback host, explicit asset registry and native/sample browser providers. No new runtime dependencies, Fleet/ROS imports in sample, or physical command authority.
- 증거: Remote evidence: 18 feature browser fetch replays, Cell form flow and real Fleet HTTPS login/profile/task cancellation/logout integration: 20 passed. Eight entry documents, synthetic voice/video and prior focused state regressions also passed in scoped runs. These are frontend and temporary-ledger tests, not deployment/device acceptance.
- Backend receipts retain exact passing HTTP test IDs and source revisions. The initial broad capture had 6046 passed, 323 skipped and 3 failures; those failures were asset-test wiring and passed the later 50-case correction run. Refusal-only endpoints remain labeled as such in the matrix.
- gate 변화: Independent review found cancel-all wrongly latched dispatch and missing Cell overview rows. Added real button/list browser regressions; final correction verification is pending. LOCAL stays HOLD until combined verification passes.

## 2026-10-21 · 030df77030 · Review corrections and cross-screen state

- 변경: Corrected non-latching cancel-all response, shared Cell overview rows, initial Cell session/read ordering, formation stop fanout and pending task counts. Saved document reads wait for verified session role; the editor and explicit connection remain available.
- 증거: Remote cancellation/formation/task-count corrections: 21 passed. The earlier Cell session correction run had 59 passed and one incorrect test selector; the selector now uses the real row title and checks the selected detail ID/status. Final combined check remains pending.
- gate 변화: Evidence and six refusal-only backend HTTP qualifications: docs/validation/fleet-frontend-development-2026-10-21.md. No device/field gate changes.

## 2026-10-21 · c000a57004 · Cell approval and combined regression

- 변경: Cell sample now follows the existing two-person approval registry. Proposer self-admission is refused; reviewer login admits the same job. Actor ownership is passed through channel composition; overview reports the same approval rule.
- 증거: f5aab6d2de combined sample/browser/installed/CLI/architecture/real-Fleet-HTTPS regression: 264 passed, zero skips. Subsequent changed sample flows and all 18 representative browser replays plus Cell form/reviewer/terminal/overview: 36 passed at c000a57004. Stop/formation/queue coherence: 21 passed at 030df77030.
- gate 변화: LOCAL GO for frontend development verification. Operational deployment, ROS-SIM, device and field acceptance remain HOLD. Standard landing FULL pending. Required journal labels were corrected with exact normalized hash pairs in log_repairs.yaml; the recorded execution prose was preserved.

## 2026-10-21 · a7ef52c3aa · Development module guards and public fixture identity

- 변경: Registered development scripts with the existing size guard, added scoped module instructions and functional test ownership. Sample credentials use the explicit CHANGE_ME placeholder; account passwords have one state source. HTTP evidence stores test file/function separately, and public commit/compiler/journal digests have exact reviewed provenance bindings. The scanner itself is unchanged. Cell browser replay waits for reviewer navigation before reading the job.
- 증거: The first merged FULL snapshot b774a8b127 passed Fleet 6056 cases (323 skipped) and CORE/domain/shared contracts 7253 cases (64 skipped, 5 subtests). Root guards exposed the registration/provenance omissions, and the Cell browser exposed the navigation race. Corrections: 294 focused cases passed at 826bf356e2 with two remaining failures, then both were resolved; final repository secret/provenance checks plus real Cell form/reviewer/overview passed 98 cases at a7ef52c3aa with zero skips. Independent review confirmed all nine digest bindings are public lineage, not credential exceptions.
- gate 변화: Frontend LOCAL remains GO for scoped evidence. Standard FULL must run again on the corrected commit before landing. Timing load sensitivity, skipped checks and physical deployment/device/field acceptance remain separate.


## 2026-10-25 · uncommitted · D-862 독립·중첩 통합관제 합성 예제

- 변경: 기존 sample router에 R/A/A1/B overview/detail/map과 불변 정지 요청·GET 이력·명시 재시운전 확인을 연결했다. R만 기존 로봇·작업·지도를 소유하고 자식의 직접 자원은 빈 합성 예다. 기존 위임 로직을 유지한다.
- 증거: 기존 sample-unit fixture를 R로 함께 정렬했다. 실제 sample flow/browser 회귀는 구현 커밋의 원격 시험으로 확인한다. 이 예제는 네트워크·장치 수용 증거가 아니다.
- gate 변화: 새 기능의 SOURCE/원격 검증을 진행하며 배포·장치·FIELD 승격은 없다. CE 해당 없음 — 현재 판단은 ADR·소스·회귀에 남기고 검증 전 해결 교훈을 쓰지 않는다.

## 2026-10-25 · uncommitted · 합성 정지 예제도 관제별 stale 결과 보존

- 변경: 한 관제의 과거 fence로 전체 요청을 거절하던 sample을 관제별 STALE_FENCE와 최신 관제의 계속 처리로 정렬했다. 결과는 latch 소비 후 fence를 담고 HOLD 작업도 직접 소유 활성 건수에 포함한다.
- 증거: source10fc372212의 공식 원격 sample RED8건으로 전체409·소비 전 fence·HOLD 누락을 재현했다. 기존 assertion을 약하게 하는 대신 독립 관제 진행과 stale 관제 미변경·중복 미실행을 함께 검증한다. 수정 source의 GREEN은 다음 실행이다.
- gate 변화: 합성 예제의 계약 정합성 수정이며 실제 배포·네트워크·장치 수용이 아니다. CE 해당 없음 — 원인과 수용 조건이 해당 회귀·D862에 직접 남는다.
