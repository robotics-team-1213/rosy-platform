## D-584 테스트는 운영 노트북에서 돌리지 않는다 — 시험 PC가 없으면 기다리거나 실패한다

**Status:** Accepted (2026-10-10, 사용자 결정 "test는 무조건 로컬 PC가 아니라 다른 PC에서 하도록").

### Context

D-553·D-568은 pytest를 모델 PC(OMEN), AI PC, 현장 PC 가운데 여유 있는 곳에서 돌리게 했다. 하지만 예외가 남아 있었다.

- `tools/remote/remote_pytest.py`는 `--require-host` 없이 부르면, 닿는 시험 PC가 없을 때 노트북에서 돌린다. `--local`과 `ROSY_TEST_LOCAL=1`은 노트북 실행을 강제한다.
- `tools/land.py`는 시험 PC가 없으면 로컬로 돌리도록 일부러 열어 두었다.
- 저장소와 우산 폴더의 AGENTS.md, `shared-checkout.md`, `rosy-land-on-main` 스킬은 "어느 PC도 닿지 않을 때만 로컬로 돌린다"고 적었다.

노트북의 로컬 실행은 커밋이 아니라 작업 트리를 시험하고, 다른 세션이 같이 쓰는 노트북의 CPU를 막는다. 모델 PC가 메모리 부족으로 멈춘 2026-10-09 사건(D-566)처럼 시험 PC가 잠시 없을 때가 바로 이 예외가 쓰이는 때였다.

### Decision

1. **pytest, 브라우저 시험, Gazebo, GPU·torch 시험은 운영 노트북에서 돌리지 않는다.** 시험은 커밋된 HEAD를 시험 PC(모델 PC, AI PC, 현장 PC; D-553·D-568의 배치 규칙)로 보내서만 돌린다.
2. **시험 PC가 없으면 기다리거나 실패한다.** `remote_pytest.py`는 닿는 PC가 없으면 노트북으로 넘어가지 않고, 정해진 시간 동안 다시 시도한 뒤 실패로 끝낸다. `--local`과 `ROSY_TEST_LOCAL=1`은 없앤다. 남아 있는 호출은 분명한 오류로 거절한다. `land.py`, pre-push, CI 보조 스크립트도 같은 경로만 쓴다.
3. **실패는 통과가 아니다.** 시험 PC가 없어 돌리지 못한 시험은 "확인 못 함"으로 보고한다. 착지와 푸시는 하지 않는다.
4. **노트북에서 해도 되는 것.** lint(`rosy_harness.py lint`), 정적 검사, git·ADR 도구, 원격 시험 로그를 `known_failures.py`로 비교하는 일, 이미 만든 결과 파일을 읽는 일은 계속 노트북에서 한다. 이는 코드를 실행해 시험하는 것이 아니다.
5. **문서를 같이 고친다.** 저장소 AGENTS.md「같이 하는 깃」5항, 우산 폴더 AGENTS.md의 같은 절, `docs/reference/shared-checkout.md`, `rosy-land-on-main` 스킬의 "로컬로 돌린다" 문구를 이 결정으로 바꾼다.

### Consequences

- 시험 PC가 모두 바쁘거나 꺼져 있으면 착지가 늦어진다. 그 시간은 기다림으로 보고하고, 노트북 실행으로 메우지 않는다.
- D-566의 모델 PC 작업 규칙(메모리 상한, 한 번에 GPU 작업 하나)은 그대로 적용된다.

**Related:** [D-553](D-553-cd-speed-parallel-build-and-test-pcs.md), [D-568](D-568-compute-pool-headroom-placement.md), [D-566](D-566-v13-1-offroad-false-positive-and-model-pc-job-guard.md).
