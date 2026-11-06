# situation logs

## 2026-10-28 · uncommitted · harness 모듈 등록

- 변경: `tools/harness/harness.yaml` `modules`에 `situation`(path `operations/situation`, tests/functional `operations/situation/test`)을 등록하고 모듈 harness 기록(`progress.md`, `logs.md`, 생성 `index.md`)을 시작했다. 이때까지 이 모듈은 size 단위로만 세이고(size_units.txt:82) 모듈 등록·게이트 기록이 없어, 나중에 등록된 monitoring(D-876)·rosy_vision과 대비되는 갭이었다.
- 증거: 등록 시점 원격 시험(아래 회차)에서 `operations/situation/test` green, known NEW 0. `last_verified`는 본 등록 직전 main(3627ec21fb)의 같은 suite green을 가리킨다.
- gate 변화: 없음 — 기존 상태를 처음으로 기록 형태로 고정한다(SOURCE GO, LOCAL/ARTIFACT/DEVICE/FIELD HOLD는 D-516·D-630 경계 그대로).
- CE: 해당 없음 — 등록 자체가 기록이다.

## 2026-11-03 · uncommitted · feat(situation): D-971 AI PC가 팔 사건을 설명한다

- 변경: `rosy_situation/arm_incidents.py`. `ROSY_ARM_INCIDENTS=1`일 때만 Fleet에서 설명 없는 열린 팔 사건을 15초마다 당겨 가 로컬 시각 모델로 `{seen, suspected_cause}`를 만들어 돌려준다. 동작을 고르지 않고 실패는 기록만 한다.
- 증거: `operations/situation/test/test_situation_arm_incidents.py` 원격 통과(가짜 Ollama·가짜 Fleet). 실제 AI PC는 부르지 않았다.
- gate 변화: 없음.
- CE: 해당 없음.
