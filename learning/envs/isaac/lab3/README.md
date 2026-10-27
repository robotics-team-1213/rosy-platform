# Lab 3 분리 학습 환경

모델 PC의 수동 Lab v3.0.0 환경은 기존 SDK 5.1 실행기와 별개다. 이 폴더의 도구는 환경 정비용이며 제품 시나리오·운영 SDK 연결·로봇 명령을 추가하지 않는다.

| 환경 | 위치 | 최초 구성 결과 |
|---|---|---|
| Newton / MJWarp | `~/rosy-test/venvs/isaaclab-3.0.0-newton/` | 의존성 207개·CUDA·Cartpole·PPO 기본 검증 통과 |
| Sim 6.2 후보 | `~/rosy-test/venvs/isaaclab-3.0.0-sim62/` | 의존성 충돌 2건·진단 정리 검사 실패, 복구 조사 중 |

공통 소스는 IsaacLab Git v3.0.0 commit `e3f7d9ff1f5d7f8280de3ece9000b7117f66bcf4`, Python 3.12.3, Torch 2.11.0+cu130이다. Newton은 Warp 1.17.0 / Newton 1.6.1 / MuJoCo-Warp 3.12.0 / RSL-RL 5.5.1 / NumPy 2.3.5다. Sim은 NumPy 2.3.1을 사용한다. 각각 source/와 .venv/를 함께 보존한다.

공식 설정에서 NumPy dependency와 override를 조정하고 다시 잠갔으므로 수정 없는 GA 설치는 아니다. Sim 후보는 registry와 실제 SDK robot wheel의 Requires-Dist 차이를 Lab dependency-metadata로 보정했고 GPU onnxruntime만 설치했다. 후보 lock은 Linux x86_64 전용이다. 원본 upstream.*와 변경 지문은 환경에 보존한다.

설치·GPU 작업은 별도 운영 저장소 `rosy-ops/docs/lab-host-storage.md`의 디스크 게이트, 기존 자원 예약, work/GPU lease, 새 run과 소유 프로세스 확인을 적용한다. 실제 호스트 선택은 기존 `tools/remote/remote_isaac.py`의 model 역할을 사용한다. 실행·중지·제품 결과 회수는 [기존 운영 안내](../../../../docs/deployment/isaac-experiment-runs.md)를 유지한다.

초기 실행 증거와 남은 범위는 [검증 기록](../../../../docs/validation/isaaclab3-setup-2026-10-27/result.md)을 따른다. 원본 정제 로그·lock·설정 증거 ZIP은 [Confluence 구성 기록](https://winna1492.atlassian.net/wiki/spaces/SP/pages/9764866)에 첨부했다. 원시 로그·wheel·checkpoint·계정·호스트 정보는 공개 Git에 넣지 않는다.

기본 학습 성공은 설치 연결 검증이며 OMX task, 모방학습 데이터, 물체 위치·크기·높이 일반화, ROS·카메라·실물 수용은 별도다. 전체 preset 열거는 최초 audit에서 120초 제한에 걸려 빠른 조회로 권장하지 않는다.
