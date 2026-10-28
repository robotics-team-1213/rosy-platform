# CORE 경유 OMX–LeRobot 연동 검증

날짜: 2026-10-18. 작업 브랜치 `feat/omx-core-lerobot`, 기준
commit `8be38f1b94c937c9864fb26488cd2b8549fc06b2`.
최종 코드 검증 commit: `5e3af70e6d824d1f6333a46c954393c011c06dfa`.
안전 symbol 등록 보완 commit: `8beeb47ef26b1eb15ed530e589af87861041a40c`(실행 코드 변화 없음).
이 기록을 추가하는 커밋은 문서만 변경한다. main 병합·push·배포는 하지 않았다.

## 구현한 경로

```text
CORE의 관절·RGB 관측 → LeRobot 기록 → 학습·평가·기존 승인 절차
CORE의 관측 → LeRobot ACT 추론 → CORE 후보 검증 → 기존 OMX owner → ROS Action
```

LeRobot은 모터나 ROS에 직접 접근하지 않는다. CORE의 선택적 arm port는
기존 `OwnerPolicySession`과 runtime에 결선하며, 최종 writer는 기존 OMX owner다.
기본 CORE에는 이 port가 결선되지 않는다. HTTP 요청으로 모델 설치·lease 발급·
재무장할 수 없다. API v1.271과 D-800에 계약을 기록했다.

관측은 원본 센서 시각과 단일 사용 ID를 보존한다. 후보 제출 시 원본 입력의
유효시간·권한·정지 fence·관절 범위를 기존 owner가 다시 검사한다. CORE E-stop은
arm fence에도 전달된다. 불확실한 응답은 정지를 요청하며 동작을 재시도하지 않는다.

설치·설정 절차는 [CORE_LEROBOT.md](../../../integrations/robots/omx/docs/CORE_LEROBOT.md)에 있다.
지원 범위는 LeRobot 0.4.4, RGB 한 대, 정확히 일치하는 관절 이름과 rad 단위,
ACT `n_action_steps=1`, temporal ensemble 없음이다.

## 실행한 검증

모든 pytest는 승인된 원격 AI PC에서 커밋을 전달하여 실행했다. 모델 PC가 도달
불가여서 remote runner의 대체 호스트 선택을 사용했다. runner가 자원 하한 미달
경고를 출력했다. 노트북에서는 pytest를 실행하지 않았다.

| 검증 | 커밋 | 관측 결과와 범위 |
|---|---|---|
| CORE·native ROS·실제 LeRobot SDK | `5e3af70e6d` | **22 passed, 0 skipped**. 인증·입력 재사용/만료·권한 철회·정지·실제 ROS Action 수락/완료/취소·SDK 녹화/학습/추론 |
| CORE 브라우저 회귀 | `9bbf3cdc80` | **45 passed, 0 skipped**. 콘솔·지도·캘리브레이션·역할·viewport. 이후 UI 변경 없음 |
| 전체 영향 범위 회귀 | 아래 출처 참조 | 22개 분할, **27,638 passed / 1,916 skipped / 1 failed**(실행 건수, 중복 가능). safety anchor 등록 누락을 발견해 보완 |
| 등록 보완 후 관련 계약 재검증 | `8beeb47ef2` | **170 passed, 0 skipped**, known_failures NEW 0. 안전 경계·manifest·문서 배치·폴더·network·harness |
| 정적 검사 | `8beeb47ef2` | harness lint 0 errors/32 기존 경고, safety-review 17 commits, size-range 17 commits, diff whitespace 통과 |

집중 검증 명령:

```text
python tools/remote/remote_pytest.py --log-dir <external>/source-final -- ROSY_OMX_NATIVE_RUNTIME_TESTS=1 middleware/core/api/test/test_arm_policy_api.py test/test_omx_native_ros_runtime.py test/test_omx_lerobot_integration.py
# The saved browser log has 45 passing cases; its complete original invocation was not retained here.
# See ../core-omx-deployment-2026-10-18/landing.md for the later explicit mapped-browser verification.
python tools/remote/remote_pytest.py --sha 8beeb47ef2 --log-dir <external>/anchor-final -- test/architecture/test_safety_separation.py test/architecture/test_platform_parts.py test/architecture/test_document_placement.py test/architecture/test_folder_layout.py test/test_network_topology_contracts.py test/test_harness_contracts.py
```

