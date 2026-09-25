# core_events logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/core_events`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register core_events under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `PYTHONPATH=src/core:src python -m pytest src/core/core/test -q` — core suite 1056 passed, 12 skipped (2026-09-22 Windows); no own test/ yet (D-168 KNOWN_WITHOUT_OWN_TESTS)
- gate 변화: 없음(신규 기록). SOURCE HOLD(자체 시험 없음), LOCAL GO(core 스위트), 나머지 N/A
- 결정: D-168
- 교훈: 없음

## 2026-09-22 · uncommitted · fix(core_events): audit quarantine off the lock, no duplicate evidence, thread-start and dir-fsync failures counted
- 변경: `events/audit.py` — (1) 격리 파일 덧붙이기+fsync 를 `record()` 가 기다리는 락 **밖**, 바꿔 끼우기 **전**으로 옮기고, `(파일 신원, {(오프셋, 바이트)})` 로 이미 격리한 줄을 기억해 바꿔 끼우기가 실패한 뒤의 재시도가 같은 바이트를 두 번 격리하지 않게 한다(성공한 바꿔 끼우기에 비운다). "격리 없이 지우지 않는다"는 그대로 — 건너뛰는 줄은 같은 바이트가 이미 격리 파일에 있을 때뿐. (2) `Thread.start()` 의 `RuntimeError` 를 삼켜 `_worker=None`·요청 해제·`prune_failures` +1(`last_prune_error="worker start: ..."`) — `record()` 무던짐 유지, 정리가 영영 멈추지 않는다. (3) `os.replace` 뒤 디렉터리 fsync 실패는 `prune_failures` 가 아니라 새 `health()` 칸 `dir_sync_failures`·`last_dir_sync_error` 로 센다. 중복 근거 주석 정리(splitlines·신원 검사). `test_audit.py` 시험 5 개 추가(락 소유로 본 fsync 위치, 재시도 중복, 새 손상 줄은 여전히 격리, 스레드 시작 실패, 디렉터리 fsync), `test_module_structure.py` audit.py 판정 길이 675→692
- 증거: `python -m pytest src/core/core/test/ src/core/core_api_web/test test/ -q -p no:cacheprovider` (3.14) 2521 passed, 51 skipped, 3 failed — 모두 `test_harness_contracts.py` 의 main 선재 문제(D-171 본문 없음, 생성물 stale); `uv run --python 3.12 ... pytest src/core/core/test/` 1224 passed, 13 skipped. 새 시험 5 개와 키 계약 시험은 옛 audit.py 에서 실패함을 확인. 부하 스크립트(stall/jitter/race)는 main 과 같은 수준(record 최악 1.4 ms / 12.4 ms)
- gate 변화: 없음. LOCAL GO 유지
- 결정: 없음
- 교훈: 재시도 중복을 막는 표시는 "그 바이트가 이미 격리 파일에 있다"를 증명할 때만 건너뛰게 키를 잡는다 — 그러면 신원이 우연히 같아도 삭제 불변식이 깨지지 않는다.

## 2026-09-23 · uncommitted · fix(core_events): the quarantine dedupe re-checks that the quarantine file still holds the bytes
- 변경: `events/audit.py` — 리뷰 HIGH. 격리 fsync 뒤 격리 파일의 `(st_dev, st_ino, st_size)` 를 `_quarantined` 에 함께 적고, 재시도가 "이미 격리함" 표시를 믿기 전에 격리 파일을 `stat` 한다(`_already_quarantined`). 없거나 다른 파일이거나 적은 크기보다 작으면 표시를 버리고 다시 격리한다 — 틀려도 중복 쪽. 재현: 바꿔 끼우기 실패 → 운영자가 격리 파일을 지움/비움 → 재시도가 건너뜀 → 바꿔 끼우기 성공 → 증거가 어느 파일에도 없음(`qrot.py`). 시험 `test_a_quarantine_file_removed_before_the_retry_is_written_again[delete|truncate]` 추가(옛 코드에서 둘 다 실패 확인). audit.py 판정 길이 692→707
- 증거: 3.14 `python -m pytest src/core/core/test/ src/core/core_api_web/test test/ -q -p no:cacheprovider`, 3.12 `uv run ... pytest src/core/core/test/` — 3.14 2517 passed / 51 skipped / 15 failed, 3.12 1214 passed / 13 skipped / 15 failed. 15 개는 모두 main 에서 온 `core_api_web/api/v1/system.py` 의 UTF-8 BOM(`10ceb53`, `ast.parse` SyntaxError U+FEFF, `test_event_catalogue`·`test_vision_boundaries`)이고, BOM 을 잠시 떼면 두 파일 74 passed. `qrot.py` 재시도 뒤 격리 파일에 증거가 있다
- gate 변화: 없음. LOCAL GO 유지
- 결정: 없음
- 교훈: "이미 했다"는 표시는 그 결과가 담긴 파일이 아직 그 파일일 때만 참이다 — 우리 밖에서 지워질 수 있는 파일에 대한 기억은 쓰기 전에 다시 확인한다.

