# OMX 실제 torque/error 피드백과 불확실한 토크 명령 정리

2026-10-16, D-770 후속. 토크 명령 ACK 유실 시 cleanup 누락과 native 상태의
기본값 출력을 실제 고정 vendor 메서드로 재현하고 수정했다. 실제 자동 시연은 0회다.

## 원인과 변경

SDK wrapper는 enable 성공 ACK 뒤에만 torque cache를 켰다. 모터에 ON이 전달됐지만
ACK가 유실되면 cache는 OFF에 남고 Disable은 OFF cache를 보고 송신을 생략했다.
`hardware-torque-uncertainty.patch`는 ON/OFF 시도 전에 별도 불확실성 집합에 넣고,
ACK 성공 뒤에만 제거한다. 불확실한 ON의 OFF cleanup과 불확실한 OFF 뒤의 ON 재시도를
실제로 송신한다. 이 bookkeeping은 물리 torque readback이 아니다. 해당 객체가 토크
쓰기를 한 적이 없는 passive 초기화 실패에서는 외부 소유 장치를 임의로 끄지 않는다.

기존 DHI `dxl_torque_state_`는 생산자가 없었고 publication에서 false 기본값을 만들었다.
SDK의 별도 torque cache도 물리 readback이 아니다. Hardware Error Status 역시 GPIO
state interface에 없으면 실제로 갱신되지 않고 publication이 zero를 만들었다. 기존
preserved candidate의 여섯 GPIO에는 Position/Velocity만 있었다. 따라서 이전 passive
probe의 native torque/error 검사는 실제 register 검증이 아니었다. 당시 별도 raw 전후
snapshot의 torque/error0 증거는 유효하지만 cyclic 상태 검증으로 확대하지 않는다.

`hardware-status-readback.patch`는 각 모터에 Torque Enable/Hardware Error Status를
정확히 하나씩 요구하며, on_init에서 base 초기화·bus open보다 먼저 검사한다.
read 성공 뒤 실제 cyclic 값의 존재·포인터·길이·중복·유한값·허용 정수 범위를 검사한다.
실제 CheckError로 오류를 해석하고 측정값만 게시한다. read 실패·누락·잘못된 값은 즉시
ERROR이며 fresh 정상 상태를 게시하지 않는다. 실제 nonzero hardware error는 게시하고
ERROR를 반환한다. 기존 fault callback의 stop 시도로 이어지며 자동 재개하지 않는다.

candidate 생성기는 여섯 GPIO에 필요한 read interface 12개를 추가하고 중복/무명 상태를
거절한다. 기존 candidate와 운영 prefix/service를 덮어쓰지 않는다. 기존 read interface가
없는 description은 새 드라이버에서 통신 전 거절되므로 새 candidate로의 migration이 필요하다.

## 확인한 실행

| 증거 | 결과 | 범위 |
|---|---|---|
| 실제 SDK Enable/Disable 본문 | 원본 6실패/5통과 → 수정 11통과 | 전달 여부/ACK 경계 double, 재시도·부분 실패·passive 거절 |
| 실제 read/CheckError 본문 | 원본 14실패 → 수정 14통과 | transport/publication 경계 double, 실제 수치 오류 해석 |
| description RED | 5실패 → GREEN 포함 | 필수 상태 추가와 중복/무명 거절 |
| 명시적 vendor source 원격 pytest | 39 passed, NEW 0, `1608b715d` | lifecycle/init/write/torque/read/description/image wiring |
| 전체 native 8-patch driver | configure/build/install/ldd/CDLL load 성공 | Fleet Lyrical, 실제 장치 없이 compile/link |
| 실제 on_init + Linux PTY | 이전 2open/10PING → 수정 0open/0write | 누락 상태 거절이 실제 bus open보다 앞섬 |
| 실제 torque-off native read | process exit0, fresh 상태 3회 | 여섯 모터 실제 cyclic torque0/error0; 전체 전후 보존 검사는 실패 |

