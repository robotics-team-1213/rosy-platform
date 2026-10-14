# OMX 모방학습 시뮬레이션 준비

2026-10-14. branch `feat/omx-sim-preparation`. 실물 연결 전 Pilot 조작과 시연
수집을 재현할 수 있게 기존 경로를 정리한다. 새로운 실물 driver나 API를 만들지 않는다.

## 조사한 코드와 선택

| 경로 | 실제 역할 | 이번 준비 범위 |
|---|---|---|
| `deploy/robot/omx/stack.lock.yaml`, `Dockerfile`, `patches/` | ROBOTIS 5.1.2 고정 소스와 Jazzy 이미지, action-only SIM 패치 | 기존 pin과 패치를 유지한다 |
| `integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf` | 작업대·전면 카메라를 포함한 Gazebo world | Pilot 녹화 연습의 1차 환경 |
| `middleware/devices/omx/adapter/omx_adapter/pilot_sim_server.py` | SIM 전용 HTTP, pairing, 관절 owner, 카메라·녹화 결선 | 기존 서버 재사용 |
| 같은 디렉터리 `pilot_sim_runtime.py`, `ros_runtime.py` | lease와 goal 중재, FollowJointTrajectory 결과 | 브라우저 → owner → Gazebo → readback |
| `deploy/robot/omx/probe_pilot_sim_http.py`, `probe_pilot_recording.py` | 관절·그리퍼·취소, 영상 녹화·lease 만료 시험 | 각자 새 pairing 세션에서 실행 |
| `learning/curation/omx/lerobot_export.py` | complete 원본 검증, LeRobot v3 작성·실제 reader 재독출 | SIM rad 전용 오프라인 export |
| `learning/training/omx/act_job.py`, `act_inference_replay.py` | train/eval 분리, ACT 저장·재적재, offline 평가·재생 | 학습 준비와 실제 SIM 정책 실행을 구분 |
| `learning/envs/isaac/prepare_omx_urdf.py`, `import_omx.py` | pinned OMX-F/L geometry·joint의 USD import | 후속 모델 검증; 조종기·카메라·학습 환경은 아님 |
| `deploy/robot/omx/run_cell_sim.sh`, `probe_cell_transfer.py` | 작업셀 transfer 시뮬레이션 | 별도 owner이므로 Pilot과 동시 실행하지 않음 |

Gazebo를 먼저 쓴다. 기존 Pilot·영상·녹화 경로와 실제 실행 이력이 있다.
Isaac은 학습 환경 확장에 유용하지만 OMX controller/camera/task가 아직 연결되지
않았다. 별도 가짜 관절 simulator는 이 경로의 ROS action·영상 동기화를 검증하지 못한다.

공식 문서 재확인:

- [ROBOTIS Gazebo 안내](https://docs.robotis.com/docs/systems/omx/simulation/gazebo/)는
  현재 `omx_f_gazebo.launch.py`와 Zenoh 구성을 안내한다. 현재 저장소의 고정
  5.1.2 follower-AI launch/CycloneDDS와 다르다. 최신 안내를 그대로 덮어 적용하지 않는다.
- [LeRobot v0.4.4 OMX follower 코드](https://github.com/huggingface/lerobot/blob/v0.4.4/src/lerobot/robots/omx_follower/omx_follower.py)는
  Dynamixel 버스를 직접 소유한다. body는 설정에 따라 정규화 또는 degree이고
  gripper는 0..100이다. Gazebo의 ROS 관절 rad와 자동 호환되지 않는다.
- [LeRobot OMX 예제](https://github.com/huggingface/lerobot/tree/main/examples/omx)는
  물리 setup의 예제다. 이 예제 자체를 ROSY SIM adapter로 취급하지 않는다.

## 구현과 확인 순서

1. 장치 변수 없는 독립 `compose.pilot-sim.yaml`: vendor build → Pilot build →
   localhost HTTP, 격리 network, read-only source, 별도 recording volume.
2. 원격 PC 배치·자원 예약 후 clean committed source로 실행한다. 노트북과 현장 PC는 제외한다.
3. Pilot 조작과 녹화 probe는 각각 새 서버 pairing으로 실행한다. HTTP ready만으로
   완료하지 않고 ROS terminal·관절 readback·complete 영상·lease expiry를 읽는다.
4. 원본을 보존하고 complete episode만 별도 LeRobot 환경에서 export/reload한다.
   episode 단위 train/eval을 분리한다. 합성·SIM과 native 실물 데이터를 섞지 않는다.
5. 동작 결과·이미지 ID·source/world/vendor revision·실패 원본을 보존한다.
   실제 정책의 closed-loop 집기 성공은 별도 수용으로 남긴다.

실행 명령의 단일 안내는 [OMX README](../../deploy/robot/omx/README.md#재현-가능한-pilot-sim-준비)다.

## 이번 증거와 보류

- 독립 Compose의 실제 `docker compose config --format json` 해석 성공. Docker
  daemon이나 Gazebo를 노트북에서 실행하지 않았다.
- `check_vendor_patches.py`가 고정 vendor 파일을 받아 4개 패치를 Dockerfile
  순서대로 적용하고 Python/YAML/XML을 검사했다. exit 0. 이미지 빌드 증거는 아니다.
- 원격 배치 첫 확인은 SSH 시간 초과였으나 runner 재시도에서 연결이 복구되어
  기존 배포·vendor lock baseline 19개가 통과했다(NEW 0). 재확인한 비현장 PC는
  예약을 뺀 가용 메모리가 SIM 최소 8 GiB에 못 미쳤다. 원격 회귀와 별개로
  이미지 build·live ROS-SIM은 아직 미확인이다. 자원 기준을 낮추지 않는다.
- OMX-F/L은 `prepare_omx_urdf.py`로 vendor manifest·관절·mesh 경로 검사 후
  X: 세션 export에 실제 URDF를 생성했다. Isaac SDK/USD import를 실행한 것은 아니다.
- 구현 commit `91995a99e`의 새 Compose·기존 OMX·문서 배치·harness 원격 시험은
  129 passed, NEW 0이다. 독립 리뷰의 새 터미널 SHA 누락과 build 자원 상한
  오해를 수정한 뒤 추가 소스 차단 사항 없음으로 재검토했다.
- 모델 PC의 Docker version/image 읽기 요청은 `/var/run/docker.sock` 접근 거부로
  실패했다. 설치·그룹·권한을 변경하지 않았다. 운영자가 준비한 비현장 build
  환경과 사용 가능한 Docker context, 여유 자원을 확인한 뒤 live 실행을 재개한다.
- 원격 로그: `X:/DevTemp/projects/rosy-platform/2026-10-14--035840--omx-sim--9a5dea/logs/preparation/run-1.txt`.
  Compose 해석 결과와 누락 SHA 거절은 같은 세션 `evidence/`, 검사한 URDF는 `export/`에 있다.
  URDF의 mesh URI는 생성 host의 절대 경로이므로 다른 host에서는 그 checkout에서 재생성한다.
- 이전 [6개 Gazebo 시연·ACT 평가](../validation/omx-diverse-sim-act-2026-10-04.md)는
  재사용 가능한 설계 근거다. 당시 ACT가 상수 기준보다 나빠 reject였으며 현재
  commit의 새 실행 성공이나 정책 집기 성공으로 재표시하지 않는다.

미정인 실물 PC, joint/camera 보정, HF 계정과 Spaces의 재개 조건은
[D-756](../adr/D-756-omx-imitation-preparation-and-resumption-gates.md)에 유지한다.
새 원격 SIM 실행은 host 연결·가용 자원·Docker와 이미지 확인부터 재개한다.
