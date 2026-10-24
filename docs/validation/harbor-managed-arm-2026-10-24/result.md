# D-856 managed physical owner 검증

소스: `69607b2b0dc3ca62bd1e5f65764b10766f808f16`. 명시적으로 선택한 새 프로파일에만 적용하며 기본 Cell/Pilot 설정은 바꾸지 않는다. journal schema3에 owner/policy/journal identity를 영속 결속하고, 같은 admission·journal·grant·phase·최종 owner에 연결된 synchronous command만 허용한다. TTL/재시작으로 unmanaged로 돌아가지 않는다.

## 고정 SHA 증거

공식 `tools/remote/remote_pytest.py --sha 69607b2b0d --log-dir <external>/rosy-managed-arm-final --`에 다음 여섯 target을 전달했다. `test_managed_transfer_admission.py`, `test_control_seat_admission.py`, `test_omx_action_store.py`, `test_omx_action_api.py`, `test_omx_pick_place_runner.py`는 `middleware/devices/omx/adapter/test/` 아래이며 나머지는 `test/test_platform_arm_transfer_owner.py`다.

- **119 passed, 0 skipped**, runner exit0. `test/known_failures.py`도 **0 NEW**. 재시작 scope/policy 유지·잘못된 identity/저널 손상 거절·동시 초기화·Pilot/raw 차단·정확한 object/thread/context 종료·잘못 연결된 최종 owner·최종 writer에서 만료 거절을 포함한다.
- native `size_range.py ed5eecc216 69607b2b0d`와 `safety_review.py`는 각각 4 commits, exit0. 독립 fixed-SHA 소스 재검토는 material finding 없음이다. [검토 기록](source-review.md)을 따른다.
- e26→696의 공식 affected 선택은 `affected`, 한 invocation이다. `rosy-managed-arm-affected/run-1.txt`는 1729 passed/36 skipped/1 failed, **1 NEW**였다. test helper 두 곳의 `setup` 이름이 저장소의 nose 호환성 guard에 걸렸다. 호출부까지 `_setup`으로 변경했으며 전체 선택 재실행 전이다. 이 집중 결과를 전체 affected 통과로 대체하지 않는다.

## 실패 이력

`ed5eecc216`의 미구현 admission은 공식 RED 4 failed/1 passed였다. 첫 기능 SHA `e4b2c6c3c0`는 117 passed/1 failed/1 skipped였다. 실패는 새 시험의 수기 owner 설정에 rate limit이 없었던 것이며 설치 profile의 `arm_command_config`를 재사용하도록 고쳤다. 같은 실행의 ROS runtime module은 `rclpy` 부재로 skip됐고 실제 native ROS 수용의 증거가 아니다.

만료 RED의 최초 `1f7f71efdb`도 같은 설정 누락으로 다른 경계에서 거절됐으므로 유효한 만료 증거로 쓰지 않는다. 수정된 test-only `69295d4b9e`는 유효 명령 1 passed, 만료 명령이 실제 FakeActionClient까지 `submitted`되는 1 failed였다. 이후 최종 owner의 exact-command 확인에서도 pure clock validator를 호출하도록 수정했고 최종 집중 GREEN에 포함했다. 최종 owner lock 안 DB/network 조회를 추가하지 않았다.

## 한계와 다음 게이트

실제 planner·ActionStore·ControlSeatAdmission·ArmCommandOwner와 FakeActionClient를 사용한 호스트 시험이다. goal/gripper/measured state는 시험 주입이며 실제 ROS, 물체 접촉, 전체 링크의 영역 이탈, 정지 시간이나 실물 안전 수용을 입증하지 않는다. 관리 모드의 필드 활성화·배포·push는 수행하지 않았다.

Fleet physical producer·중립 승인/receipt·claim 해제·Harbor ARM 변환은 아직 연결하지 않았다. shared zone의 모든 참가자가 managed이고 trusted 전체 링크 증거와 현재 owner/journal/fence가 확인돼야 다음 producer를 연다. 이전 e26 affected의 G1 timing 2 NEW는 같은 SHA 별도 재현 4 passed였지만 원인은 미확정이다. 해당 로그와 실패 판정은 보존한다.

CE: 미해결 — G1 timing 실패의 원인은 확정하지 않았다. 이번 managed 권한 보강의 판단은 설계·코드·회귀에 남겼고 별도 해결 교훈을 만들지 않았다.
