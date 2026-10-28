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
새 시각으로 바꾸거나 정책 신선도 기준을 늘리지 않는다. pytest stdout에는 socket
receipt를 남기며 fixture credential은 출력하지 않는다.

## 실행 근거

로그 루트는 저장소 밖 `<system-temp>/rosy-omx-core-runtime/`다.

- RED commit `2fd2b168e8653797e7d168018f29453abdb3bc3a`: 교환 지점이 없어
  `core_client` unexpected keyword로 실패.
  `red/run-1.txt` SHA256: `90e1686ad9f9c846c7df18bad29b2b9b7bb9b4dbc16aac44486102aec0f71090`.
- 첫 GREEN commit `e81c3f1a484ab94a09821403499d5b8f938a128f`:
  원격 AI 시험 PC에서 socket wrapper 1 passed / 3 deselected / 0 skipped,
  내부 native case 1 passed. known failures 비교 NEW 0.
  `socket/run-1.txt` SHA256: `18d6a579ed13616ed039b5c283267756ba250039ccd80328c9dfddab61ed423b`.
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

## 최종 native 결과와 머지 차단

commit `c32f56b762`의 `fence-native/run-1.txt`는 domain199 wrapper 3개가
모두 통과했다(3 passed / 1 deselected / 0 skipped, 내부 7 cases).
socket receipt의 원래 command UUID는 `c92a4aa5-8269-411d-9d1c-1cad7dfab025`,
terminal status는 4이며, disconnect 뒤 `hold=local_stop_closed`,
`local_stop_open=false`였다. RGB와 실제 ROS 수신 목표 비교도 통과했다.
known failures 비교는 NEW 0이다.

반면 commit `58f86ced0d`의 전체 native 실행은 wrapper 3 passed / 1 failed였다.
기존 `test_slow_feedback_handling_cannot_starve_the_joint_state_subscription`가
`joint_state_stale`로 실패했다. 같은 commit에서 해당 domain113 wrapper를 단 한 번
분리했을 때는 내부 8 passed였지만, 변경 없는 main commit `ad2bfb3075`에서는
동일한 시험이 다시 실패했다(내부 7 passed / 1 failed). 따라서 **MAIN-RED**이며
분리 통과만으로 전체 검증이나 머지 가능 상태를 주장하지 않는다.

이 브랜치는 adapter/runtime 구현과 해당 기존 시험을 변경하지 않았다. 독립 검토에서
느린 sink가 owner lock을 직접 잡는 경로는 확인되지 않았다. 같은 executor의
ActionServer 실행, early-feedback 재생, live-feedback의 event-delivery 대기가
worker를 점유할 가능성은 있으나 기존 로그로 원인을 확정하지 못했다. 다음 진단은
최초 HOLD 시 publisher·intake·owner 전달 시각과 thread stack을 수집하는 것이다.
freshness 기준·thread 수·known failures·quarantine은 바꾸지 않았다.

`docs/reference/shared-checkout.md` 6절은 다음과 같이 정한다.
“그때는 자기 브랜치를 고치지 말고, 동료가 이미 고치는지 본 다음 main만 고치는
작은 fix/ 브랜치를 먼저 착지한다.” 이 기존 실패를 숨기고 이번 브랜치를 착지하지 않는다.

일반 affected 검사 첫 실행은 478 passed / 7 skipped / 3 failed였다. 세 실패는
이번 기록의 log 필수 항목 누락, 잘못 옮겨진 과거 log 행, 독립 줄에 둔 SHA256
표기였다. 원래 과거 행을 제자리에 복구하고 새 항목을 끝에만 추가했으며,
실제 로그 hash를 같은 줄의 SHA256 표기로 고쳤다. 검사기·baseline은 변경하지 않는다.

정정 commit `5d9fc07247`의 원격 최종 문서·구조·비밀·harness 검사는
**248 passed / 0 skipped / NEW 0**, 로컬 lint는 0 errors였다. c32f56b762 이후
이 검증을 수행한 commit까지의 변경은 `docs/logs.md`와 이 결과 문서뿐이다.
최종 결과를 적은 후속 문서 commit에서 native 전체가 통과했다고 주장하지 않는다.

- `fence-native/run-1.txt` SHA256: `1fc21a601818101717e51250daff927a08fbbb12fcaf9f4d3c9643b79fc255cd`.
- `main-native/run-1.txt` SHA256: `4871c568bcc22a182480c944f9ed351c0f531b809ffe47da89b51e5ea4187e9d`.
- `final-guards/run-1.txt` SHA256: `5d5595e2c2ba1c098540fcd64d24972d30650152c4026a985d7ec46c8e780e7a`.

이 기록 당시 공유 main은 `a2076ddd8d`로 진행됐으나, 재현 main commit 대비
변경 3파일에 adapter·native wrapper·의존성·conftest 수정은 없었다.

## 실제 Gazebo probe

모델 시험 PC의 자원이 확보된 뒤 기존 OMX vendor overlay와 새로 격리한 Gazebo를
기동했다. 저장소 밖 probe는 rule_based owner로 joint1 0.01 rad를 요청하고
후속 feedback의 이동량·목표 오차를 검사하도록 작성했다. CORE·학습 모델 시험은 아니다.

- `gazebo-model`: controller는 active였으나 probe가 system ROS clock을 사용해
  신선한 joint feedback 준비 단계에서 실패했다.
- `gazebo-clock`: 노드의 use_sim_time을 맞춘 뒤 submit이 HOLD로 거부됐다.
  이 실행은 원래 HOLD 원인을 별도로 출력하지 않아 원인을 확정하지 않는다.
- `gazebo-sim-clock`: 기존 cell owner처럼 owner_clock=sim과 wall bound를 함께
  사용했다. 목표 접수 뒤 `joint_state_stale` HOLD로 끝났다. 기본 freshness 0.5 s와
  timeout 4 s는 늘리지 않았다. 이동 readback 성공 조건까지 도달하지 못했다.

세 실패 로그를 모두 보존한다. 따라서 이번에도 **Gazebo에서 목표만큼 움직였다는
증거는 확보하지 못했다.** 명령 접수나 controller active를 실제 이동으로 바꾸어
기록하지 않는다. 각 scope는 종료됐으며 공유 서비스·실물 장치는 건드리지 않았다.

## 다음 운영 연결의 완료 조건

Fleet 승인 원장의 lease를 신뢰된 장치 전달 경로에서 검증하고, 원래 만료 시간보다
길어지지 않는 로컬 예산과 owner session·epoch·generation에 묶어야 한다. 갱신·승인
폐기·통신 단절이 실제 owner HOLD로 이어져야 한다. 그 owner의 관측·후보·정지 포트를
CORE에 연결한 뒤 승인된 설치 pin과 실제 적재 모델 digest를 대조한다.

실물로 가기 전에는 기존 승인·독립 정지·실측 profile·readback 수용이 필요하다.
이번 시험은 고정 목표를 쓰고, 인증 principal·정책·RGB·권한·ActionServer는 합성이다.
실제 CORE 노드의 설치 조립, 학습 모델의 action 생성, Gazebo 관절 이동·과제 성공,
실물 이동·물리 정지 증거는 없다. 기존 main의 ROS 신선도 실패와 Gazebo feedback
HOLD의 원인 확인도 운영 연결의 검증 선행 조건으로 남는다.
