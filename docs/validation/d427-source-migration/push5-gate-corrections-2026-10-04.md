# D-427 push5 통합 게이트 수정 (2026-10-04)

## 기준과 관측

- 후보 기준: `69779adb524e`. 원격 기준 `7e26295117b9`.
- push5 빠른 게이트: 462 passed / 2 skipped / 11 freshness warnings, 84.59 s.
- 주 영향 범위: 3 failed / 12556 passed / 527 skipped / 20 warnings, 2123.78 s.
- 나머지 perception 포함 묶음: 2836 passed / 112 skipped, 415.35 s. face: 3 skipped.
- pre-push가 실패해 원격 main에는 보내지 않았다. 원본 출력: `X:/DevTemp/rosy-d427/resume/push-5.txt` (UTF-16).

## 변경과 유지 조건

1. 운영 시나리오의 가상 미래 `select_output(now=...)`는 실제 ingress 시계를 전진시키지 않는다. 실제 MANUAL 조종이 살아 있어 409가 맞았다. disconnect 출력 zero 확인 뒤 HTTP `IDLE` 전환으로 수동 소유를 해제하고 목표를 제출한다. 기본 500 ms watchdog과 운영 MANUAL 가드는 그대로다.
2. Fleet의 재명령 안내는 내부 intent mode를 한국어로 표시한다. 알려진 여섯 mode와 missing/unknown을 구분하고, prototype 이름이나 잘못된 자료형도 미확인 의도로 표시한다. 실제 카드 렌더 회귀가 한국어 문구와 명령 전송 없는 표시를 확인한다. presence/auth/seq/failsafe 감독과 기존 enum lint allowlist는 그대로다.
3. CORE 이미지 closure는 정확한 ROS 패키지 열 개와 ROS 밖의 계약 wheel 두 개를 각각 단정한다. ROS 입력은 container colcon source 아래에 있고, skill/motion은 그 밖의 계약 경로·COLCON_IGNORE·package.xml 부재를 만족한다. 임의 추가 입력·필수 입력 누락·wheel의 colcon 오배치는 허용하지 않는다. 실제 wheel 설치와 final image import probe는 기존 delivery 시험이 함께 확인한다.

## 로컬 검증

- 수정 관련 Python 전체 파일: 35 passed, 2.64 s. 실제 파일 mutation 복원 뒤 35 passed, 2.38 s.
- 구조·시험 소유·로봇 이름·Fleet API/팔레트/disabled feature: 97 passed, 13.07 s.
- Fleet 전체 Node: 109 passed. 신호 presence/label/실제 card render subset: 3 passed.
- 실제 mutation: motion COPY 누락, core ROS COPY 누락, motion wheel의 colcon 배치, raw intent 표시 복귀 — 네 경우 모두 RED. 각 파일이 바뀐 사실을 단정했고 원본 bytes로 복원한 뒤 GREEN을 확인했다.
- 문서/harness 계약: 59 passed, 11 기존 freshness warnings (18.27 s). harness lint: 0 errors / 11 warnings. `git diff --check` 통과.
- `test/known_failures.py`: 0 new / 0 known / 0 listed but not failing. backlog와 알려진 실패 파일은 고치지 않았다.
- gateway journey와 CORE closure flake8: 0. shared operator-copy parser의 기존 스타일 위반 44개는 기준과 정확히 같고 신규 위반 0개다. 기존 parser를 범위 밖으로 다시 쓰지 않았다.
- 원본 증거: `push5-corrections-focused.txt`, `push5-corrections-green.txt`, `push5-corrections-guards.txt`, `push5-corrections-node.txt`, `push5-corrections-mutations.json`, `push5-mutation-*.txt`, `push5-corrections-flake-baseline.json` (모두 `X:/DevTemp/rosy-d427/resume/`).

## 독립 리뷰와 다음 gate

- 독립 리뷰: `d427_safety_review` **APPROVE source/host**. 별도 설치 wheel 기반 Python 22 passed (2.10 s), Node 3 passed. Fleet 29276 줄은 기존 29264 기준에서 +12이며 +150 허용·split 판정은 유지한다. 실제 gateway/closure/display-only 조건을 검토했으며 예산·allowlist·waiver를 늘리지 않았다. 기록: `push5-corrections-independent-review-2026-10-04.md`.
- 새 후보 pre-push와 원격 CI는 아직 NOT_RUN. ARM64 native/SD image, release 서명·발행, robot readback, 사이트 PC model-watch는 별도 후속이다.
- 다른 브랜치가 unsigned `2026.10.04-034`를 이미 빌드했다(run `37158237042`). 이번 릴리스 번호는 발행 전 다음 사용 가능한 번호를 다시 확인하며 034를 재사용하지 않는다.
