---
title: 새 패키지는 전체 시험에서만 켜지는 저장소 가드 네 개를 통과해야 한다 — 모듈 시험 초록은 머지 준비가 아니다
date: 2026-09-26
category: workflow-issues
module: src/site/overhead (D-261) 머지 — test/architecture, test/test_module_scorecard.py, deploy/release/secret_scan.py, pytest 수집
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - src/ 아래에 package.xml이 있는 새 패키지를 만들 때
  - 새 모듈의 시험 파일 이름을 정할 때 (test_cli.py, test_protocol.py 같은 흔한 이름)
  - 시험 벡터·고정값에 40자 이상 hex나 50자 이상 영숫자 연속이 들어갈 때
  - 모듈 자기 시험과 하네스 lint만 보고 main에 머지하려 할 때
symptoms:
  - "src/site/overhead/test 45 passed, rosy_harness lint 0 error — 그런데 main을 합친 뒤 전체 시험에서 4건 실패/수집 오류"
  - "ERROR src/site/fleet/test/test_cli.py (수집 단계에서 전체 실행 중단)"
  - "test_every_package_has_a_declared_target: assert ['site/overhead'] == []"
  - "기준선에 없는 새 패키지: ['overhead']"
  - "secrets found in tracked files: ... high-entropy-token: \"hex\": \"524f4631...\""
root_cause: missing_workflow_step
tags: [new-package, repo-guards, target-layout, d-231, scorecard, d-178, secret-scan, d-256, pytest-basename, merge-readiness]
---

# 새 패키지는 전체 시험에서만 켜지는 저장소 가드 네 개를 통과해야 한다

## Context

2026-09-26 `src/site/overhead`(D-261: 폰 천장 카메라 수신기 + 안드로이드 앱)를 두 워크트리에서 만들었다.
모듈 자기 시험(`python -m pytest src/site/overhead/test -q` 45 passed), 안드로이드 JVM 시험 72개,
`rosy_harness.py lint` 0 error, 독립 리뷰 APPROVE까지 모두 초록이었다. 그런데 main을 합친 뒤
`src/site/overhead/test src/site/fleet/test src/site/games/test test`를 한 번에 돌리자 수집 오류 1건,
그다음 실패 3건이 나왔다. 넷 다 **새 패키지가 생겼다는 사실 자체**에 반응하는 저장소 가드였고,
모듈 시험에는 절대 나타나지 않는다.

## Guidance

새 패키지를 main에 넣기 전에 다음 넷을 직접 맞추고, 끝에 **저장소 전체 시험을 한 번에** 돌린다.

1. **시험 파일 이름이 다른 스위트와 겹치지 않게 한다.** 시험 디렉터리에 `__init__.py`가 없어서
   같은 basename 두 개를 한 pytest 실행에서 import할 수 없다. `src/site/overhead/test/test_cli.py`(이 수정으로
   `test_overhead_cli.py`로 이름이 바뀜)가 `src/site/fleet/test/test_cli.py`와 부딪혀 수집 단계에서 전체 실행이 멈췄다. 모듈 이름을 앞에 붙인다
   (`test_overhead_cli.py`). 확인:
   ```bash
   for f in src/<domain>/<pkg>/test/test_*.py; do b=$(basename $f); git ls-files "*/$b" | grep -v "^src/<domain>/<pkg>/"; done
   ```
2. **D-231 목표 배치표에 선언한다.** `test/architecture/test_target_layout.py`의 `TARGET`에
   `"site/overhead": "site/overhead"` 한 줄. `src/` 아래 모든 `package.xml` 위치가 이 표에 있어야 한다.
3. **D-178 평가표 기준선에 잠정 행을 넣는다.** `docs/adr/D-178-module-maintainability-scorecard.md`
   기준선 표에 `| \`<패키지명>\` | M1 | M2 | M3 | M4 | M5 | 총점 | 등급 | 비고 |` 행.
   `test_module_scorecard.py`가 작업 공간 패키지 집합과 표를 **집합 동일성**으로 비교하고,
   총점(`Σ 점수×가중치 ÷ 5`)과 등급 구간·컷 게이트도 다시 계산한다. 다른 신규 패키지처럼
   비고에 "잠정 채점(날짜)"을 적고, 표 아래 문단에 한 문장을 덧붙인다.
4. **비밀값 검사 오탐은 값이 있는 곳에서 고친다 (D-256).** `deploy/release/secret_scan.py`의
   `_BARE_TOKEN`은 40자 이상 hex 또는 50자 이상 영숫자(+`/`)를 잡는다. 걸린 것은 프로토콜 헤더
   시험 벡터(`"hex": "524f4631000000..."`)와 50자가 넘는 Kotlin 시험 함수 이름 두 개였다.
   스캐너 허용목록을 넓히지 않고:
   - 벡터 hex를 **필드 단위로 띄어 쓴다** (`"524f4631 00000000 00000000 0005 d002 5a00 0000"`).
     헤더 배치가 눈에 보여 오히려 읽기 좋다. Python `bytes.fromhex`는 공백을 받고, Kotlin 쪽은
     공백을 지운 뒤 비교·디코딩한다.
   - 긴 camelCase 시험 이름은 50자 미만으로 줄인다.

4개를 고친 뒤 결과: 가드 3개 + 모듈 시험 117 passed, 저장소 묶음 719 passed, 하네스 lint 0 error.

## Why This Matters

모듈 단위 검증(자기 시험, 하네스 lint, 코드 리뷰)은 이 네 가드를 한 번도 실행하지 않는다.
가드들은 저장소 전체 목록(패키지 집합, 추적 파일 전체, 한 번의 pytest 수집)을 보는 시험이라
새 패키지가 main에 들어가는 순간 **모든 세션의 전체 시험을 붉게** 만든다. 공유 체크아웃에서
동시 작업하는 다른 에이전트의 push까지 막는다. 전체 저장소 시험은 이 머신에서 13분쯤 걸리므로
"나중에 누가 돌리겠지"로 미루기 쉽다. 미루면 그 비용을 남이 치른다.

오탐을 스캐너에서 풀고 싶은 충동이 가장 크다. D-256은 그것을 금지한다: 값 단위 허용은
매처 전체를 무장 해제시킨 전례가 있다(PEM 헤더 사건).

## When to Apply

`src/**/package.xml`을 새로 만드는 모든 변경. 머지 전에 저장소 전체 시험을 한 번 돌리면
넷이 한꺼번에 드러난다:

```bash
python -m pytest src/<domain>/<pkg>/test src/site/fleet/test src/site/games/test test -q -p no:cacheprovider
```

단독으로 돌려 통과하는 무관한 시험 1건(이번에는 `test_sd_writer_contract.py`의 uid 재결합 시험)이
부하 때문에 섞여 실패할 수 있다. 이 브랜치가 그 파일을 건드리지 않았고 단독 재실행이 초록인지
확인한 뒤 따로 기록한다.

## Related

- `docs/adr/D-261-overhead-camera-app-skeleton.md` (이 패키지)
- `docs/adr/D-256-integrity-values-are-named-not-allowlisted.md` (오탐은 호출 지점에서)
- `docs/adr/D-178-module-maintainability-scorecard.md` Decision 5 (집합 동일성)
- `docs/solutions/workflow-issues/peers-share-one-git-index-never-amend-stage-only-your-line-2026-09-26.md` (같은 날 공유 체크아웃에서 커밋하는 방법)
