# Fleet 막힘 판단 코드를 `fleet/fleet/stuck` 하위 패키지로 옮기는 계획

- 날짜: 2026-10-10
- 결정: [D-577](../adr/D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md), [D-438](../adr/D-438-fleet-stuck-resolver-rules-model-human.md), P6 크기 규칙 [D-362](../adr/D-362-per-code-type-file-size-budget.md)
- 계기: `fleet` 패키지 크기 판정이 D-577 때문에 다시 매겨졌다(51672 → 51848 → 52550). Fleet 판단 코드가 커져서이고, D-577의 분리 조건을 두 번째로 넘었다. 지금 `fleet`은 52550줄이다.

## 규칙

**이 이동이 끝나기 전에는 `line_stuck`·`stuck_*`·`ai_facts`를 더 키우는 변경을 착지하지 않는다.** 결함 수정은 같은 줄 수 안에서(늘지 않게) 하거나 이 이동 뒤에 한다.

## 옮기는 것

| 지금 (`operations/fleet/fleet/server/`) | 옮긴 뒤 (`operations/fleet/fleet/stuck/`) | 줄 수 (2026-10-10) |
|---|---|---|
| `line_stuck.py` | `board.py` | 396 |
| `stuck_resolver.py` | `resolver.py` | 600 |
| `stuck_resolver_loop.py` | `loop.py` | 165 |
| `stuck_lane_lost.py` | `lane_lost.py` | 149 |
| `ai_facts.py` | `ai_facts.py` | 292 |

합계 1602줄. 옮긴 뒤 `fleet`은 약 50948줄이다(52550 − 1602).

`fleet/fleet/stuck`는 `SIZE_UNITS`에 크기 단위로 넣는다(`test/architecture/test_module_structure.py`). 그 줄 수는 `fleet` 합계에서 빠지고, 단위 자체가 판정과 +150 허용을 갖는다. 같은 변경에서 `fleet` 판정을 다시 잰다.

## 순서

1. 파일을 `git mv`로 옮기고 import만 고친다. 동작 변경 없음. 옛 경로에 재수출 모듈을 두지 않는다(모든 호출자를 고친다: `app.py`, `console_routes.py`, `cli.py`, 시험).
2. `SIZE_UNITS`에 `fleet/fleet/stuck`, `SIZE_VERDICTS`에 그 단위의 판정을 더하고 `fleet` 합계 판정을 다시 잰다.
3. `operations/fleet/fleet/stuck/AGENTS.md`(모듈 기록, D-61)를 만들고 `server/AGENTS.md`의 행을 옮긴다.
4. 시험: `operations/fleet/test/test_stuck_*.py`, `test_line_stuck_*.py`, `test_ai_facts.py`, `test_mission_ai_proposal.py`, `operations/situation/test`, `test/architecture/test_module_structure.py`를 `tools/remote/remote_pytest.py`로 돌리고 `test/known_failures.py`에 NEW가 없어야 한다.
5. 독립 검토(크기 단위 추가 규칙) 뒤 착지.

## 하지 않는 것

- 판단 규칙, API, 감사 표 이름은 바꾸지 않는다. 이동만 한다.
- `fleet/traffic`(이미 단위)과 합치지 않는다.

## D-610 통합 시 적용한 저장 책임 분리

2026-10-10 기존 판정의 다음 성장 조건을 적용했다. `board.py`의 `LineStuckAnswerLog`와
순수 함수 `_resolution`을 함께 `stuck/reports.py`로 옮겼다. 모든 호출자가 새 경로를
직접 import하며, DB 스키마·트랜잭션·조회·오류 처리는 그대로다. `board.py`는 메모리
상태를 맡고, `reports.py`는 감사 기록과 사람 검토를 맡는다.

D-610의 정책·케이스·결과 확인·문제 관찰·에피소드 저장은 각 파일에 있다. 별도 검토
에이전트 `integration_review`가 이 경계에 동의했다. 새 크기 단위나 예산 완화 없이
stuck 전체를 2800줄로 다시 측정했다. 다음 성장은 +150줄에서 재검토하며, AI 사실
소유 영역이 커지면 HTTP 경로와 감사 저장을 분리한다.