원격 pytest는 `ROSY_OMX_VENDOR_ROOT=rosy-test/vendor/dynamixel-hardware-3375b3d`를
명시했다. read fixture는 ROS publisher/time·kinematics·수송을 double로 두며 실제
CheckError 본문을 컴파일한다. 오류 설명 문자열 lookup은 null이며 실제 오류 비트의
수치 판정은 원본 코드다. SDK fixture의 전달/ACK는 독립 모델이며 물리 ACK 시험이 아니다.

PTY probe는 프로그램 입구에서 `/dev/pts/` character device만 허용한다. 동일한 기존
description으로 이전 6-patch와 새 8-patch 설치 target을 각각 link하고 실제 loader 경로와
library hash를 확인했다. 두 native 객체 모두 init ERROR(설치 enum99)를 반환하고 정상
소멸했다. 이전은 응답 없는 첫 모터 ping을 시도했고 새 버전은 serial open 전에 거절했다.
실제 port·configure·activate·read·write는 실행하지 않았다.

## 실제 passive 실행과 보존 검사 실패

별도 신규 candidate는 GPIO read interface 12개를 추가했다. 실제 port의 독점 소유·device
identity·loader hash를 확인하고 on_init/read3/정상 소멸을 실행했다. configure/activate와
write callback은 호출하지 않았다. native 상태 message의 source stamp가 매 read 이후
진행하고 250ms 이내이며 모터 6개의 torque0/error0임을 실제 cyclic read로 확인했다.
encoder nominal 변환은 최대 1틱 오차다. 이 결과로 torque ON 검증을 주장하지 않는다.

전후 raw snapshot 보존 검사에서 ID14의 Goal Position이 3196→3195로 달라졌다.
Present Position도 같은 1틱 변화이고 velocity1→0이었다. 나머지 설정과 목표는 같고
여섯 모터의 전후 torque/error는 0이다. 따라서 원본 `passive-receipt.json`은
`checks_passed=false`이며 전체 passive 실행을 통과로 기록하지 않는다.

저장된 strace만 별도 분석한 송신105개는 PING6·READ12·indirect SRAM mapping84·
FastBulkRead3이다. goal/torque/reboot 명령은 관측되지 않았다. 값 변화의 원인은 아직
확정하지 않았다. firmware 동작 또는 안전한 변동이라고 추정해 검사를 완화하지 않는다.
장치를 재실행하거나 목표를 복원하는 쓰기를 하지 않고 원본과 별도 offline 분석을 보존했다.

## 원본 위치와 남은 일

Fleet private artifacts:

- `~/rosy-test/omx-driver-status-1608b715d/`: source/patch/library/build logs와 hash receipt.
- `~/rosy-test/omx-status-admission-1608b715d/`: old/new native consumer, loader/strace/output receipt.
- `~/rosy-test/omx-status-description-1608b715d/candidate/`: 신규 description과 원본/출력 hash.
- `~/rosy-test/omx-native-status-read-1608b715d/`: 실제 read·전후 snapshot·송신 trace·실패 receipt와 저장 자료만 사용한 `offline-analysis.json`.

호스트 외부 로그는 `rosy-il-python312` 임시 디렉터리의 `torque-uncertainty-red3`,
`torque-uncertainty-green`, `status-readback-red`, `status-description-red`,
`status-readback-green` 아래에 보존했다. full hash는 private receipt가 소유한다.

현재 자세 주변의 한 관절씩 작은 단계 측정이라는 D-770 결정을 유지한다. 첫 움직임 전에
초기 목표 보존·실제 유한 제한·owner/HOLD·정지 경로를 연결하고 두 카메라와 encoder로
도달·정지·지연을 매 단계 확인한다. hard stop을 향한 범위 탐색이나 현재 측정의 전체
workspace/부하 수용으로의 확대는 하지 않는다. 실제 IL eligible 데이터와 모델 학습은 남아 있다.
