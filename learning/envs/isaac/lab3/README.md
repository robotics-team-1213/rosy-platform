# Lab 3 분리 학습 환경

AI PC·모델 PC의 수동 Lab v3.0.0 환경은 기존 SDK 5.1 실행기와 별개다. 두 호스트는 [D-897](../../../../docs/adr/D-897-dual-host-offline-simulation-learning.md)의 격리된 오프라인 학습 범위에서 독립 작업을 실행한다. 이 폴더의 도구는 환경 정비용이며 제품 시나리오·운영 SDK 연결·로봇 명령을 추가하지 않는다.

| 환경 | 위치 | 2026-10-27 최종 검증 |
|---|---|---|
| Newton / MJWarp | 두 PC의 `~/rosy-test/venvs/isaaclab-3.0.0-newton/` | 의존성 207개·CUDA·Cartpole·PPO 동시 실행·정리 통과 |
| Sim 6.2 로컬 호환 환경 | 모델 PC의 `~/rosy-test/venvs/isaaclab-3.0.0-sim62/` | 의존성·CUDA·PhysX Cartpole·PPO·정리 통과 |

공통 소스는 IsaacLab Git v3.0.0 commit `e3f7d9ff1f5d7f8280de3ece9000b7117f66bcf4`, Python 3.12.3, Torch 2.11.0+cu130이다. Newton은 Warp 1.17.0 / Newton 1.6.1 / MuJoCo-Warp 3.12.0 / RSL-RL 5.5.1 / NumPy 2.3.5다. Sim은 NumPy 2.3.1을 사용한다. 각각 source/와 .venv/를 함께 보존한다.

공식 설정에서 NumPy dependency와 override를 조정하고 다시 잠갔으므로 수정 없는 GA 설치는 아니다. Sim 후보는 registry와 실제 SDK robot wheel의 Requires-Dist 차이를 Lab dependency-metadata로 보정했고 GPU onnxruntime만 설치했다. 후보 lock은 Linux x86_64 전용이다. 원본 upstream.*와 변경 지문은 환경에 보존한다.

설치·GPU 작업은 별도 운영 저장소 `rosy-ops/docs/lab-host-storage.md`의 디스크 게이트, 기존 자원 예약, work/GPU lease, 새 run과 소유 프로세스 확인을 적용한다. 실제 호스트 선택은 기존 `tools/remote/remote_isaac.py`에서 model·ai 역할을 명시한다. AI의 추론 서비스는 첫 검증에서 사용자가 승인한 범위로만 중지·복원했다. 미래 학습에서 같은 GPU와 경합하면 별도 배치·중지 승인을 확인한다. 실행·중지·제품 결과 회수는 [기존 운영 안내](../../../../docs/deployment/isaac-experiment-runs.md)를 유지한다.

