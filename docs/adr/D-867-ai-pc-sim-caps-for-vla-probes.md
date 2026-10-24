## D-867 시뮬레이션 실행 상한을 올린다: AI PC 12코어·10GB, 모델 PC 16코어·10GB

**Status:** Accepted (2026-10-25, 사용자 결정 「한도 올리고 처리해」). D-571 §4의 상한 표를 바꾼다. 배치 규칙과 관제 PC 제외는 그대로다.

**관련:** D-571 §4 · D-866 · D-864 §5

### Context

- D-571은 AI PC를 RAM 15GB 공용 PC로 보고 실행 하나당 4코어·4GB로 묶었다.
- 2026-10-25 `free -g`·`nproc` 확인 결과 AI PC는 RAM 30GB(사용 6GB, 가용 24GB), 24코어다. 모델 PC도 RAM 30GB, 24코어다.
- 같은 날 P0 실행에서 6코어 상한으로는 Gazebo(카메라 2대), CORE, Fleet, SmolVLA가 한 실행에 들어가지 못했다. headless Gazebo는 기본으로 Mesa EGL을 잡아 카메라를 CPU로 그렸다(`__EGL_VENDOR_LIBRARY_FILENAMES`로 NVIDIA를 지정하면 경고가 사라짐). 그 뒤에도 궤적이 실제 시간 감시에 걸려, 시뮬레이션이 실시간보다 느린 것으로 보였다.
- D-866 P0은 Gazebo, CORE, Fleet, SmolVLA 추론 자식 프로세스를 같은 PC(D-795)에서 한 실행으로 돌린다. SmolVLA 기본 모델은 GPU에 올라가도 호스트 메모리를 수 GB 쓰므로 4GB 상한을 넘을 수 있다.

### Decision

- `tools/remote/remote_sim.py`의 상한을 AI PC `cpus=12`, `mem_gb=10`, 모델 PC `cpus=16`, `mem_gb=10`으로 한다. AI PC 코어 상한이 모델 PC보다 작다는 기존 시험 조건은 유지된다.
- 상한은 여전히 `systemd-run --scope`의 `MemoryMax`·`CPUQuota`와 `nice -n 10`으로 건다. 공용 PC의 다른 사용자 작업 보호 규칙(D-571)은 그대로다.

### Consequences

- AI PC에서 VLA를 포함한 Gazebo 실행이 한 번에 쓸 수 있는 자원이 늘어난다. 같은 PC의 다른 작업이 쓸 여유는 그만큼 줄어든다.
- D-571 §1 표의 AI PC RAM 15GB는 실제와 다르다. 이 ADR이 2026-10-25 값(30GB)을 기록한다.
