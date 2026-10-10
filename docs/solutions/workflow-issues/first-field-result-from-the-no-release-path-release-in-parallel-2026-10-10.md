---
title: 개발 중 첫 실물 결과는 릴리스가 필요 없는 경로에서 낸다 — 릴리스 경로는 나란히 돌린다
date: 2026-10-10
category: workflow-issues
module: field test path (on-robot loop via CORE API, model pointer, payload release, pre-push gate)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "a model or code change must be seen driving on a real Pinky soon"
  - "a change needs a new runtime parameter, overlay key or node behaviour on the robot"
  - "local main is many commits ahead of origin/main before a push"
  - "someone proposes skipping tests or the pre-push gate to get to the robot faster"
symptoms:
  - "D-592 on-robot script loop drove 9dfk with the crop128 drivable model within one agent run, without a release"
  - "D-597 runtime keep-mode drivable source needed land, push, ARM64 build (4m19s-6m36s, runs 069-071), sign, push to each robot, overlay, restart"
  - "pre-push affected tier was huge because local main was 97 commits ahead of origin/main; all 3 test PCs were below the memory floor"
  - "2 unrelated guard failures (size verdict, frozen behaviour-test set) blocked the push"
  - "the user ordered '테스트하지 말고 바로 착지', then a --no-verify push"
  - "a new overlay key made the installed release's validator skip the whole line_observer overlay"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
tags: [field-test, release, pre-push, affected-tier, overlay, model-pointer, d-592, d-597, d-553, d-584, d-548]
---

# 개발 중 첫 실물 결과는 릴리스가 필요 없는 경로에서 낸다

## Context

2026-10-10 목표는 팀 crop128 drivable 모델로 Pinky를 조향하는 것이었다. 같은 날 두 경로를 탔다.

- **경로 A (D-592).** 로봇 위 스크립트 루프 `tools/capture/drivable_steer.py`. 스크립트 묶음(`git archive`)과 모델을 로봇 `~/d592/`에 복사하고, ONNX 스레드 2로 돌려 CORE teleop(`MANUAL`)으로 명령을 보냈다. 계산만 하는 실행 3번, 실주행 1번. 시작부터 9dfk 실주행까지 에이전트 한 번의 실행 안에 끝났다. 릴리스도, 테스트 게이트도 없었다(기록: `docs/validation/d592-drivable-steer-field-test-2026-10-10.md`, 브랜치 `feat/drivable-steer-field-test`).
- **경로 B (D-597).** 런타임 keep 모드의 drivable paint 소스(`learned_paint_target`). 착지 → 푸시 → GitHub ARM64 payload 빌드 → 서명 → 로봇마다 push → overlay → `rosy-camera` 재시작이 필요했다.

B에서 막힌 곳:

1. **pre-push 게이트.** `tools/hooks/pre-push`는 fast suite와 affected tier를 원격 pytest로 돌리고, affected 기준은 `git merge-base <push> origin/main`이다. 로컬 main이 origin보다 97커밋 앞서 있어 affected tier가 컸다. 시험 PC 3대가 모두 메모리 하한 아래였고, 이번 변경과 관계없는 가드 실패 2건(size verdict, frozen behaviour-test set)이 푸시를 막았다.
2. **릴리스 빌드 시간.** 릴리스 069–071 빌드가 4분 19초–6분 36초 걸렸다. 서명·로봇별 push·재시작은 별도다.
3. **모델 파일 권한.** 로봇의 `/var/lib/rosy/models`는 `root:rosy-camera` 0750이라 `rosy` 사용자가 읽지 못한다. A 루프는 같은 sha256의 모델을 `~/d592/model`에 따로 복사해 썼다.
4. **overlay 키 화이트리스트.** `/etc/rosy/line_observer_overrides.yaml`은 설치된 릴리스의 `control/ir_overlay.py` `OPERATOR_KEYS`로 검사된다. 모르는 키가 하나라도 있으면 overlay 전체를 건너뛴다. 새 파라미터는 그 키를 가진 릴리스가 먼저 로봇에 있어야 overlay로 켤 수 있다.
5. 결국 사용자가 "테스트하지 말고 바로 착지"라고 명시했고, 이어 `--no-verify` 푸시를 했다.

## Guidance

