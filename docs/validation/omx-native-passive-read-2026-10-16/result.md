# OMX 실물 native 초기화·토크 off 읽기

2026-10-16, D-770 후속. 실제 follower에서 native driver on_init과 read 3회,
정상 소멸을 확인했다. 구동·보정 수용이나 모방학습 시연 수집은 아니다. 실제 시연은 0회다.

## 수정과 재현

고정 vendor InitDxlComm은 ping의 hardware alert/error 분기에서 Reboot를 호출했다.
GPIO Reboot=0만으로 이 경로를 막지 못했다. `hardware-init-no-reboot.patch`는
진단과 DXL_HARDWARE_ERROR 반환을 유지하고 자동 reboot만 제거한다. source lock은 유지한다.
실제 고정 메서드를 컴파일하는 시험에서 원본 2개 오류 분기의 reboot를 재현했고,
수정 후 정상·transport 실패·hardware alert·error code·model lookup 5경우가 통과했다.
driver 수정 커밋은 `a52253eee`이며 별도 prefix에서 전체 build/install/load를 완료했다.

포트 보호 helper는 SDK의 open/open64 직후 st_rdev를 사전 snapshot과 대조하고
TIOCEXCL 및 fuser로 단독 소유를 확인한 뒤 SDK에 descriptor를 돌려준다.
다른 기존 opener가 있으면 거절하며 해당 opener의 handle은 유지한다.
root 실행은 거절한다. 이 임시 helper는 privileged 사용자를 차단하는 운영 경계가 아니다.

첫 실제 실행에서 helper의 dlsym과 ROS tracing library constructor의 worker가
loader lock으로 교착했다. 포트 없이 dlopen→constructor→worker open을 수행하는
회귀(`22e3a59b7`)도 timeout으로 실패했다. Linux SYS_openat 직접 호출로 바꾼
`01a878150`에서 교착 회귀와 PTY 독점/경합/identity/negative control 합계 6시험이
실제 Linux 비특권 계정에서 통과했다. 시험의 기존 실패 비교는 NEW 0이다.

## 실행을 구분한 기록

Fleet private scratch `~/rosy-test/omx-native-passive-read-a52253eee`와
각 `-b`, `-c` 디렉터리에 source/binary binding, 전후 snapshot, stdout/stderr,
strace, receipt와 파일 hash seal을 각각 보존했다. 실패 디렉터리를 덮어쓰지 않았다.

| 실행 | 결과 | native serial 송신 |
|---|---|---|
| 첫 실행 | constructor 교착, bounded timeout exit 137 | 0 packet |
| b | 동적 XML parser dependency 경로 누락, abort -6 | 0 packet |
| c | on_init 성공, read 3회, 정상 소멸, exit 0 | 93 packet |

수정 helper로 존재하지 않는 포트의 선행 검사 exit 4를 확인했다. c에서는 장치 접근 전에
전체 description 파싱과 6 GPIO parameter 검증도 별도 모드로 완료했다.
child의 LD_* 상속을 제거하고 새 driver·기존 SDK/interfaces·ROS dependency 경로를
명시했다. 정확히 같은 loader 환경에서 ldd로 실제 선택된 driver의 canonical path와
build receipt hash를 대조했다. 오래된 driver를 로드하며 새 파일의 hash만 검사하지 않는다.

현재 Fleet은 Ubuntu 26.04/ROS Lyrical이며 `/opt/ros/jazzy`가 해당 설치를 가리킨다.
이 결과를 Jazzy 제품 배포 수용으로 확대하지 않는다. 운영 prefix나 service는 교체하지 않았다.

## c의 실제 관측

[probe.cpp](evidence/probe.cpp)는 실제 driver의 on_init만 호출하고 configure/activate/write는
호출하지 않는다. preserved description의 GPIO는 ID/type/Torque Enable=0/Reboot=0만 허용한다.
각 read가 반환한 뒤 해당 읽기 시작보다 새로운 실제 driver status를 250ms 안에 받아야
sample을 인정한다. 6개 ID·comm/error·torque·원본 시각 진행을 검사한다.
read가 통신 오류 동안 OK와 이전 state를 유지하는 경로는 새 status가 없어 sample로 인정되지 않는다.

- 실제 여섯 관절 위치 3 sample, 원본 시각 간격 103.410164ms / 103.359916ms.
- 사전 원시 위치의 vendor nominal 변환과 최대 차이 0.001533980788rad, 약 encoder 1틱.
- 전후 여섯 모터 torque/error 모두 0. 비교 대상 설정·goal·mode·offset·gain·limit·watchdog 변경 없음.
- serial 송신: ping 6, read 12, indirect-address SRAM write 72, fast bulk read 3.
- 72개 write는 모델별 허용된 indirect mapping 주소의 2바이트 unicast write다.
  위치 goal·torque·reboot packet은 관측되지 않았다. 초기화가 모든 의미에서 읽기 전용인 것은 아니다.

처음 coordinator는 CallbackReturn SUCCESS를 숫자 0으로 잘못 가정해 실행 후 분석에서
중단됐다. 설치 header의 실제 값은 97u이며 C++ probe 자체는 SUCCESS enum과 비교했다.
원래 `passive-receipt.json`의 checks_passed=false는 보존했다. 장치 재실행 없이 원본 로그를
검사한 별도 `offline-analysis.json`은 checks_passed=true이며 원래 receipt, analyzer,
enum header와 결과 파일의 hash를 기록한다. 실제 결과와 분석 수정은 구분한다.
후속 `offline-analysis-v2.json`은 현재 장치 경로 stat도 제거해 보존 파일만 사용한다.
기존 analyzer와 output을 쓰기 전에 검사하며 재호출의 덮어쓰기 거절도 확인했다.
첫 분석 source/receipt는 유지하고 v2는 그 receipt hash도 연결한다.

## 남은 단계

nominal 좌표 일치는 물리 보정이나 전체 관절 한계의 증거가 아니다. torque off인데도
한 관절의 원시 위치가 1틱 바뀌었으므로 명령 없이도 정지 상태가 완전히 불변이라고 가정하지 않는다.
첫 작은 이동 전 유한한 profile/PWM/current 제한 적용·초기 목표 보존·write 오류 전파·
실물 owner/HOLD·정지 경로를 연결한다. 현재 자세 주변만 단계적으로 측정하며 hard stop을
탐색하지 않는다. 이전 observation bag은 계속 commands=0, imitation_eligible=false다.
실제 action/feedback/video 시연과 그 데이터의 LeRobot reader·모델 학습은 아직 미완료다.
