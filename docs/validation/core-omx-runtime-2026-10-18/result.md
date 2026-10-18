# CORE–LeRobot 전체 연결 재점검

2026-10-18. 실제 별도 LeRobot 프로세스에서 loopback CORE HTTP를 거쳐 native ROS
Action 결과와 disconnect 정지까지 연결했다. 운영 프로필·Fleet 장치 lease 전달·학습
모델 추론·Gazebo/실물 이동을 완료했다는 뜻은 아니다.

## 확인한 운영 공백

| 경로 | 코드에서 확인한 상태 |
|---|---|
| CORE 기동 | `core/node.py`가 `CoreServices.build` 후 앱을 만든다. `arm_policy`는 기본 `None`이며 생산 조립이 없다 |
| Fleet lease 발급 | `operations/fleet/fleet/server/missions/policy_governance.py::issue_lease`는 이미 있다. `clock=fleet_wall_ns`, `device_delivery=not_connected`를 반환한다 |
| 장치 전달 | 위 lease를 장치의 steady clock·owner session·AttemptIdentity에 검증하여 연결하고 갱신·폐기하는 소비자가 없다 |
| 기존 SIM owner | `run_cell_owner.py`는 sim clock과 rule-based/Pilot owner다. 정책 binding은 dedicated learned_policy·steady runtime을 요구한다 |
| 실물 owner | `run_hardware_owner.py`는 rule_based만 허용하고 `OwnerPolicySession`도 SIM만 받는다 |

따라서 단순히 `arm_policy` 설정을 켜거나 Fleet wall-clock 만료값을 로컬 monotonic
lease에 복사하면 안 된다. 승인된 workcell·policy가 없다는 사용자 답변도 그대로다.
CORE는 외부 접점이며 OMX owner가 최종 관절 writer다. 둘을 합치지 않았다.

## 이번에 연결한 실행

`test_core_arm_lerobot_ros.py`는 기존 native session fixture를 재사용한다.

1. 별도 LeRobot 0.4.4 프로세스를 미리 적재한다. ROS를 import하지 않았는지 검사한다.
2. 원래 시계·lease·카메라 시각을 유지한 watchdog-bound SIM session을 CORE 앱에 넣는다.
3. 임시 loopback socket의 uvicorn에 실제 SDK Robot이 접속한다. HTTP client 대역은 없다.
4. SDK가 받은 RGB 12 byte와 관절 값, 보낸 목표를 비교한다.
5. 실제 ROS ActionServer에 전달된 joint 이름·목표가 SDK의 값과 같은지 검사한다.
6. 원래 journal의 terminal SUCCEEDED를 기다린 뒤 SDK disconnect를 호출한다.
   `/arm/stop` 요청과 지속 정지 fence의 HOLD를 검사한다.
7. 자기 HTTP 서버·SDK subprocess·ROS executor를 닫는다.

cold SDK 적재를 lease 발급 전에 끝낸다. 이미 소비한 관측이나 lease의 시각을
새 시각으로 바꾸거나 정책 신선도 기준을 늘리지 않는다. SDK stdout에는 socket
receipt를 남기며 fixture credential은 출력하지 않는다.

## 실행 근거

로그 루트는 저장소 밖 `<system-temp>/rosy-omx-core-runtime/`다.

- RED commit `2fd2b168e8653797e7d168018f29453abdb3bc3a`: 교환 지점이 없어
  `core_client` unexpected keyword로 실패. `red/run-1.txt` SHA256:
  `90e1686ad9f9c846c7df18bad29b2b9b7bb9b4dbc16aac44486102aec0f71090`.
- 첫 GREEN commit `e81c3f1a484ab94a09821403499d5b8f938a128f`:
  원격 AI 시험 PC에서 socket wrapper 1 passed / 3 deselected / 0 skipped,
  내부 native case 1 passed. known failures 비교 NEW 0.
  `socket/run-1.txt` SHA256:
  `18d6a579ed13616ed039b5c283267756ba250039ccd80328c9dfddab61ed423b`.
- 첫 GREEN 후 ROS 수신 goal의 정확한 값 비교와 receipt stdout 보존을 보강했다.
  아래 전체 opt-in native 명령으로 새 커밋의 회귀를 검증한다. 위 GREEN 로그는
  이 보강분을 시험한 결과로 사용하지 않는다.

```text
python tools/remote/remote_pytest.py --log-dir <external>/final-native -- ROSY_OMX_NATIVE_RUNTIME_TESTS=1 test/test_omx_native_ros_runtime.py -s
python test/known_failures.py <external>/final-native/run-1.txt
python tools/land.py --tests auto
```

독립 계약 리뷰는 운영 자동 연결의 근거가 없으며 이 시험 조립이 현재 경계 안의
최소 검증이라는 점을 확인했다. 시험 통과·landing 여부는 각 실행 로그로 구분한다.

## 다음 운영 연결의 완료 조건

Fleet 승인 원장의 lease를 신뢰된 장치 전달 경로에서 검증하고, 원래 만료 시간보다
길어지지 않는 로컬 예산과 owner session·epoch·generation에 묶어야 한다. 갱신·승인
폐기·통신 단절이 실제 owner HOLD로 이어져야 한다. 그 owner의 관측·후보·정지 포트를
CORE에 연결한 뒤 승인된 설치 pin과 실제 적재 모델 digest를 대조한다.

실물로 가기 전에는 기존 승인·독립 정지·실측 profile·readback 수용이 필요하다.
이번 시험은 고정 목표를 쓰고, 인증 principal·정책·RGB·권한·ActionServer는 합성이다.
실제 CORE 노드의 설치 조립, 학습 모델의 action 생성, Gazebo 관절 이동·과제 성공,
실물 이동·물리 정지 증거는 없다. 시험 PC 자원 부족을 우회하지 않는다.
