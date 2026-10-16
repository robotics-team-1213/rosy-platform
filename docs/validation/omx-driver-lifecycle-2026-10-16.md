# OMX 드라이버 시작·쓰기·정지 오류 처리

2026-10-16 · [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)

## 원인과 수정

source lock의 `dynamixel_hardware_interface` revision(`3375b3d0`)을
직접 읽고 다음 경로를 확인했다. 전체 revision은 기존 `stack.lock.yaml`이 정본이다.

| 경로 | 원본 동작 | 수정 |
|---|---|---|
| 최초 command buffer 쓰기 실패 | 반환값을 무시하고 torque 활성화로 진행 | ERROR 반환, torque 활성화로 진행하지 않음 |
| torque 활성화 10회 실패 | 루프 뒤 SUCCESS 반환 | 전체 disable 시도 후 ERROR 반환 |
| 일부 motor만 활성화된 뒤 실패 | 앞선 motor가 활성화된 채 남을 수 있음 | physical/virtual 그룹 모두 disable 시도, cleanup 실패여도 ERROR 유지 |
| stop의 disable 실패 | 두 결과를 무시하고 SUCCESS 반환 | 두 그룹 모두 시도한 후 어느 하나 실패하면 ERROR |
| direct write/reboot/torque ROS service | owner를 거치지 않는 조작 경로 제공 | 세 command service 등록 제거, read service 유지 |

패치는 원본 source lock을 바꾸지 않고 `Dockerfile`에서 vendor compile 전에 적용한다.
ROSY에서 직접 서비스 세 개를 사용하는 caller는 현재 source 검색에서 발견되지 않았다.
서비스 제거는 기존 단일 command owner 경계를 유지하기 위한 vendor 내부 변경이며,
Fleet/Pilot 공유 API나 SIM API를 실물용으로 바꾸지 않는다.

## 실제 코드 실행 검증

`test/test_omx_driver_lifecycle.py`는 시험 호스트의 고정 Git object에서 원본을 읽고
실제 `start()`·`stop()` 본문을 추출한다. 동일 메서드를 통신 경계 대역과 C++14로
compile해 실행한다. ROS node·SDK·직렬장치·모터는 사용하지 않는다.

원본은 최초 쓰기·enable 소진·두 stop 그룹 실패를 성공으로 보고하는 것을 재현했다.
추가 부분 활성화/cleanup 회귀에서도 수정 전 실패를 확인했다. 수정 후 다음 10개를
모두 통과했다.

- 최초 쓰기 실패와 torque 활성화 방지
- enable retry 소진과 부분 활성화 정리 시도
- 정리 실패에도 activation ERROR 유지
- 정상 시작
- 첫 stop 그룹 실패 후에도 두 번째 그룹 시도
- 두 번째 stop 그룹 실패
- 정상 stop
- 없는 communication 객체의 stop 거절
- 자동 torque 대상이 없을 때 활성화하지 않음
- 초기 read timeout

별도 고정 source 검사에서 세 command callback 등록이 사라지고 read callback은
남는 것을 확인했다. 두 patch의 실제 build 연결도 RED→GREEN으로 확인했다.
`ce08732ce` 원격 관련 pytest **22개 통과**이며, 그중 compiled-method 검사가
위 10개 시나리오를 실행한다. 모델 PC와 Fleet PC에서 해당 고정 source를 사용했다.
독립 검토에서 부분 활성화 정리 누락을 지적받아 회귀 RED 후 수정했고 재검토를 마쳤다.

## 전체 native plugin 확인

운영 install/service와 분리된 새 private source/build/install prefix에 고정 vendor를
추출하고 두 patch를 함께 적용했다. Fleet PC의 기존 Lyrical 환경에서 전체 plugin
build·install, `ldd` 누락 없음, `ctypes.CDLL` library load를 확인했다.
메모리 1536MB·CPU 한 core·단일 build job으로 제한했다.

원문 configure/build/install/ldd log와 patch/library hash receipt는 해당 호스트
`~/rosy-test/omx-driver-lifecycle-ce08732ce/`에 보존했다. 기존 private 원본 build와
운영 prefix는 변경하지 않았다. controller나 ROS node를 시작하지 않았다.

이는 native compile/link/load 확인이며 지원 distro 승인이나 실물 driver 실행 수용은
아니다. `physical_stop_verified=false`, `motion_admitted=false`를 유지한다.
SDK의 성공 반환과 실제 관절 정지·하중 유지·독립 전원 차단은 서로 다른 증거다.
부분 활성화 cleanup도 실패할 수 있으므로 실패를 숨기지 않고 owner가 ERROR를
받아 정지/복구 상태를 판정할 수 있게 한 수정이다.

## 아직 남은 사항

실제 owner와 lifecycle ERROR/terminal/HOLD 연결, 허용 실측 범위·그리퍼 부하,
독립 정지 수용, 실제 feedback과 결과 판정이 남는다. 실제 자동 시연은 0회이며,
이 검증을 모방학습 demonstration이나 실물 stop 성공으로 집계하지 않는다.
