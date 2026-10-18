# OMX 독립 watchdog 시한과 현재 자세 대조 — 2026-10-16

[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 첫 구동을 준비하며
시간 제한을 보강했다. 모든 모터 토크를 OFF로 유지하고 실제 manager watchdog에 의한
native 종료와 별도 OFF 후처리를 검증했다. 실제 ON·의도한 이동·시연은 계속0회다.

## 발견과 수정 범위

private 그리퍼 ON prototype의 `now-first_on<0.4` 검사는 수용 시각의 신선도만 검사했다.
이후 systemctl 호출이 지연되면 ON 상태가 unit의6초 fallback까지 이어질 수 있었다.
검토에서 이를 발견했으며 해당 powered prototype은 실행하지 않았다.

별도의 all-OFF native fixture로 systemd manager에 300ms deadline을 맡겼다. 외부
supervisor의 추가 kill 명령이나 Python watchdog loop가 종료를 수행하는 구조가 아니다.
NotifyAccess=main이므로 child controller가 manager deadline을 연장할 수 없다.

1. 실제 native driver를 UNCONFIGURED로 시작하고 확인된 by-id 독점 소유·driver hash/
   maps·여섯 Torque Enable/Reboot 선택0·기존 cap·mode·실제 OFF/error0을 확인했다.
2. native main이 main/CM PID를 pre-ready로 기록했다. 외부 supervisor가 해당 unit의
   InvocationID·임의 description token·main PID·cgroup을 대조했다.
3. 실제 unit의 Type=notify, NotifyAccess=main, WatchdogUSec=300ms, WatchdogSignal=9,
   KillMode=control-group, KillSignal=9, Restart=no를 읽은 뒤 atomic admission을 남겼다.
4. native main은 실제 libsystemd의 READY/WATCHDOG 알림과 100ms 제한 barrier를 호출했다.
   성공한 뒤에만 hardware ACTIVE를 요청했다. watchdog은 이후 refresh하지 않았다.
5. 실제 OFF/error0 상태3개를 기록하고 대기했다. manager가 watchdog으로 종료했고,
   별도 ExecStopPost가 기존 stop helper로 ID16 OFF 한 번과 여섯 상태 readback을 수행했다.

TimeoutStartSec=6·RuntimeMaxSec=6·TimeoutStopSec=8은 별도 fallback이다. unit 시작
대기와 deadline admission을 분리하기 위해 systemd-run은 no-block으로 호출했다.
기존 unit 거절과 token/InvocationID를 확인하는 cleanup은 유지했다.

## 실제 결과와 지연의 구분

실제 unit Result=watchdog, ExecMainCode=2·ExecMainStatus=9였다. 외부 supervisor는
kill 명령을 보내지 않았다. 기존 main/CM PID는 사라졌고 ExecStopPost는 exit0이었다.
여섯 모터는 실제 OFF/error0, 기존 cap/mode/offset 등 고정 설정은 같았다.

| 시각 범위 | 이번 실행의 관측값 |
|---|---:|
| native notify 발신 → main exit | 약312.4ms |
| main exit → stop 후처리 process exit | 약656.6ms |
| native notify 발신 → stop 후처리 process exit | 약969.0ms |
| 후처리 process 자체 실행 | 약656.3ms |
| stop 함수의 OFF 시도 시작 → readback 완료 | 약17.35ms |

native monotonic timestamp와 실제 systemd D-Bus의 process timestamp를 사용했다.
terminal 조회의 WatchdogTimestampMonotonic은0이어서 그 필드로 시간을 계산하지 않았다.
stop 후처리의 시작/종료는 실제 ExecStopPost struct의 monotonic field를 별도로 보존했다.
함수17.35ms는 Python/SDK import·독점 open·전체 인계를 포함하지 않는다. 설정300ms는
전기적 OFF 완료 시간이나 물리 정지 시간의 보장이 아니다. 이 한 번의 all-OFF 실행
지연을 powered 정지 시간·최악 지연 수용값으로 바꾸지 않는다.

stop helper 저장 trace는 OFF1·PING6·READ6, 총13packet이다. 전송 byte count와 CRC를
전부 검증했고 OFF는 ID16/주소64/값0 한 건이다. helper에 ON·goal·mode·offset·reboot·
EEPROM 쓰기는 없다. 강제 종료된 native trace는 별도 자료로 보존했다.

## 영상과 기구 대조

기존 두 camera producer를 유지하고 최신 frame·진행하는 timestamp를 확인했다.
집게 양쪽 끝과 주변 간격은 명확히 식별하지 못했다. source camera preview에는
원격 PTZ 제어가 없으며 640×480 MJPEG로 고정돼 있다. 영상이 fresh인 사실만으로
집게 주변이 비어 있다고 판정하지 않았다.

별도 독점 read-only snapshot에서 여섯 OFF/error0을 다시 확인했다. 실제 raw 위치를
기존 nominal vendor 좌표로 변환하고 private vendor URDF·8개 mesh의 forward kinematics를
그렸다. 각 source·snapshot·frame transform·그림 hash를 보존했다. 이는 구조 대조용이며
실측한 기계 보정·camera registration·바닥 높이·jaw clearance 수용이 아니다.
손끝 위치 설명 또는 손끝과 바닥이 함께 보이는 시야를 사용자에게 요청했다.

## 소스·보존·남은 범위

기존 committed `9e92cf707`의 stop helper/reader를 그대로 사용했다. controller/adapter
source는 앞선 committed `3b95fcab7`과 동일하며 운영 profile은 비활성이다. 현장 실제
runtime은 systemd259·Lyrical/Python3.14, stop SDK는 별도 기존 Python3.12다.

Fleet private `~/rosy-test/omx-native-watchdog-9e92cf707/`에 native/supervisor/deadline
source·expected hash·guard/parent receipt·원본 설정/상태·unit 전후 속성·admission·
ready·trace·stdout/stderr·stop receipt·D-Bus struct·saved-only 분석을 보존했다.
`~/rosy-test/omx-geometry-readonly-9e92cf707/`에는 read-only snapshot·nominal frame/
mesh source hash·그림을, `~/rosy-test/omx-pulse-camera-20261016/`에는 두 영상을 보존했다.
원본 분석 대기 receipt를 다시 쓰지 않고 별도 all_checks_passed=true 판정을 남겼다.

이 기록은 추가 코드 변경이나 운영 service 설치의 수용이 아니다. private all-OFF
fixture를 한 번 실행했고 분석을 위해 장치를 다시 실행하지 않았다. 실제 ON→OFF와
물리 정지·국소 범위·운영 owner 재시작·실제 IL 데이터 수집/학습은 미완료다.

알림/barrier의 의미는 실제 설치와 같은 major의
[systemd259 문서](https://raw.githubusercontent.com/systemd/systemd/v259/man/sd_notify.xml)를
확인했다. barrier는 앞선 알림 수신을 동기화하며, 종료 수용은 실제 watchdog 결과와
후처리 readback으로 별도 판단했다.
