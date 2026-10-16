# OMX 실제 native controller와 owner 피드백 연결

2026-10-16, D-770 후속. 실제 Fleet의 native driver·controller manager·상태 발행기·
trajectory controller를 토크 OFF로 연결했다. 기존 명령 소유자가 실제 상태를 받고,
발행 중단 뒤 stale 명령을 전송 전에 거절해 HOLD에 들어가는 것을 확인했다.
실제 자동 시연과 IL eligible 데이터는 0회다.

## 실제 실행한 경로

고정 8-patch driver와 기존 private controller overlay를 사용했다. 공개 지원 target은
계속 Jazzy이며 이번 실제 설치는 Lyrical/Python3.14다. controller manager/hardware
interface6.10.1, controller6.9.0 조합의 실제 load·configure·activate·종료를 확인했다.
시스템 패키지·운영 prefix/service·disabled profile은 바꾸지 않았다.

현재 `3b95fcab7`의 adapter와 core_common source124개 파일/아티팩트를 hash로 묶어
별도 private 경로에서 import했다. 이전 설치 adapter의 core_common 누락은 현재
source를 함께 제공해 해소했다. 모듈을 stub으로 대체하지 않았다.

| 단계 | 실제 결과 |
|---|---|
| 진입 전 | 알려진 by-id follower, 여섯 torque0/error0·기존 mode·유한 cap 확인 |
| 기동 환경 | 별도 ROS domain·고유 namespace, 다른 ROS node가 없는 baseline 확인 |
| hardware 초기 상태 | 명시적 UNCONFIGURED, 실제 `/proc` maps의 patched driver 경로 확인 |
| hardware ACTIVE | 모든 Torque Enable/Reboot 선택0, enable list 없음; 현재 위치 목표만 동기화 |
| controller | 실제 joint_state_broadcaster와 6관절 JointTrajectoryController ACTIVE |
| source binding | 실제 maps의 두 controller plugin 경로, JSB 단일 publisher 이름/namespace/GID 확인 |
| owner | 현재 RosArmCommandRuntime이 실제 관절 상태10개와 준비된 Action server 확인 |
| 상태 중단 | JSB만 deactivate 후 `joint_state_stale` 거절, owner HOLD, dispatch 시도0 |
| 종료 | 실제 controller manager의 `exit_group(0)`, 강제 종료 없음, 전후 cap·mode·offset 등 동일 |

실물 시작용 [유한 cap](../omx-bounded-commissioning-2026-10-16/result.md)을 매 실행 전후
읽었다. hardware의 `is_async`는 이 bounded probe에서 false로 두고20Hz의 순차
read/update/write를 사용했다. 이 값이 실물 운용 주기의 최종 수용값이라는 뜻은 아니다.

## 명령과 정지의 판정 경계

probe에는 ActionPort의 최종 send_goal을 거절하는 차단 장치를 두었다. 실제 소유자의
stale 검사에서 이미 거절되어 이 차단 장치까지의 dispatch 시도는0이었다. 실제 ROS
Action client/server가 준비됐음은 확인했지만 accepted goal·취소 종단을 실행하지 않았다.
이 차단 장치는 피드백을 생성하거나 소유자 판정을 대신하지 않는다.

실제 native torque/error 상태46개는 모두 여섯 모터 OFF/error0이고 advancing/fresh
source stamp를 가졌다. 관절 상태10개의 nominal vendor 좌표는 raw encoder와 일치했다.
이를 물리 calibration·작업 범위·하중 유지 검증으로 부르지 않는다.

송신196개는 PING6·READ12·indirect mapping84·FastBulkRead47·SyncWrite47이다.
cyclic SyncWrite는 주소224/폭4, IDs11..16의 현재 위치 유지 목표다. 최초 raw 위치와의
최대 차이는1틱이었다. torque/reboot/mode/offset 쓰기는 관측되지 않았다.
목표 차이는 **송신 후** 기록 검사이며 사전 transport guard가 아니다. Action goal0과
native cyclic 목표 쓰기47회를 구분한다. 정지 관측만으로 IL 데이터를 만들지 않는다.

독립 GNU timeout40초/kill-after3초를 두었고 fault/deadline latch를 service 전송 전·
대기 중에 검사했다. controller load/활성화 전에는 최신 실제 OFF/error0 상태를 요구했다.
정상 종료는 실제 CM PID에 SIGINT를 먼저 보내 추적을 유지하고, 종료 뒤에도 소유한
process group의 생존 여부를 검사했다. cleanup 단계 오류가 post snapshot과 receipt를
건너뛰지 않도록 했다. 이번 성공은 **토크 OFF인 경우의 정상 종료**다. 독립 물리 stop,
토크 ON의 해제·처짐·전원/통신 장애를 검증한 결과는 아니다.

## 실패와 수정

1. 첫 실행은 PyYAML이 공유 관절 목록에 만든 alias를 ROS parameter parser가 거절해
   abort했다. serial 송신0, 전후 실제 torque/error0·기존 설정 유지. 각 controller 목록을
   별도로 직렬화해 해결했다.
2. 두 번째 실행은 실제 driver까지 성공했지만 controller의 joints가 비어 초기화가
   실패했다. CM의 전역 params file이 controller에 암묵적으로 전달된다고 가정한 것이
   원인이었다. 각 controller의 `params_file`을 명시했다. 이 실행에서는 group signal이
   tracer를 먼저 종료시켜 cleanup exit 증거를 잃었고 process137이므로 통과로 남기지 않았다.
   실제 post snapshot은 cap·mode·torque/error0을 유지했다.
3. 세 번째 실행이 위 성공 결과다. 저장 packet 분석 첫 버전은 strace의 중첩 `<char ...>`
   FD 표기를 파싱하지 못해 실패했다. 분석기v2는 중첩 표기와 unfinished/resumed syscall을
   재구성하고 완전 송신 길이를 검사했다. **저장 자료만** 분석했으며 장치를 재실행하지 않았다.

controller별 설정 파일 전달은 설치 버전의
[실제 load 경로](https://github.com/ros-controls/ros2_control/blob/6.10.1/controller_manager/src/controller_manager.cpp),
UNCONFIGURED 시작과 controller params_file 의미는
[공식 설명](https://control.ros.org/rolling/doc/ros2_control/controller_manager/doc/userdoc.html)을
대조했다. 문서만으로 실행 성공을 판정하지 않고 위 실제 결과를 별도로 보존했다.

## 원본 위치와 남은 일

Fleet private `~/rosy-test/omx-native-controller-3b95fcab7/`, `-b/`, `-c/`에 각 실행을
보존했다. `-c/`의 source/expected hash·description/controller config·실제 maps·
stdout/stderr·전후 snapshot·trace·`controller-receipt.json`과 저장 자료 전용
`wire-analysis-v2.json`/`analyze-wire-v2.sh`가 판정 근거다. 원래 receipt는 분석 전
`checks_passed=false`를 유지하고 별도 분석이 좁은 검증 범위를 기록한다.
full hash·실제 장치 식별자·호스트 정보는 private 원본에 둔다.

독립 source 검토의 process lifetime/cleanup과 fault 후 activation 지적을 수정했다.
검토자는 장치 시험을 실행하지 않았다. 실제 실행·packet 분석은 별도의 증거다.

이 경로는 첫 미세 이동을 위한 실제 controller/피드백 결선을 확인한다. 아직 영속적인
운영 owner의 admission/restart·실제 accepted goal/취소·토크 ON 상태의 독립 정지·
실제 카메라 동기 시연 수집·사람 검토·실데이터 학습과 재적재는 미완료다.
