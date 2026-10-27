# Lab 3 복구와 두 호스트 학습 검증

2026-10-27 동결 실행 기록. [최초 실패 기록](../isaaclab3-setup-2026-10-27/result.md)은 보존한다. [상세 보고서와 정제 증거](https://winna1492.atlassian.net/wiki/spaces/SP/pages/10190849)는 Confluence 후속 페이지에 있다. 호스트 배치 결정은 [D-897](../../adr/D-897-dual-host-offline-simulation-learning.md), 재구성·실행 안내는 [Lab 3 README](../../../learning/envs/isaac/lab3/README.md)를 따른다.

## 두 PC에서 같은 Newton 환경으로 실제 학습했다

AI PC와 모델 PC는 서로 다른 물리 호스트·GPU다. 둘 다 Ubuntu 24.04.5, RTX 5080 Laptop 16GB, RAM 약 32GB, Python 3.12.3이다. Isaac Lab v3.0.0 upstream commit은 `e3f7d9ff1f5d7f8280de3ece9000b7117f66bcf4`다. 같은 source 설정·lock을 AI PC로 전송한 뒤 별도 venv를 설치했다. 두 GPU의 메모리를 합치거나 DDP를 구성하지 않았다.

Newton lock SHA-256은 `717cbd0ffec4c9bdb2a419aae3a1d7474d580ae4e128885572f0b5de98a8c7b9`다. 양쪽 의존성 검사 207개가 통과했다. Torch 2.11.0+cu130, NumPy 2.3.5, Warp 1.17.0, Newton 1.6.1, MuJoCo-Warp 3.12.0, RSL-RL 5.5.1을 사용했다.

| 관측 | 모델 PC | AI PC |
|---|---|---|
| 최종 run | `isaac3-parallel-model-84487c` | `isaac3-parallel-ai-756371` |
| seed / 규모 | 42 / 64환경·64iteration·rollout 16step | 43 / 동일 규모 |
| 실제 learn 시작 UTC | 06:09:51.781811 | 06:09:51.781695 |
| 실제 learn 종료 UTC | 06:10:01.677296 | 06:10:00.238945 |
| 학습 산출물 | 65,536 transitions·새 checkpoint 3개 | 동일 |
| CUDA·FK / zero / train | 모두 exit 0 | 모두 exit 0 |
| zero·train 종료 정리 | 모두 clean | 모두 clean |

NTP 동기화와 실제 `OnPolicyRunner.learn` 진입을 확인한 후 같은 미래 epoch의 barrier를 전달했다. 실제 학습 구간의 교집합은 **8.457134초**다. 준비·barrier 대기 시간은 제외했다. 학습 성능·수렴·처리량 벤치마크로 해석하지 않는다.

사용자가 승인한 검증 중에만 AI의 `rosy-v11-sam-worker.service`와 `rosy-ollama.service` user unit을 일시 중지했다. 원래 상태를 배타적으로 저장하고 정상·예외·종료 시 복원하도록 구성했다. 최종 restore와 별도 재조회에서 둘 다 active/running/enabled였다. 미래 작업의 무기한 중지 권한을 뜻하지 않는다.

## SDK 의존성과 실행을 복구했다

실제 Torch wheel 요구는 fsspec>=0.8.5다. 최초 보고서에서 Lab override의 >=2026.6.0을 실제 Torch 요구로 해석한 설명을 정정한다. SDK와 같은 fsspec==2026.2.0으로 override를 조정했다.

원본 kernel의 urllib3==2.7.0 고정과 Lab의 >=2.8.0 요구는 별도 로컬 wheel `6.2.0.0+rosy.1`로 구분했다. 원본 SHA·RECORD를 검증하고 METADATA·dist-info 이름·RECORD·출처 JSON만 바꿨다. 감사에서 runtime 파일 3,325개가 원본과 일치했다. 기존 SDK 5.1 binding·ML venv·Newton SETUP와 lock은 보존됐다.

최종 SDK run `isaac3-sdk-1c16f5`에서 의존성, CUDA, PhysX Cartpole 4환경·32step, fsspec/Torch 입출력, PPO 16환경·2iteration을 모두 exit 0으로 완료했다. 새 checkpoint 2개, zero 후 1.922초·train 후 0.848초의 clean을 확인했다. 환경의 ACCEPTANCE는 `local_compatibility_installation_smoke_passed`, `production_accepted=false`다.

SDK 종료 직전에는 Torch 2.11.0+cu130·NumPy 2.3.1이 관측됐고 top-level urllib3는 로드되지 않았다. 별도 입출력 프로세스에서 fsspec 2026.2.0·urllib3 2.8.0을 직접 확인했다. Nucleus registry용 urllib3 2.7 번들은 보존됐으므로 SDK 전체 보안 패치로 주장하지 않는다.

## 실패를 보존하고 새 실행으로 확인했다

- 첫 SDK 복구는 대형 확장 캐시 전송 중 1,800초 제한을 넘었다. 새 run `isaac3-model-2083ad`에서 같은 source·lock·wheel로 설치를 완료했다.
- 최초 종료 검사는 telemetry transmitter가 약 2.06초 남아 실패했다. 최대 30초 동안 실제 소유 cgroup·GPU를 관측하도록 고쳤다. cgroup을 읽지 못하거나 GPU 조회가 실패하면 통과시키지 않는다. 관련 회귀를 원격 RED→GREEN으로 확인했다.
- AI의 빈 placement mutex mode 0664는 일반 GPU lock과 구분했다. 정확한 경로에만 읽기 전용 flock과 소유권·부모·world-write 금지 검사를 적용했다. 일반 work/GPU lock 검증은 유지했다.
- 다음 AI zero 실행은 shared Omniverse Hub가 남아 정리 실패했다. 서비스 복원·소유 scope 종료를 확인하고 새 run에서 프로세스 환경에만 `OMNICLIENT_HUB_MODE=disabled`를 적용했다. [NVIDIA 문서](https://docs.omniverse.nvidia.com/kit/docs/client_library/latest/index.html#hub)의 shared 동작과 일치한다. 전역 Hub·제품 설정을 변경하지 않았다.
- 첫 SDK 모듈 관측은 Kit의 process-ending close로 atexit 파일이 없어 실패했다. 원래 simulation context 종료 직전 관측으로 옮겨 정상·예외 close 순서 자기 검사와 독립 검토를 거친 뒤 새 run을 통과했다.
- 전체 preset 조회의 최초 120초 초과는 보존했다. Cartpole로 좁힌 조회는 Newton 28.59초·Sim 32.32초에 성공했다.

## 소스와 실행 증거의 대응

SDK lock SHA-256은 `d0475ad52dd5ab77ee559cb7e5c0734ad56fc65a6edeb773f7d2022c0bf038ce`다. 원본 kernel SHA는 `f6b49ed4fa67569c90d69c835e7700bb339b57ce67aecfe6b5b76c52b0c0b3b4`, 로컬 wheel SHA는 `d865768dcaeaece10fa56c5cdc7c9c167e9fbcb956f125f1225b2bf541743c44`다.

실행한 cleanup.py SHA는 `49fdd947a367dd49be570f50fe2fae55f6cffb06ed7f2c8bf485b54cae2df814`, kernel_wheel.py SHA는 `a5d134a156841d7df87941807128be934af5ba85a8aff2cc165d32104ef5f05d`이며 커밋 `ad878b235d`의 바이트와 같다. 이후 로그 구획 이력을 정리했지만 구현 바이트는 바꾸지 않았다. 정제 ZIP manifest는 원본·정제본 SHA를 구분하고 CRC와 항목별 SHA를 검증했다.

| Confluence 첨부 | SHA-256 |
|---|---|
| `repair-evidence-20261027-v2.zip` | `0bb5ab84646e7ba7b6ac899dc82bcbff7f768f8b09c313334c0344fefb17e8f9` |
| `parallel-model-evidence-20261027-v2.zip` | `40faf8d4ff3b11dde9ec705c9b2d745d145e359e68fdcc4f40529547863ebf27` |
| `parallel-ai-evidence-20261027-v2.zip` | `3fb1fa0a10e414d679d1478b3b115caa6f6a7ef24dcbcd903dab8dd13c6a8212` |

Confluence 후속 페이지 10190849의 본문·계층·아이콘 속성·첨부 다운로드 SHA와 이전 두 페이지의 이력 보존을 API 재조회로 확인했다. 브라우저 시각 검사는 하지 않았다.

기본 설치·동시 실행 검증은 OMX task, 모방학습 데이터, 물체 위치·크기·높이 일반화, ROS·카메라·실물 수용을 대신하지 않는다. 운영 SDK 교체나 실제 로봇 동작은 수행하지 않았다.