SDK 검증은 실제 LeRobot `record_loop`와 dataset writer로 합성 이미지·관절·행동
프레임을 저장·완료했다. 별도 합성 3-episode 데이터는 공식 ACT trainer로 CPU
2 step 학습 후 저장된 모델과 processor를 다시 읽고 추론했다. 녹화 fixture의
클라이언트 경계는 대역이다. 이 두 검증을 실제 CORE 관측으로 학습한 모델의
연속 작업 성공으로 합쳐 해석할 수 없다.

native ROS 검증은 실제 CORE HTTP app → session → `RosArmCommandRuntime` →
격리 `FollowJointTrajectory` 서버의 goal ID·terminal 결과·권한 철회 취소를 확인했다.
센서·정책·권한은 합성이며 Gazebo나 실물 서버가 아니다. 입력 시간 예산은 명시적인
테스트 fixture의 2초다. 제품 시간 예산을 늘리지 않았다.

## 수정 과정에서 확인한 실패

- RGB capture가 멈추면 stop도 같은 lock을 기다리는 결함을 회귀 시험으로 재현했다.
  stop을 capture lock 밖의 기존 persistent fence에 연결했고, 막힌 capture 중에도
  정지가 완료되며 재개된 관측이 거부됨을 확인했다.
- 실제 SDK recorder가 `robot.cameras`를 요구했다. remote stream 표시만 제공했고
  장치 reader를 만들지 않았다. 실제 writer 실행으로 호환성을 확인했다.
- native fixture가 최초 카메라 시각 뒤에 CORE를 cold import하여
  `policy_camera_stale`로 거부되는 실패가 있었다. import를 최초 lease/capture
  앞으로 옮겼다. 이미 사용한 관측 시각을 갱신하거나 admission을 약화하지 않았다.
- 전체 회귀가 API changelog의 v1.271 누락을 잡아 해당 행을 추가했다.
- 전체 회귀가 새 safety module의 필수 symbol anchor 누락을 잡았다. 기존
  safety 태그를 유지하고 `CoreArmPolicyPort` anchor를 등록했다. `public: true`
  예외를 추가하지 않았으며, 독립 리뷰와 위 170개 관련 계약 재검증을 통과했다.

독립 `core_arm_review`는 stop 수정과 최종 `5e3af70e6d`까지의 변경을 읽고
추가 권한·안전 계약 위반을 발견하지 않았다. 초기 리뷰가 놓친 stop lock 문제는
위 회귀로 보완했다. 리뷰는 소스 검토이며 원격 결과 재실행이나 실물 수용이 아니다.

## 증거 출처와 한계

원시 로그는 저장소 밖 `%LOCALAPPDATA%/Temp/rosy-omx-core-lerobot/`에 있다.
해시와 회귀별 결과는 [log-manifest.json](evidence/log-manifest.json)에 기록했다.
집중 검증은 `source-final/run-1.txt`, 브라우저는 `browser/run-1.txt`다.
전체 회귀는 affected selector의 `full_invocations` 22개 분할을 사용했다.
앞 8개는 `9bbf3cdc80`의 `full-partitioned/run-1..8.txt`, 나머지 14개는
`7d8a61e58f`의 `full-final/run-1..14.txt`다. 이후 최종 코드의 변화는 recorder의
remote camera 표시와 테스트 추가·cold import 순서다. 전체 suite를 최종 SHA에서
다시 실행한 것으로 주장하지 않는다. 각 로그를 `test/known_failures.py`와 비교했다.
전체 회귀의 NEW 1건은 위 anchor 누락이다. 수정 후 관련 재검증은 NEW 0이며,
원래 실패 로그를 성공 로그로 대체하지 않았다. 그 외 21개 분할은 NEW 0이다.
1,916 skipped는 실행 증거가 아니며, 별도 opt-in native/SDK/browser 결과와 구분한다.

**현재 SIM 연동 구현과 검증이다.** 기본 실물 profile, Fleet lease의 실제 owner 전달,
D-770 G4, 설치된 정책의 실물 승인·캘리브레이션·작업 성공은 검증하지 않았다.
관측 revision pin은 외부 프로세스가 실제로 어느 모델과 픽셀을 사용했는지 증명하지
않는다. native 정규화 OMX 데이터와 rad 데이터를 자동 변환하지 않는다.
정지 응답은 fence·취소 증거이며 물리적으로 정지했다는 증거가 아니다.
