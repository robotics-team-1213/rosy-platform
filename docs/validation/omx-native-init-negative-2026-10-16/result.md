# OMX native ROS 초기화 실패 경로 — 2026-10-16

D-770 후속. [이전 compile/link/load 확인](../omx-driver-lifecycle-2026-10-16.md)에서
실제 ROS 객체 생성·초기화·소멸까지 진행한 비구동 시험이다.

## 대상과 실패 재현

`d8a24d778`의 source lock과 두 driver patch를 적용한 private Fleet build를 사용했다.
지원 목표 Jazzy와 달리 실제 호스트는 Lyrical이며 이 시험으로 지원 distro를 승인하지 않는다.

외부 CMake consumer에서 고정 driver target을 연결하자 configure가 실패했다.
공개 link interface가 사용하는 `std_srvs`와 `realtime_tools`를 vendor의
`ament_export_dependencies`가 내보내지 않았다. consumer에 두 `find_package`를
추가하면 configure/build와 아래 시험이 성공하여 원인을 확인했다.

`hardware-export-dependencies.patch`는 두 dependency만 추가한다. 기존 두 patch와
함께 적용한 별도 prefix에서 전체 plugin build/install 후, consumer의 임시
`find_package` 두 줄을 제거하고 configure/build가 성공했다. `ldd`로 새 prefix의
실제 plugin을 연결했음을 확인했다. 기존 운영 prefix는 변경하지 않았다.

## 실제 ROS 시험

재현 source와 consumer CMake는 [evidence](evidence/probe.cpp)에 있다.
보존된 실제 expanded URDF 후보를 읽되 `port_name`을 코드에서 고정한
`/nonexistent/rosy_omx_negative_probe/serial`로 덮어쓴다. `/nonexistent`가 존재하면
시험을 거절한다. 여섯 GPIO의 torque/reboot 선택이 모두 0인지 검사한다.

ROS domain 113, localhost discovery, FastDDS로 격리했다. 실제 C++ driver 객체를
생성하고 `on_init`만 호출했다. configure/activate/write/goal은 호출하지 않는다.
실제 source의 SetupPort는 전달한 포트만 사용하며 fallback이 없다.

두 번의 실행 모두 다음을 확인했다. 두 번째는 export 수정 후 새 plugin이다.

- `ROS_DRIVER_CONSTRUCTED`
- 고정된 존재하지 않는 포트에서 open 5회 실패
- `ON_INIT_RETURN=99` (`CallbackReturn::ERROR`)
- `DRIVER_DESTRUCTED`, process exit 0

부분 초기화 뒤 destructor의 `stop()` 호출도 crash 없이 끝났다. 이는 잘못된 포트의
실패 경로에 한정된다. 통신 중 실패나 부분 활성화 종료의 실물 검증은 아니다.

원문 로그·source·CMake·library 바인딩은 Fleet private
`~/rosy-test/omx-native-negative-probe-20261016/`와
`~/rosy-test/omx-driver-export-20261016/`에 보존했다.
후자의 `receipt.json`에 source/patch/library/probe/log checksum을 기록했다.

## 실물 owner 경계와 미완료 조건

`omx_cell_owner.py`의 현재 조립은 `simulation=True`, `omx-cell-sim`과
SIM gripper joint-position 관측에 고정돼 있다. 기존 합성 `/joint_states`나 SIM
그리퍼 추정을 실제 feedback으로 간주하여 이 조립을 실물용으로 실행할 수 없다.
실측 profile과 실제 feedback을 사용하는 조립, lifecycle ERROR/terminal/HOLD 연결,
독립 정지·그리퍼 부하·허용 범위 수용이 남아 있다.

실제 시연 **0회**, `motion_admitted=false`, `physical_stop_verified=false` 유지.
이미 수집한 observation-only bag은 command가 없어 IL demonstration에 포함하지 않는다.
실제 demonstration → 사람 검토·독립 분할 → 실제 LeRobot reader → 학습·재적재라는
D-770 완료 조건은 아직 충족하지 않았다.
