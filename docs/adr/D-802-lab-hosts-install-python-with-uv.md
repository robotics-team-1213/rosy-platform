## D-802 실험실 PC의 Python 설치 도구는 uv 하나다 — host-state가 해시 고정 휠로 배포하고, 원격 도구는 pip·venv 대체 경로를 쓰지 않는다

**Status:** Proposed (2026-10-18, 사용자 결정 "uv로 하도록 규칙을 세워서, PC에도 바로 설치해서 운용 가능하도록"과 "PyPI 휠을 고정 설치"(2026-10-18)). [D-530](D-530-host-management-desired-state-and-guard.md)의 host-state와 [D-571](D-571-sim-ready-hosts-load-aware-placement.md)의 원격 시뮬 위에 선다.

### Context

2026-10-18 v2 SIM 한 바퀴 작업에서 같은 커밋이 PC마다 다르게 끝났다.

- `remote_pytest.py`와 `remote_sim.py`는 uv가 있으면 uv로, 없으면 `python3 -m venv`와 `python3 -m pip`로 의존성을 설치했다.
- uv는 PC마다 손으로 깔려 있었다. 모델 PC에는 `~/.local/bin/uv`가 있었고 AI PC에는 없었다. `python3-venv`는 AI PC에만, `python3-pip`은 재부팅 뒤 모델 PC에 손으로 설치될 때까지 어디에도 없었다.
- 재부팅한 모델 PC에서 시뮬이 `/usr/bin/python3: No module named pip`으로 시작하지 못했다. host-state의 `approval=sim` 목록에는 ROS·Gazebo 패키지만 있고 Python 설치 도구는 없었다.
- `/usr/local/sbin/rosy-host-state install`은 옆에 manifest 폴더가 없어 `FileNotFoundError`로 끝났다. 설치는 저장소에서 돌려야 하는데, 사본이 그것을 알려 주지 않았다.

### Decision

1. **실험실 PC(관제·모델·AI)의 Python 의존성 설치 도구는 uv 하나다.** `remote_pytest.py`는 `uv venv --seed`로, `remote_sim.py`는 `uv pip install`로만 설치한다. uv가 없으면 PC마다 다른 대체 경로로 가지 않고, 설치 명령을 알려 주며 실패한다.
2. **host-state가 uv를 배포한다.** 새 manifest 종류 `wheel-tool <name> <version> <sha256>`는 PyPI 휠 하나를 `pip install --no-deps --only-binary=:all: --require-hashes --target /usr/local/lib/rosy-tools/<name>-<version>`로 넣고 `/usr/local/bin/<name>`(uv는 `uv`, `uvx`)으로 연결한다. 해시가 맞지 않으면 설치하지 않는다. 버전을 올릴 때는 버전과 해시를 함께 바꾼다.
3. **승인 묶음 `approval=uv`.** 공통 manifest에 `approval=uv apt python3-pip`과 `approval=uv wheel-tool uv 0.12.22 <sha256>`을 둔다. `apt`처럼 `wheel-tool`도 승인 정책에서만 허용한다(타이머는 보고만 한다). 관제 PC도 같은 uv를 받는다. 시뮬 패키지가 아니므로 D-571의 "관제 PC에는 시뮬 패키지를 설치하지 않는다"와 충돌하지 않는다.
4. **설치는 저장소에서 한다.** `cd <checkout> && sudo python3 deploy/hosts/common/rosy-host-state install <role> --approve uv[,sim]`. `/usr/local/sbin` 사본은 `check`만 하고, `install`을 받으면 이 명령을 알려 주며 멈춘다.

### Consequences

- 새 PC나 재설치한 PC는 저장소 클론 하나와 위 명령 하나로 원격 시험·시뮬을 받을 수 있다.
- uv가 없는 PC는 원격 실행이 바로 실패한다. 조용히 다른 설치 경로를 타지 않는다.
- 기존 `~/.local/bin/uv`(관제 PC, 모델 PC)는 그대로 남지만 `/usr/local/bin/uv`가 PATH에서 먼저 잡힌다. 손으로 깐 사본은 소유자가 지운다.

### Validation

- `test/test_host_state.py`: uv 줄은 `--approve uv` 없이는 설치되지 않는다. 승인하면 해시 고정 pip 한 번과 `uv`·`uvx` 연결이 생기고, 그 뒤 점검은 깨끗하다. 승인 정책 없는 `wheel-tool` 줄은 거절된다. 설치된 사본의 `install`은 저장소 안내로 멈춘다. 공통 manifest의 apt 줄은 `python3-pip`(uv 묶음) 하나다.
- 2026-10-18 모델 PC에서 같은 pip 명령으로 임시 폴더에 설치했다: `uv 0.12.22`, `uv`·`uvx` 생성, PEP 668 거절 없음. 시스템에는 설치하지 않았다.
- 실제 PC 적용은 각 PC 소유자가 sudo로 한다(D-530 6항).
