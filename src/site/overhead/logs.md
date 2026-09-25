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

## 2026-09-26 · 27b8f34e · fix(overhead): never stall a reconnecting phone behind a half-open old socket

- 변경: 독립 리뷰(REQUEST CHANGES)가 재현한 결함 — 같은 source 교체 때 옛 연결 close를 기다리면, 옛 폰이 Wi-Fi를 잃은 반열림 상태일 때 새 연결이 10 s 멈추고 그동안 프레임이 websockets 안에 쌓였다. 옛 close는 백그라운드(2 s 뒤 transport abort), 수신 큐 1장, `max_size`는 `max_bytes`를 따른다, hello 5 s 무응답은 4400, 토큰 비교 상수 시간, `websockets>=14` 선언(Ubuntu 24.04 apt 10.x는 import에서 명확히 실패).
- 증거: 반열림 시험이 옛 코드에서 10.2 s로 빨강, 수정 후 초록. `python -m pytest src/site/overhead/test -q` 45 passed ×4
- gate 변화: 없음. LOCAL GO 유지.

## 2026-09-26 · c6647a1e · 에뮬레이터 종단 확인 (안드로이드 앱 → 이 어댑터)

- 변경: 코드 없음. 안드로이드 리뷰 수정(타임스탬프 기준 판정, 토큰 로그 가림, 회전 시 페어링 대화상자 유지) 뒤 재확인.
- 증거: API 35 에뮬레이터(가상 장면 카메라) → `rosy_overhead receive` 127.0.0.1:8095. 3 fps, `seq_gaps` 0, 헤더 불량 0, `age_ms` p50 11–177 ms, 약 0.4–0.6 Mbps. 수신기 종료 → 앱 "다시 연결 중" → 수신기 재기동 → 앱이 스스로 재접속해 32프레임. 딥링크 확인 대화상자가 가로/세로 회전 뒤에도 남고 취소하면 기존 페어링 유지. 정지 시 카메라 DISCONNECT 확인.
- gate 변화: 없음. 에뮬레이터는 LOCAL이다(D-261 8항). DEVICE PARKED.

