# 군집 수명주기 의미 보존 추출 검증

`refactor/swarm-reference-stream`의 소비자 보호 구현 전 준비 변경이다. D-870의 시간 수용이나 새 신선도 동작을 구현한 증거는 아니다.

- CORE 기준 `b29f3ff855`: 기존 7개 suite 원격 137개 통과. 추출 `77826ac7e1`: 같은 suite와 경계 변이 검증 2개를 합쳐 139개 통과, skip0/NEW0.
- Fleet 기준 `77826ac7e1`: session/arming/relay/anchor 관련 원격 108개 통과. 추출 `4ed200d0ee`: 같은 범위와 motion capability 회귀를 합쳐 123개 통과, skip0/NEW0.
- 외부 로그 root: `%LOCALAPPDATA%/Temp/rosy-swarm-freshness/`. 하위 `extraction-baseline`, `extraction-green`, `fleet-extraction-baseline`, `fleet-extraction-green`의 `run-1.txt`를 보존했다. pytest는 노트북에서 실행하지 않았다.

SwarmManager의 네 메서드는 같은 패키지의 SwarmReferenceStream으로 원문을 보존해 옮겼다. manager는 691→561줄이고 기존 상수 export·잠금·세션 검사를 유지한다. 전송 경계 검사는 두 파일을 읽으며, socket/rclpy import를 읽기 경로에 주입한 뒤 실제 거절과 복원을 확인한다.

FormationSession의 네 메서드는 SessionArming으로 옮겼고 두 enum은 session_state로 옮겼다. 기존 session export와 logger를 유지한다. session은 628→520줄이다. 이동한 본문과 남은 메서드의 원문, 원본 위치에서의 제거를 확인했다. 두 oversized ratchet 행은 각 추출과 같은 커밋에서 제거했다.

기존 manager/새 reference stream과 Fleet session/arming/relay를 실제 안전 모듈·앵커로 등록했다. 독립 `/root/time_sync_review`는 각 추출의 MRO·import·정리 순서·export·분류 변경에 차단 사항이 없다고 검토했고 각 소스 커밋에 한정된 Safety-Review trailer가 있다. 검토자는 시험·장치를 실행하지 않았다.

이 브랜치는 군집 수명주기 준비라는 한 관심사로 묶고, 공유 계약 및 실제 동작 소비자와 분리한다. 공식 FULL 착지 검증은 아직 남아 있다. 배포·UTC50ms·실물 정지·radio·FIELD를 수용하지 않는다.

CE: 해당 없음 — 추출은 동작을 보존하며 판단은 원문 비교·회귀·D-870에 직접 남긴다.

## 2026-10-25 integration preparation

Merged main d93c306e3f and pinned C0 commit 94d27806d2 on refactor/swarm-reference-stream-land. Resolved changelog and owner-log ordering; generated indexes are regenerated. No production-code conflict occurred. API reference v1.316 and envelope1.0 remain unchanged.

Git blob comparison confirms manager/reference_stream, session/session_arming/session_state and the boundary mutation test equal prepared commit 2bea6f4d1e byte for byte. Shared schemas and both incoming CE documents equal pinned C0.

Only static integration checks are authorized here. Historical remote results above remain attached to their original source commits; they are not a new pass for this integrated HEAD. Official FULL testing and landing await C0 landing confirmation and GO. CE: not applicable; existing ADR, tests and source comparisons already capture the merge rationale.

## 2026-10-25 D-875 safety boundary correction

Official C1 source commit `9f9fc5846d` failed both D-430 separation guards; the same guards passed on official main commit `6abf6a8a7e`. Whole-module safety classification exposed Decision dependencies and non-public legacy type reexports. D-875 keeps actual lifecycle, admission and relay authority in Safety, moves existing declarations to an owner-local API and supplies the existing planner/default assigner through the Decision facade. No frozen violation was added.

New pure-API, same-object reexport and planner/stop guards at commit `cac7a23477` produced remote RED: 3 FAIL, 1 PASS. Independently reviewed implementation commit `cc237b02c1` passed the entire architecture suite and 15 focused Fleet suites: **578 PASS, 5 SKIP, NEW0/known0/flaky0**, remote runner exit0. This includes separation, anchors/API roots, arming/start/stop/reform/resume, relay/transport, assignment/geometry, CLI/bench, formation routes and native/idle channel outcomes. The skips belong to existing architecture/environment guards; no browser or device acceptance is claimed.

Logs: `%LOCALAPPDATA%/Temp/rosy-c1-boundary/green-final/run-1.txt`, `green-final-runner.txt`, and `known-final.txt`. The preliminary unpublished source commit `afba821aa9` had 577 PASS, 5 SKIP and one CLI size failure; its evidence remains in `green/`. Root authorized amending only that owned candidate to remove one blank line and restore the existing 773-line limit; independent review confirmed the whitespace-only delta. The final committed SHA was rerun in full for the selected scope.

Static generate/lint passed (0 errors, 34 existing warnings); staged diff/syntax and size-range passed. Official dry-run exit0 selects FULL; actual FULL/landing remain pending. All 22 nonconstructor lifecycle method ASTs equal source `9f9fc5846d`, and CORE manager/reference_stream/test_swarm Git blobs equal original prepared C1 source `2bea6f4d1e`. External `source-preservation.json` records the exact blob IDs. Independent implementation review approved the actual final tree and is recorded in its Safety-Review trailer; it does not attest tests or field behavior.

CE: existing lesson update coordinated with root's separate queued-FULL guard tooling unit. Verified C1 case facts are supplied outside Git in `ce-case-draft.md`; this branch does not duplicate or concurrently edit that lesson. No deployment, clock convergence, robot motion or field acceptance.

## Latest main integration

Merged verified local main commit `ced1e7681e` into source commit `c5b4bcf1b3`. The separate landing-tool correction has already landed locally; its latest FULL had 24 invocations with NEW0, including one existing quarantined timing failure that passed on rerun. That tooling round had no browser opt-in invocation and is not C1 FULL evidence.

The incoming `RobotClient.motor_health()` declaration is preserved at the D-875 canonical API port. The other critical C1 source blobs match prepared commit `f289daf3e3`; incoming station/anchor implementations are retained. Both parent journals retain every nonempty line. Main's existing size shrink values remain, with only the two C1 manager/session ratchet rows removed. The already-landed D-868 gap is removed; absent reserved ADRs remain gaps.

Independent source review approved commit `c5b4bcf1b3`. On that exact committed source, the entire architecture suite and the same 15 Fleet suites passed remotely: **590 PASS, 5 SKIP, NEW0/known0/flaky0**, runner exit0. Raw logs: `rosy-c1-boundary/current-main-green/run-1.txt`, `current-main-green-runner.txt` and `current-main-known.txt` outside Git. Generate/lint reported 0 errors; the final run retained 35 warnings. The 11-commit size range passed. Parent-to-parent whitespace diagnostics inherited unchanged main files are not new merge edits.

Official C1 FULL and landing follow separately. No device, clock-precision, browser or field acceptance is inferred. CE: existing structural-guard lesson already records this boundary correction; the new merge and test evidence extends this verification record.
