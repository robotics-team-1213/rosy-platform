# OMX 별도 torque-OFF 경로와 process-death 인계 — 2026-10-16

[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 첫 미세 이동에 필요한
정지 경로를 추가했다. `commissioning_stop.py`와 실제 systemd 종료 후처리를 검증했다.
모든 native torque 선택은 계속0이며 실제 ON→OFF 전환·물리 정지는 아직 검증하지 않았다.

## 구현과 시험

stop helper는 기존 register reader의 확인된 by-id·unprivileged 독점 open을 재사용한다.
실제 열린 FD의 st_rdev가 명시한 identity와 같아야 한다. 대상은 명시한 follower IDs
11–16의 유일한 부분 집합이다. 전송 경계는 기존 PING/READ와 해당 ID의 주소64/폭1/
값0을 정확히 한 번만 허용한다. ON·goal·mode·offset·reboot·EEPROM 쓰기는 없다.

한 모터의 SDK 예외·ACK 유실 뒤에도 나머지 지정 모터의 OFF를 각각 한 번 시도한다.
불확실한 쓰기를 재시도하지 않는다. 이후 여섯 모터의 모델/ID와 지정 모터의 실제
Torque Enable=0·Hardware Error Status=0을 읽는다. ACK와 readback을 각각 보존한다.
ACK 유실 뒤 OFF를 읽더라도 clean success로 표시하지 않는다.

기록 디렉터리 생성·hash·fsync는 OFF 시도 뒤에 수행한다. 디스크 오류로 정지 시도를
생략하지 않으며, 기존 기록은 덮어쓰지 않는다. ACK/readback 성공 뒤 포트 정리가
실패한 경우도 CLI는 실패로 종료한다. 전송 기능은 finally에서 read-only로 되돌린다.

| 구분 | committed revision / 결과 |
|---|---|
| 최초 RED | `d27bd4767`: stop transport 부재로 신규26시험 실패 |
| 구현 GREEN | `26cf0d50d`: stop·기존 cap·register 종합91시험 통과 |
| 검토 발견 RED | `8de348088`: serial close 실패에도 exit0 반환을 재현 |
| 수정 GREEN | `d6439490b`: 종합92시험 통과, NEW0 |

시험은 원격 PC에서 committed HEAD로 수행했다. packet whitelist, 잘못된 ID/ON/goal/
mode/reboot/길이, 중복/short/실패 송신, 부분 실패 뒤 후속 OFF, ACK 유실, 여전히 ON,
read 유실, 모델 불일치, 선택하지 않은 모터, 디스크 오류, device mismatch, close 오류를
검증했다. SDK/transport 경계 double을 사용하는 시험이며 실물 OFF의 대체 증거는 아니다.

## 실제 인계 실행

실제 stop helper는 `d6439490b`의 committed source와 register reader를 그대로 사용했다.
native driver/CM은 [앞선 실제 경로](../omx-native-controller-feedback-2026-10-16/result.md)와
동일하다. 실제 현장 systemd는259이고 native ROS는 Lyrical/Python3.14다. stop helper는
별도 기존 SDK Python3.12 환경에서 ROS/LD 환경을 제거해 실행했다.

1. 기존 cap·mode·여섯 OFF/error0을 raw snapshot으로 확인했다. 8-patch driver의
   hash·실제 maps와 여섯 Torque Enable/Reboot 선택0을 확인했다.
2. 별도 domain의 실제 controller manager·JSB·JTC를 시작했다. Action goal은 보내지
   않았다. native 실제 OFF/error0 상태17개와 두 PID의 해당 unit cgroup 소속을 기록했다.
3. transient user unit은 RuntimeMaxSec=12, TimeoutStopSec=8, KillMode=control-group,
   KillSignal=SIGKILL, Restart=no다. unit의 main PID만 SIGKILL로 종료했다.
4. systemd 종료 후처리가 남은 controller process 종료 뒤 독립 stop helper를 실행했다.
   helper는 장치를 독점 확보하고 gripper ID16에 OFF 한 번을 보냈다.
5. 실제 OFF ACK와 여섯 모터 OFF/error0, cap/mode/offset 등 고정 설정 보존을 확인했다.
   unit Result=signal·ExecMainStatus=9는 의도한 강제 종료다. ExecStopPost는 exit0이고
   기존 main/CM PID는 사라졌다. 정상 CM exit 증거로 바꾸지 않는다.

stop helper의 저장 trace는 총13packet: OFF1·PING6·READ6이다. 첫 packet은 ID16의
주소64/값0이며 전송 byte count와 전 packet CRC를 검증했다. 다른 쓰기는 없었다.
native main의 trace는 강제 종료된 별도 자료이며, 이13개 집계에 포함하지 않는다.
helper의 OFF 시도 시작부터 readback 완료까지 약17.1ms였다. import·독점 open·systemd
인계 전체 시간 또는 물리 정지 시간·최악 지연을 측정한 값이 아니다.

## 소유권 검토와 보존

private supervisor 검토에서 unit 생성 실패 뒤 같은 이름의 기존 unit을 중지할 수 있는
문제를 발견했다. 실제 try/finally AST를 fake systemctl로 실행해 foreign unit stop을
재현했다. 기존 unit 거절과 임의 description token·InvocationID 일치 확인을 추가한 뒤
기존 unit/생성 경합 두 경우 모두 타 unit을 중지하지 않음을 확인했다. 이 검사는
standalone probe 검사이며 원격 pytest92개에 합산하지 않는다. 수정 전후 source를
보존했고 실물 실행은 수정한 supervisor로 한 번만 수행했다.

Fleet private `~/rosy-test/omx-stop-handover-d6439490b/`에 committed source·expected
hash·native/stop/supervisor source·기존 guard receipt·description/YAML·maps·전후 상태·
ready·unit 속성·stdout/stderr·native/stop trace·stop-output/receipt.json·supervisor
receipt·stop-wire-analysis.json을 보존했다. source identity와 분석 대상 full hash는
private receipt에 있다. 원본 checks_passed=false는 분석 대기값으로 유지하고 별도
saved-only 분석의 all_checks_passed=true로 좁은 판정을 남겼다.

이 transient unit은 독립 supervisor가 종료 후처리를 실행할 수 있음을 검증하는
commissioning fixture다. 운영 service 설치·자동 재기동·토크 ON 권한을 추가하지 않았다.
전체 host/USB/전원 고장에 대한 물리 E-stop을 대체하지 않는다. 실제 ON→OFF 정지와
국소 이동 측정, 운영 owner 재시작 수용, 실제 시연·IL 데이터·실데이터 학습은 미완료다.
실제 시연은 계속0회다.

설계 의미는 systemd의 [service 정의](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.service.xml)와
[process 종료 정의](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.kill.xml)를
참고했고, 실행 수용은 위 현장의 실제 unit/독점 open/readback 증거로 판단했다.