초기 실행 증거와 남은 범위는 [검증 기록](../../../../docs/validation/isaaclab3-setup-2026-10-27/result.md)을 따른다. 원본 정제 로그·lock·설정 증거 ZIP은 [Confluence 구성 기록](https://winna1492.atlassian.net/wiki/spaces/SP/pages/9764866)에 첨부했다. 원시 로그·wheel·checkpoint·계정·호스트 정보는 공개 Git에 넣지 않는다.

복구와 두 PC의 실제 learn 구간·서비스 복원은 [후속 검증 기록](../../../../docs/validation/isaaclab3-repair-2026-10-27/result.md), 상세 정제 증거는 [Confluence 후속 보고서](https://winna1492.atlassian.net/wiki/spaces/SP/pages/10190849)를 따른다. `SETUP.json`은 Newton 설치, `COMPATIBILITY.json`은 SDK 의존성 복구, `ACCEPTANCE.json`은 SDK 기본 실행 결과를 구분한다.

기본 학습 성공은 설치 연결 검증이며 OMX task, 모방학습 데이터, 물체 위치·크기·높이 일반화, ROS·카메라·실물 수용은 별도다. 전체 preset 열거는 최초 audit에서 120초 제한에 걸려 빠른 조회로 권장하지 않는다.

## 두 PC에서 독립 학습하기

각 호스트의 source·venv·lock을 함께 보존한다. 서로 다른 seed·작업 디렉터리·로그·checkpoint를 사용하며 두 16GB GPU의 메모리가 합쳐지는 것은 아니다. 모델 PC의 기존 평가·등록 소유권은 유지한다. 자원을 확보하고 기존 work/GPU lease를 획득한 제한 unit 안에서 다음 CLI를 사용한다. ISAAC3_ENV는 위 Newton 환경의 절대 경로이며 실행 cwd는 새로 만든 소유 run이다.

```bash
OMNICLIENT_HUB_MODE=disabled "$ISAAC3_ENV/.venv/bin/isaaclab" train \
  --task Isaac-Cartpole --rl_library rsl_rl --num_envs 64 \
  --max_iterations 64 --seed 42 --viz none --device cuda:0 physics=newton_mjwarp
```

AI PC에서는 seed 43을 사용했다. 실제 업무 학습에서는 task·분포·평가 조건에 맞게 예산을 정한다. Newton 설치 검증의 64 iteration은 학습 성능·일반화 달성 기준이 아니다. CLI 작업 목록은 `isaaclab list_envs --keyword Isaac-Cartpole --show_presets`로 범위를 줄여 확인했다.

`OMNICLIENT_HUB_MODE=disabled`는 이 작업 프로세스에만 적용한다. AI PC의 Launcher에 설치된 shared Hub가 zero-agent 종료 후에도 같은 cgroup에 남는 현상을 재현했다. [NVIDIA 문서](https://docs.omniverse.nvidia.com/kit/docs/client_library/latest/index.html#hub)의 shared 모드는 Hub를 자동 종료하지 않는다. 전역 설정·다른 소유자의 Hub는 건드리지 않는다. 이 설정의 검증과 shared-cache 통합 수용은 구분한다.

## SDK 호환 패치의 경계

설치된 Torch 2.11.0+cu130 wheel은 fsspec>=0.8.5를 요구한다. Lab의 fsspec>=2026.6.0 override를 SDK와 같은 fsspec==2026.2.0으로 바꾼다. 상위 주석보다 실제 선택한 wheel metadata를 기준으로 한다.

SDK kernel은 urllib3==2.7.0을 고정하지만 Lab은 [보안 수정판 2.8.0](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) 이상을 요구한다. `kernel_wheel.py`는 원본 wheel의 SHA와 모든 RECORD 항목을 검사하고, urllib3==2.8.0을 지정하는 **로컬 버전 6.2.0.0+rosy.1**을 새 파일로 만든다. SDK 런타임 payload는 그대로 보존하고 METADATA·dist-info 이름·RECORD·출처 JSON만 바꾼다. 원본 파일과 기존 출력은 덮어쓰지 않는다. wheel 바이너리는 호스트의 sdk-compat/에만 두며 공개 저장소에 배포하지 않는다.

입력은 [PyPI의 공식 kernel 6.2.0.0 Linux x86_64 wheel](https://pypi.org/project/isaacsim-kernel/6.2.0.0/#files)이며 SHA-256은 `f6b49ed4fa67569c90d69c835e7700bb339b57ce67aecfe6b5b76c52b0c0b3b4`다. ROSY_REPO는 현재 저장소 checkout, ISAAC3_ENV는 위 Sim 환경의 절대 경로로 지정한다. 승인된 정비 작업의 예산 안에서 다음 도구로 재구성한다.

```bash
python3 "$ROSY_REPO/learning/envs/isaac/lab3/kernel_wheel.py" \
  "$ISAAC3_ENV/sdk-compat/vendor/isaacsim_kernel-6.2.0.0-cp312-none-manylinux_2_35_x86_64.whl" \
  "$ISAAC3_ENV/sdk-compat/wheels" \
  --source-sha256 f6b49ed4fa67569c90d69c835e7700bb339b57ce67aecfe6b5b76c52b0c0b3b4
```

Lab source의 isaacsim extra에 `isaacsim-kernel==6.2.0.0+rosy.1`을 추가하고 tool.uv.sources에 kernel의 `../sdk-compat/wheels/<생성 wheel 이름>` path를 지정한다. 기존 NumPy·robot GPU metadata·Linux x86_64 제한과 urllib3 보안 하한을 유지한다. `/usr/bin/python3`를 지정해 lock을 다시 만들고 `uv sync --frozen --no-dev --extra isaacsim`, 같은 환경의 `uv pip check`를 실행한다. 선언이 맞아졌다는 사실과 runtime 수용은 별도 검사다.

이 패치는 NVIDIA 공식 수정판이 아니다. 새 SDK가 나오면 원본 pin과 런타임을 재검증하고 해당 패치를 제거할지 결정한다. 기존 후보 설정과 lock은 pre-repair.*로 보존한다. 복구를 되돌릴 때는 해당 환경을 사용하는 작업의 종료를 확인하고 현 설정·증거를 회수한 뒤, 보존한 두 파일로 되돌려 frozen sync한다. 이 경우 최초 의존성 충돌도 다시 생기므로 통과 환경으로 표시하지 않는다.

## 종료 검사

Sim 프로세스 종료 직후 telemetry transmitter가 잠시 남을 수 있다. `cleanup.wait_for_cleanup()`은 소유 cgroup과 GPU 조회를 최대 30초 반복 관측한다. 소유 프로세스·GPU 점유가 남거나 GPU 조회가 실패하면 통과하지 않는다. 프로세스를 강제 종료하거나 빈 GPU 결과로 대체하지 않는다. 실제 관측 결과는 실행 보고서에 보존한다. 이 도구는 별도 설치 검증용이며 기존 제품 실행기의 종료 판정은 변경하지 않는다.
