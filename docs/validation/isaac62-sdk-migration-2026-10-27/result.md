# Isaac Sim 6.2 SDK 설치와 운영 전환

2026-10-27. 두 호스트의 Lab 3 학습 환경과 모델 PC의 기존 운영 실행기에 SDK 6.2를 연결했다. 최초 구성과 동시 Newton 학습은 [이전 기록](../isaaclab3-repair-2026-10-27/result.md)에 보존한다.

## 설치와 학습

두 PC는 IsaacLab v3.0.0 (`e3f7d9ff1f5d7f8280de3ece9000b7117f66bcf4`), Python 3.12.3, SDK 6.2.0.0, kernel 6.2.0.0+rosy.1, Torch 2.11.0+cu130, NumPy 2.3.1, fsspec 2026.2.0, urllib3 2.8.0을 사용한다. 환경은 각 호스트의 `~/rosy-test/venvs/isaaclab-3.0.0-sim62/`다. 기존 Newton과 SDK 5.1 설치를 보존한다.

모델 PC의 기존 PhysX·PPO 검증에 이어 AI PC도 의존성·CUDA 역전파·PhysX Cartpole·fsspec 저장/읽기·PPO 2 iteration을 모두 exit 0으로 통과했다. checkpoint 두 개와 두 단계의 소유 프로세스·GPU 정리를 확인했다. AI 검증 실행은 `isaac62-ai-verify-5c8dc8`이다. SAM·Ollama는 사용자 승인 범위에서 중지 후 active/running/enabled로 복원했고 후속 조회의 NRestarts는 각각 0이었다.

공식 kernel SHA-256은 `f6b49ed4fa67569c90d69c835e7700bb339b57ce67aecfe6b5b76c52b0c0b3b4`, 두 호스트가 공유한 정확한 호환 wheel SHA-256은 `d865768dcaeaece10fa56c5cdc7c9c167e9fbcb956f125f1225b2bf541743c44`, frozen lock SHA-256은 `d0475ad52dd5ab77ee559cb7e5c0734ad56fc65a6edeb773f7d2022c0bf038ce`다. AI의 독립 wheel 재생성은 ZIP timestamp 차이로 SHA가 달라져 거절됐으며, lock을 완화하지 않고 검증된 archive를 복사해 일치시켰다. SDK runtime payload와 Nucleus 사설 urllib3 2.7 bundle은 변경하지 않았다. 수정 없는 공식 GA 설치나 SDK 전체 보안 패치 완료로 표시하지 않는다.

## 운영 실행과 ROS

SDK 6.2 후보 binding의 기존 실행 관리자는 OMX import·관절·120프레임 검사를 통과했다. 실행 `34d75d8c7d725cc3a521f7c6e39deeaa`는 소스 `e78a636f85931e4bc3510f478c2d1744200d47a4`, 실행 `7ce11b0d27cb5ff3bbbda5dcf2915413`는 `611b1847a81f2ad4d1878e2afe4576413eaa8ddc`다. 둘 다 exit 0과 `OWNED_PROCESSES_EXITED_GPU_RELEASED`를 확인했다.

최종 제어 소스 `6df916084147ce51bb10b34e8339e302a88fdfe6`의 모델 PC ROS conformance는 `isaac62-ros-final-304dbb`에서 통과했다. 기존 완료된 Jazzy overlay를 재사용하고, 독립 localhost ROS domain에서 기존 shared layer와 SDK backend를 실행했다.

| 측정 | 결과 |
|---|---|
| failures | 빈 목록 |
| clock / joint 메시지 | 각각 678 |
| top / front 카메라 | 240×320, 각각 56프레임, 최소 4.5Hz 기준 통과 |
| 취소 전 / 후 이동 | 약 0.0297rad / 0rad |
| 취소 수락·확인 | 모두 true |
| 물체 drift | 두 물체 모두 0mm |
| real-time factor | 약 0.8045 |
| 소유 프로세스·GPU 종료 | 확인 |

