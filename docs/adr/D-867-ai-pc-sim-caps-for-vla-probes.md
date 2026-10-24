## D-867 AI PC 시뮬레이션 실행 상한을 4코어·4GB에서 6코어·10GB로 올린다

**Status:** Accepted (2026-10-25, 사용자 결정 「한도 올리고 처리해」). D-571 §4의 AI PC 행만 바꾼다. 모델 PC 상한과 배치 규칙, 관제 PC 제외는 그대로다.

**관련:** D-571 §4 · D-866 · D-864 §5

### Context

- D-571은 AI PC를 RAM 15GB 공용 PC로 보고 실행 하나당 4코어·4GB로 묶었다.
- 2026-10-25 `free -g`·`nproc` 확인 결과 AI PC는 RAM 30GB(사용 6GB, 가용 24GB), 24코어다.
- D-866 P0은 Gazebo, CORE, Fleet, SmolVLA 추론 자식 프로세스를 같은 PC(D-795)에서 한 실행으로 돌린다. SmolVLA 기본 모델은 GPU에 올라가도 호스트 메모리를 수 GB 쓰므로 4GB 상한을 넘을 수 있다.

### Decision

- `tools/remote/remote_sim.py`의 AI PC 프로필을 `cpus=6`, `mem_gb=10`으로 한다. 모델 PC(`cpus=8`, `mem_gb=6`)는 바꾸지 않는다. AI PC 코어 상한이 모델 PC보다 작다는 기존 시험 조건은 유지된다.
- 상한은 여전히 `systemd-run --scope`의 `MemoryMax`·`CPUQuota`와 `nice -n 10`으로 건다. 공용 PC의 다른 사용자 작업 보호 규칙(D-571)은 그대로다.

### Consequences

- AI PC에서 VLA를 포함한 Gazebo 실행이 한 번에 쓸 수 있는 자원이 늘어난다. 같은 PC의 다른 작업이 쓸 여유는 그만큼 줄어든다.
- D-571 §1 표의 AI PC RAM 15GB는 실제와 다르다. 이 ADR이 2026-10-25 값(30GB)을 기록한다.
