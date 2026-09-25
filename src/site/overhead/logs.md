# overhead logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-26 · uncommitted · feat(overhead): rosy-overhead/1 protocol module (D-261 A1)

- 변경: `overhead/protocol.py` — 20바이트 헤더 pack/parse(`magic`/`short`/`reserved`/`rotation`/`size` 사유), `validate_hello`, `make_config`, `rosyov://` pairing URI 생성·파싱. `protocol/vectors.json`의 모든 벡터를 시험이 돈다.
- 증거: `python -m pytest src/site/overhead/test/test_protocol.py -q` 27 passed
- gate 변화: SOURCE/LOCAL GO 시작. DEVICE/FIELD PARKED.

## 2026-09-26 · uncommitted · feat(overhead): receive-only WebSocket ingest server (D-261 A2)

- 변경: `overhead/ingest.py` — 토큰 없으면 401, 경로 틀리면 404, `hello` 불량이면 4400, 같은 source 재접속이면 옛 연결 4409, 최신 1장만 보관(큐 없음), `max_bytes` 초과·헤더 불량은 연결 유지한 채 드롭 카운트, `captured_at`은 이 프로세스 자체 벽시계 − `age_ms`.
- 증거: `python -m pytest src/site/overhead/test -q` 36 passed (실 localhost 서버, websockets 클라이언트)
- gate 변화: 없음. LOCAL GO 유지.

## 2026-09-26 · uncommitted · feat(overhead): rosy_overhead receive CLI + ament_python package (D-261 A2)

- 변경: `overhead/cli.py` — `rosy_overhead receive`가 pairing URI(+선택 ASCII QR)를 찍고, 토큰 미설정이면 생성하고, 초당 소스별 통계를 찍는다. `--stats-jsonl`/`--save-latest` 지원. `package.xml`/`setup.py`/`setup.cfg`/`resource/overhead`는 games와 같은 레이아웃.
- 증거: `python -m pytest src/site/overhead/test -q` 41 passed
- gate 변화: 없음. LOCAL GO 유지. DEVICE/FIELD PARKED.