같은 버전에서 초기 ROS 시험은 카메라와 토픽을 수신했지만 관절 이동량 0으로 실패했다. 새 URDF converter의 미선택 Physics variant를 live reference에서 physx로 선택하고, URDF에 없는 drive gain을 명시했다. 현대 Manipulator importer는 position target, stiffness 40, damping `2√40×0.5+0.3 ≈ 6.6246`을 사용한다. 이는 기존 MuJoCo servo 계수를 기준으로 한 시뮬레이션 설정이며 물리 엔진 전체의 동등성이나 실물 팔 보정값을 뜻하지 않는다. wheel·구형 importer 경로는 유지한다.

AI PC의 추가 ROS 시험 `isaac62-ai-ros-ccd75f`는 승인된 두 서비스 중지 후에도 외부 GPU 사용자가 남아 SDK 실행 전에 거절됐다. 외부 프로세스는 중지하지 않았다. 두 서비스 복원은 성공했다. 이 결과를 AI의 ROS conformance 통과로 표시하지 않으며, 앞서 통과한 AI PhysX·PPO 설치 검증과 구분한다.

## 기본 경로 전환

`isaac62-activate-57a6bd`는 기존 work/GPU lease 아래 원본 두 파일을 먼저 백업하고 `~/.config/rosy/isaac-sdk.json`과 `~/rosy-isaac-ready/sdk-path.txt`를 교체했다. 실제 두 경로와 인터프리터 SHA를 재조회해 SDK 6.2.0.0을 확인했다. 전환 명령·receipt 모두 성공했다.

| 파일 | 이전 SHA-256 | 전환 후 SHA-256 |
|---|---|---|
| SDK JSON | 59ee49538afa446324a59760fe09a7dec056e9b6344181b1fbb9a458354d8c77 | 92b75e4f93bf34e038a0e06a1e10090f9a695f32ba4cc3ad49840632eed64c78 |
| 직접 launcher pointer | b6d72d2144c5ae7e13f94f381c52c78320e7b1ad2db20bf2c1785bc258794522 | f82189f2e9a97ed5e16d2a331685644ba7008f6c0e4cf7dad92524847c7f7695 |

원본은 해당 소유 run의 `original-0`(launcher), `original-1`(JSON)에 mode 0600으로 보존한다. rollback도 같은 lease에서 실제 현재 SHA가 위 전환 값과 일치할 때만 원본을 복원하고 두 파일·기존 SDK 5.1 지문을 재확인한다. 외부 변경이나 마지막 receipt 실패가 있으면 실제 bytes를 먼저 대조하고 자동 덮어쓰기를 거절한다. 이전 SHA의 source binding을 수정하지 않는다. 새 기본값을 쓰는 별도 source binding의 CLI 확인은 후속 기록으로 결속한다.

## 소스 검증과 남은 범위

binding 정확 버전 허용, 명시적 Kit EULA, 선택 SDK의 ROS library 해석, PhysX variant, position drive, 예외 종류 기록을 회귀 검사했다. 최종 제어 소스 `6df916084147ce51bb10b34e8339e302a88fdfe6`의 전체 `learning/envs/isaac/test -q` 원격 실행은 exit 0, known_failures 비교는 0 new·0 known·0 flaky다. 실제 SDK/ROS 실행과 호스트 pytest의 증거를 구분한다.

초기 운영 UNKNOWN 1건과 generic 오류 조기 종료 1건의 정확한 원인은 미확정이다. 이후 성공으로 이 원인이 해결됐다고 주장하지 않는다. worker가 후속 실패의 예외 종류를 보존하도록 보강했으며 재발하면 해당 증거와 unit·GPU 관측을 함께 조사한다.

학습 정책·시연 데이터·물체 위치/크기/높이 일반화·카메라 좌표 정합·RGB 내용의 시각 품질·실물 이동·현장 수용은 이번 검사에 포함하지 않았다. 두 PC의 동시 PhysX PPO 수행도 이번 기록의 주장이 아니다. 이전 동시 학습 검증은 Newton 기준이다. 드라이버 변경·재부팅·제품 AI 등록소 신설·원격 push는 수행하지 않았다.

CE: 새 교훈 기록 — import 성공과 관절 제어 수용을 분리해야 했던 converter 변경은 [해결 기록](../../solutions/runtime-errors/isaac62-imported-articulation-with-zero-position-drive-2026-10-27.md)에 남긴다.
