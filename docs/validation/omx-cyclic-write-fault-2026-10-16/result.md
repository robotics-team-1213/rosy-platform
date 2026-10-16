# OMX 정상 write 오류와 fault 정지 경로

2026-10-16, D-770 후속. 정상 write의 송신 실패를 ERROR로 전파하고 실제 ROS
framework 오류 경로를 stop에 연결했다. 이 단계의 모든 실행은 실제 serial port를
열지 않았다. 실제 정지·부하 유지·시연 수집 수용은 미완료이며 실제 시연은 0회다.

## 발견과 수정

고정 vendor의 write는 WriteItemBuf/WriteMultiDxlData 반환을 무시하고 OK를 반환했다.
HW_ERROR에서도 목표를 송신했으며 COMM_ERROR/REBOOTING에서는 timeout 전까지 OK였다.
실제 메서드를 컴파일한 RED `f0a33e17f`에서 정상 1경우만 통과하고 오류 5경우가 실패했다.

`hardware-write-errors.patch`(`af1a972f2`)는 다음을 수행한다.

- 읽기 상태가 DXL_OK가 아니면 버퍼/torque 변경/목표 송신 전에 ERROR를 반환한다.
- 실제 buffered write와 multiwrite 결과를 CheckError에 전달한다.
- buffered write 실패 후 목표를 송신하지 않는다. multiwrite 실패도 즉시 ERROR다.
- 정상 경로의 기존 순서를 유지하고 오류 누적 상태는 성공한 경우에만 초기화한다.

하위 SDK 경계의 sync/bulk write는 addParam/txPacket 실패를 이미 반환하고 있었다.
상위 write가 그 결과를 버리는 것이 이번 결함이다. txPacket 성공은 모터의 물리 도달
또는 목표 수신 ACK를 뜻하지 않으므로 실제 피드백·종단·정지 관측은 계속 필요하다.

## ERROR를 소비하는 실제 경로

Fleet 설치는 hardware_interface 6.10.1 / rclcpp_lifecycle 32.0.3이다.
`/opt/ros/jazzy`는 실제 Lyrical 설치를 가리킨다. 이번 결과를 Jazzy 검증으로 부르지 않는다.

ResourceManager::write → HardwareComponent::write → trigger_write의 ERROR →
HardwareComponent::error → plugin on_error이며 on_deactivate를 거치지 않는다.
ResourceManager의 추가 error 처리·interface 제거도 그 자체로 torque disable이 아니다.
고정 vendor는 on_error/on_shutdown을 override하지 않았고 상속된 기본 구현은
아무 작업 없이 SUCCESS였다. 따라서 ERROR 반환만 추가하면 stop 시도 없이
UNCONFIGURED로 갈 수 있었다.
[HardwareComponent](https://github.com/ros-controls/ros2_control/blob/6.10.1/hardware_interface/src/hardware_component.cpp),
[ResourceManager](https://github.com/ros-controls/ros2_control/blob/6.10.1/hardware_interface/src/resource_manager.cpp),
[기본 callbacks](https://github.com/ros2/rclcpp/blob/32.0.3/rclcpp_lifecycle/src/node_interfaces/lifecycle_node_interface.cpp).

`hardware-fault-stop.patch`(`7d176b03c`)는 다음을 연결한다.

- on_error는 기존 stop으로 두 disable 그룹을 시도하고 cleanup 실패를 기록한다.
  cleanup 성공 후에도 ERROR를 반환해 fault를 FINALIZED로 유지한다.
- on_shutdown은 stop의 결과를 반환하며 cleanup 실패를 숨기지 않는다.
- 재진입에서도 enable/start/goal을 호출하지 않는다. 자동 복구나 명령 재개를 추가하지 않는다.

## 실행 증거

| 증거 | 실제 결과 | 확인 범위 |
|---|---|---|
| 고정 메서드 compiled write | 원본 5실패 → 수정 6경우 통과 | 송신 결과 전파·추가 목표 차단 |
| compiled stop/error/shutdown | 8경우 통과 | 두 그룹·각 disable 실패·통신 객체 부재 |
| 원격 관련 pytest | 24 passed, NEW 0 | 기존 lifecycle/init/owner 서비스 경계와 image wiring 포함 |
| 전체 native plugin | 별도 prefix configure/build/install/ldd/CDLL load 성공 | 6개 driver patch의 compile/link |
| 실제 ROS 객체, 통신 객체 부재 | 기존 callbacks 97/97 → 수정 99/99 | 기본 SUCCESS 제거·정지 실패 전파 |
| 실제 HardwareComponent consumer | 12경우 통과, exit 0 | framework→오류 callback→stop 경로 |

원격 pytest는 `ROSY_OMX_VENDOR_ROOT=rosy-test/vendor/dynamixel-hardware-3375b3d`를
명시해 source 의존 시험을 실제 실행했다. 미지정으로 skip된 결과를 이 숫자에 넣지 않았다.
원래 메서드의 RED 로그와 수정 후 GREEN 로그는 별도로 보존했다.

native consumer는 [committed fixture](../../../test/fixtures/omx_driver_fault_routing.cpp)의
5914e45b0 source와 실제 patched write/stop/on_error/on_shutdown 본문을 사용했다.
bus·기구 계산과 CheckError의 상태 해석·ChangeDxlTorqueState의 torque 요청 처리는
double이고 HardwareComponent lifecycle consumer는 실제 설치본이다. 이 probe는 실제
hardware-error register 해석이나 torque 요청의 성공/실패 처리를 검증하지 않는다.
buffer/multiwrite/HW fault, 두 disable 그룹의 성공·각 실패, 정상 shutdown,
반복 cleanup과 fault 후 configure/activate/write가 명령을 다시 열지 않는 경우를 확인했다.
on_error를 실제 상속 기본 구현으로 돌린 negative control은
`FAIL write error did not route to stop`, exit 2로 실패했다.

native fixture의 첫 빌드에서는 필수 read override 누락으로 abstract-class compile 오류가
났다. 실제 장치 실행 없이 fixture를 보완했고 그 실패 디렉터리는 유지했다. read double은
ERROR를 반환하며 이 probe에서 센서 데이터나 실제 read 성공을 만들지 않는다.

Fleet private evidence:

- `~/rosy-test/omx-driver-write-fault-7d176b03c`: 원본 build receipt 연결, 두 patch·source/header·library·로그 hash.
- `~/rosy-test/omx-native-fault-callbacks-before`, `-after`: 실제 객체 source/binary·loader·출력·exit·receipt.
- `~/rosy-test/omx-native-fault-routing-7d176b03c-c`: 최종 consumer/negative control source·binary·로그·receipt·binding.

운영 prefix나 service는 교체하지 않았다. 실제 driver 객체 검사는 on_init/activate를
호출하지 않았다. native routing fixture의 activate는 통신 double의 framework lifecycle이다.
이 값을 실물 activation·torque off 성공·독립 stop 수용으로 집계하지 않는다.

## 다음 실물 단계의 조건

첫 미세 이동 전 유한한 profile/PWM/current 제한의 실제 적용, 초기 목표 보존,
실물 owner의 feedback·terminal·HOLD와 정지 관측을 연결한다. 기본 enum/cache나
송신 성공을 실제 torque/오류/정지 피드백으로 확대하지 않는다.
이 결과는 [앞선 실제 passive read](../omx-native-passive-read-2026-10-16/result.md)에
이어지는 software 오류 처리 증거이며, 새 실물 시연 데이터가 생긴 것은 아니다.
