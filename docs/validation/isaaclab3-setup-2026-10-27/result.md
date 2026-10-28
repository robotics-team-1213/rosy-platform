# Lab 3 분리 환경의 설치 검증과 복구 기록

2026-10-27 KST. 기존 SDK 5.1 운영 연결과 ML 환경을 유지하고 별도 Lab 3 환경을 설치했다. 최초 설치 후 결과와 이후 복구 결과를 구분해 남긴다.

## 최초 구성에서 확인한 사실

공식 IsaacLab v3.0.0 commit은 `e3f7d9ff1f5d7f8280de3ece9000b7117f66bcf4`다. 소스 변경은 pyproject.toml과 uv.lock에 한정했다. Newton의 NumPy는 2.3.5, Sim은 2.3.1이다.

- Newton: 의존성 207개 검사 통과. CUDA 텐서·역전파, NumPy·Numba·Pinocchio/Pink import와 CPU 순기구학, MJWarp Cartpole 환경 4개·최대 32 step 설정, PPO 환경 16개·2 iteration·seed 42를 실행했다. 각 프로세스 종료 코드 0, 512 transition과 새 checkpoint 2개, 종료 정리 성공을 기록했다.
- Sim: 292개 의존성 검사에 fsspec 2026.2.0 요구/2026.6.0 설치, urllib3 2.7.0 요구/2.8.0 설치 충돌이 남았다. CUDA·PhysX Cartpole 프로세스는 종료 코드 0이지만 진단 내부 정리 검사는 실패했다. 이후 별도 관측에서 작업 소유 cgroup 프로세스와 GPU compute 점유가 없었다. 원래 실패를 통과로 바꾸지 않았다.
- audit: 패키지·Git 변경 범위·기존 binding 보존을 조회했으나 전체 preset 열거가 120초 제한에 걸려 전체 상태는 실패다.
- 기존 SDK Python 3.11.17 / Sim 5.1.0.0 / Torch 2.7.0+cu128 / NumPy 1.26.0과 기존 ML Python 3.12.3 / Torch 2.11.0+cu128 / NumPy 2.5.2를 보존했다. 운영 binding 지문 유지도 확인했다. 드라이버는 580.178.04이며 교체하지 않았다.

최초 증거 ZIP SHA-256은 `7f05513ef4c16ad8754a557899df673448d354b3b3a841aaf6f4af50ee7108e3`다. 파일 80개, manifest 항목 78개와 CRC를 확인했다. Newton lock SHA는 `717cbd0ffec4c9bdb2a419aae3a1d7474d580ae4e128885572f0b5de98a8c7b9`, 최초 Sim 후보 lock SHA는 `933ec05e60a7c37d55b80eab27ceb53e8c62bb338984472ac81baea3c94a828b`다. ZIP은 [Confluence 실행 기록](https://winna1492.atlassian.net/wiki/spaces/SP/pages/9764866)에 첨부했고 다운로드 해시를 확인했다. checkpoint 바이너리는 포함하지 않으며 일회성 run 정리 후 원격 보존을 보장하지 않는다.

## 후속 조사에서 정정한 원인

설치된 Torch 2.11.0+cu130 wheel의 실제 요구는 `fsspec>=0.8.5`다. Lab 상위 설정의 “Torch가 2026.6.0 이상을 요구한다”는 주석을 그대로 인용한 최초 보고서는 잘못됐다. SDK가 요구하는 fsspec 2026.2.0으로 되돌릴 수 있는지 lock과 실제 실행을 검증한다. urllib3 보안 수정 하한은 유지한다. SDK의 정확한 pin과 보안 수정판을 함께 수용하려면 공식 수정판 또는 명확히 표시된 로컬 배포 수정이 필요하다.

정리 검사 원인은 아직 확정하지 않았다. 새 run에서 GPU 조회 결과와 소유 cgroup 프로세스를 분리해 관측한다. 의존성·runtime·종료 정리·장치 수용은 각각 판정한다.

## 범위 제한

OMX 학습·일반화, ROS clock/TF, 카메라·RTX 센서, 사용자 맵, 장시간 안정성, 실물 동작은 이 설치 검증의 대상이 아니다. 기존 SDK 연결도 전환하지 않았다. 호스트 재시작은 관측했지만 원인을 확인하지 않았다.