1. **첫 실물 결과는 릴리스 없는 경로에서 낸다.** 로봇 런타임을 바꾸지 않고 CORE 외부 API(teleop, 녹화, 상태)만 쓰는 로봇 위 루프, 또는 이미 설치된 런타임이 읽는 입력 교체(paint 모델 포인터, 이미 있는 overlay 키)로 먼저 움직인다. 판단표와 명령은 `.claude/skills/rosy-fast-field-test/SKILL.md`다.
2. **릴리스 경로는 같은 날 나란히 돌린다.** 실물 루프를 돌리는 동안 런타임 변경을 브랜치에 커밋하고, 사용자가 말하면 착지·푸시·빌드를 시작한다. 빌드 대기(4–7분) 동안 루프 결과를 기록한다. A의 결과로 B의 기본값을 정한다.
3. **origin을 로컬 main 가까이 둔다.** 푸시 전에 `git rev-list --count origin/main..main`을 본다. 클수록 pre-push affected tier가 커지고 남의 실패를 만난다. 사용자가 푸시를 허락한 브랜치는 착지할 때마다 바로 푸시해 이 수를 작게 유지한다.
4. **게이트는 사용자의 명시적 말이 있을 때만 건너뛴다.** `tools/land.py --tests none`, `git push --no-verify`는 사용자가 그 말을 한 경우에만 쓰고, 건너뛴 사실과 남은 위험을 보고에 적는다. 막은 실패가 남의 커밋이면 `prepush-gate-red-from-other-sessions-unpushed-commits-2026-10-10.md`대로 원인 커밋을 찾는다. `known_failures.txt`에 넣지 않는다.
5. **새 overlay 키는 릴리스가 먼저다.** 키를 추가한 릴리스가 로봇에 올라가기 전에는 overlay에 그 키를 쓰지 않는다. 쓰면 기존 overlay 설정(paint 소스, 피치·높이)까지 함께 꺼진다. `line_observer_overrides show`로 "launch가 읽는다"를 확인한다.

## Why This Matters

A는 몇십 분, B는 하루 내내 걸렸다. 차이는 코드 품질이 아니라 경로의 단계 수다. 릴리스가 필요 없는 경로로 첫 실물 결과를 내면, 릴리스 경로가 막혀도 실물 피드백은 멈추지 않는다. 사용자가 "더 이상 지체할 시간이 없다"고 할 때 게이트를 우회하는 대신 갈 길이 이미 있다. 게이트를 건너뛰는 일은 사용자가 결정한다. 에이전트가 시간을 이유로 스스로 정하지 않는다.

## When to Apply

- "실제 로봇에서 빨리 보자"는 요청을 받았을 때. 첫 작업은 판단표다.
- 새 런타임 파라미터나 overlay 키를 설계할 때. 실물 시험은 스크립트 루프로 하고, 키는 릴리스와 같이 낸다.
- 푸시 전, 로컬 main이 origin보다 크게 앞서 있을 때.

## Examples

나쁜 예: 새 keep 조향 소스를 만든 뒤 착지 → 푸시(게이트 막힘) → 빌드 → 서명 → push까지 기다리고 나서야 첫 실물 주행을 본다. overlay에 새 키를 먼저 넣어 기존 learned paint 설정까지 꺼진다.

좋은 예: 같은 조향 규칙을 `tools/capture/` 스크립트로 만들어 `~/<topic>/`에 복사하고, 계산만 하는 실행 → 실주행을 한다. 그동안 런타임 변경은 브랜치에 커밋해 두고, 사용자가 푸시를 말하면 릴리스를 시작한다.

## Related

- 카드: `.claude/skills/rosy-fast-field-test/SKILL.md`, `.claude/skills/rosy-release-push/SKILL.md`, `.claude/skills/rosy-land-on-main/SKILL.md`
- [학습한 출력이 런타임에 실제로 쓰이는지부터 확인한다](check-the-runtime-consumes-a-learned-output-before-training-it-2026-10-10.md) — 같은 날의 짝 교훈. 소비 경로가 없으면 포인터 교체는 효과가 없다.
- [pre-push가 남의 미푸시 커밋으로 빨개진다](prepush-gate-red-from-other-sessions-unpushed-commits-2026-10-10.md)
- [D-592](../../adr/D-592-drivable-steering-field-test-pc-loop.md), [D-597](../../adr/D-597-drivable-keep-steering-source.md), [D-553](../../adr/D-553-cd-speed-parallel-build-and-test-pcs.md), [D-584](../../adr/D-584-tests-never-run-on-operator-laptop.md), [D-548](../../adr/D-548-device-dev-mode-marker.md)
