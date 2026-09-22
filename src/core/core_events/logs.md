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
