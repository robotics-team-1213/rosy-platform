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

### 개정 (2026-10-14, 사용자 결정): 이 규칙은 실험실 노트북과 실험실 에이전트 세션의 규칙이다 (D-762 Decision 4)

위 Decision 본문은 바꾸지 않는다. 적용 범위만 정한다.

1. **범위.** Decision 1–3의 "운영 노트북"은 실험실 노트북 한 대와 그 위에서 도는 에이전트 세션이다. 여러 세션이 같이 쓰는 PC의 CPU를 막지 않고, 작업 트리가 아니라 커밋을 시험한다는 이유는 그 PC에만 해당한다. 그 PC와 그 세션에서는 규칙이 그대로다.
2. **다른 기여자.** 실험실 시험 PC에 닿지 못하는 기여자는 자기 PC에서 pytest를 돌려도 된다. 그 결과는 작업 중의 확인이다.
3. **들이는 증거.** 변경을 `main`에 들이는 증거는 PR의 CI다. 자기 PC의 통과도, 실험실 시험 PC의 통과도 그것을 대신하지 않는다. 서버가 CI를 필수로 요구하는 것은 D-762 단계 3부터다. 그 전에는 CI가 돌지만 요구되지 않는다.
4. **pre-push를 둘로 나눈다(D-762 단계 4).** 정적 부분(lint, 생성 기록 확인, Safety-Review trailer)은 어디서나 돈다. 시험 부분은 실험실 시험 PC가 설정된 clone에서만 돈다. 설정이 없는 clone에서는 시험 부분이 실패하지 않고 "PR CI가 증거"라고 알린다. **이 분리는 아직 구현되지 않았다.** 오늘의 `tools/hooks/pre-push`는 닿는 시험 PC가 없으면 push를 실패시킨다.
5. **바뀌지 않는 것.** 실험실에서는 `--local`과 `ROSY_TEST_LOCAL`을 되살리지 않는다. 시험 PC가 없어 돌리지 못한 시험은 여전히 "확인 못 함"이다. `AGENTS.md` 「같이 하는 깃」 5항은 실험실 체크아웃의 절차라 그대로 둔다.