## 2026-09-23 · uncommitted · fix(core_events): a reused inode no longer passes as the same audit file

- 변경: 정리가 "이 파일이 아직 그 파일인가"를 (장치, inode)와 크기로만 확인했다. Linux(ext4·tmpfs)는 지운 파일의 inode 번호를 곧바로 새 파일에 다시 주므로, 지우고 다시 만든 더 긴 파일이 같은 신원으로 보여 남의 내용 한가운데에 옛 스냅샷을 이어 붙였다. 이제 이어 붙일 경계 바로 앞 최대 4 KiB(`_FINGERPRINT_BYTES`)가 읽은 스냅샷과 같은지도 락 안에서 본다. 격리 파일의 중복 방지 표시도 같은 이유로, 마지막으로 쓴 바이트가 그 자리에 그대로 있을 때만 믿는다.
- 증거: PR #22 CI(`ros:jazzy`, Linux)에서 `test_a_file_swapped_for_a_longer_one_is_not_spliced`가 실패했다(Windows 3.14·3.12에서는 통과, Windows는 파일 ID를 바로 재사용하지 않는다). 신규 `test_a_file_rewritten_in_place_is_not_spliced`와 `test_a_quarantine_file_removed_before_the_retry_is_written_again[rewrite]`는 제자리 덮어쓰기로 같은 inode를 만들어 어느 OS에서나 재현한다. 수정 전 2 failed, 수정 후 `test_audit.py` 69 passed(Windows 3.14, WSL Linux 3.12.3).
- gate 변화: 없음.
- 결정: 없음(D-172 F2 연장).
- 교훈: 파일 신원 검사를 Windows에서만 검증하면 inode 재사용을 못 본다. 제자리 덮어쓰기 시험으로 OS와 무관하게 재현한다.

## 2026-09-23 · uncommitted · fix(core_events): the splice check also looks at the head, and the quarantine marker records our own end

- 변경: 리뷰(`348e473`)의 선택 보강 3건. (1) 이어 붙이기 전에 경계 바로 앞뿐 아니라 파일 앞 최대 4 KiB도 스냅샷과 비교한다. 같은 길이로 제자리 저장하는 편집기는 inode·크기·끝을 모두 그대로 두므로, 끝만 보면 그 편집을 옛 스냅샷이 조용히 되돌린다. 락 안에서 읽는 양은 합해 8 KiB 이하다. (2) 격리 파일의 중복 방지 표시는 `fstat` 크기 대신 우리가 쓴 끝(`tell()`)을 기록한다. 그 사이 남이 덧붙인 바이트를 지문으로 삼지 않는다. (3) `_quarantined` 타입 주석을 실제 모양대로 적었다. `audit.py` 745줄, D-168 판정 수치 갱신.
- 증거: 신규 `test_a_file_edited_in_place_near_the_start_is_not_spliced`는 이전 `audit.py`에서 실패하고 이 변경에서 통과한다. `test_audit.py` + `test_diagnostics_api.py` 79 passed(Windows 3.14).
- gate 변화: 없음.
- 결정: 없음(D-172 F2 연장).
- 교훈: 없음

## 2026-09-24 · uncommitted · test(core): LOG-001 audit 계약을 자체 `test/`로 이전

- 변경: `src/core/core/test/test_audit.py` → `src/core/core_events/test/test_audit.py`(`git mv`) + `test/conftest.py` 부트스트랩(`core_events`·`core_common` sys.path). D-168 `KNOWN_WITHOUT_OWN_TESTS`에서 `core_events` 제거, `harness.yaml` `tests`/`functional` 경로 갱신, AGENTS 테이블·Testing 블록 갱신, SOURCE gate HOLD→GO.
- 증거: `python -m pytest src/core/core_events/test -q` 70 passed (2026-09-24 Windows); 전체 게이트는 커밋 직전 실행.
- gate 변화: SOURCE HOLD→GO(자체 `test/` 확보), LOCAL GO 유지.
- 결정: module-coupling-scorecard §6 과제 2(집합 동일성 단정과 동시 갱신).
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(runtime): move core_events under src/runtime (D-231)

- 변경: src/runtime/core_events로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
