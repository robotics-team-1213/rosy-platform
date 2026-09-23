# Rosy Raspberry Pi 5 Wi-Fi 배포 가이드

이 가이드는 유선 LAN 없이 Raspberry Pi 5 8GB에 Rosy의 `rosy-core`와
FastAPI 대시보드를 설치하는 절차다. 첫 배포는 비밀정보가 들어간 커스텀
`.img`를 만들지 않는다. 공식 Raspberry Pi OS Lite 64-bit 이미지를 굽고,
Raspberry Pi Imager에서 장비별 Wi-Fi와 SSH 설정을 주입한 다음, 커밋된 Rosy
릴리스를 설치한다.

공식 참고 자료:

- [Raspberry Pi Imager와 OS 커스터마이징](https://www.raspberrypi.com/documentation/installation/installation/services/configuration.html)
- [Raspberry Pi 네트워크와 `nmcli`](https://www.raspberrypi.com/documentation/configuration/computers/raspberry-pi.html)
- [Docker Engine Debian 설치](https://docs.docker.com/engine/install/debian/)

## 1. 네트워크 구조

```text
인터넷
  |
Wi-Fi 공유기 또는 휴대전화 핫스팟
  |-- Raspberry Pi 5: rosy-01.local
  `-- 운영 노트북/태블릿: 브라우저와 SSH
```

Pi 5와 운영 단말을 같은 Wi-Fi에 연결한다. Wi-Fi 연결과 인터넷 연결은 서로
다른 상태다.

- 같은 WLAN에서 장비 간 통신이 허용되면 인터넷이 없어도 대시보드에 접속할
  수 있다.
- 패키지와 Docker 이미지를 처음 설치할 때는 Pi의 인터넷 연결이 필요하다.
- 게스트 Wi-Fi의 `client isolation`, `AP isolation`, `무선 단말 격리`가
  켜져 있으면 두 장비 모두 인터넷은 되지만 서로 접속하지 못할 수 있다.
- 공유기 포트포워딩으로 8080 포트를 인터넷에 노출하지 않는다. 현재 화면은
  같은 신뢰 WLAN에서 사용하는 운영 화면이며 공개 인터넷용 TLS 종단점이
  아니다.

현장 공유기가 없다면 휴대전화 핫스팟에 Pi와 운영 노트북을 모두 연결한다.
하나의 Pi 무선 칩으로 동시에 안정적인 AP와 인터넷 클라이언트를 구성하는
기능은 이번 릴리스 범위가 아니다.

## 2. SD 카드 굽기

1. 운영 PC에 최신 Raspberry Pi Imager를 설치한다.
2. 장치로 **Raspberry Pi 5**를 선택한다.
3. OS로 **Raspberry Pi OS Lite (64-bit)**를 선택한다.
4. 저장장치로 배포할 microSD를 정확히 선택한다.
5. OS 커스터마이징에서 아래 값을 설정한다.

   | 설정 | 권장값 |
   |---|---|
   | hostname | `rosy-01`처럼 장비마다 고유한 이름 |
   | 사용자 | `rosy` |
   | 비밀번호 | 장비별 강한 초기 비밀번호 |
   | Wi-Fi SSID/비밀번호 | 실제 현장 WLAN 또는 핫스팟 정보 |
   | 무선 LAN 국가 | `KR` |
   | 시간대 | `Asia/Seoul` |
   | SSH | 활성화, 가능하면 공개키 인증 |

6. 이미지를 기록하고 검증이 끝난 뒤 SD 카드를 Pi에 넣는다.
7. 유선 LAN 없이 Pi 전원을 켜고 첫 부팅을 2~5분 기다린다.

Wi-Fi 비밀번호와 SSH 개인키는 Git 저장소나 공용 이미지에 넣지 않는다.
같은 이미지를 여러 장비에 복제할 때도 hostname과 자격증명은 장비마다
다르게 설정한다.

## 3. 첫 Wi-Fi 및 SSH 확인

Windows PowerShell에서 다음을 실행한다.

```powershell
ping rosy-01.local
ssh rosy@rosy-01.local
```

첫 SSH 연결에서는 표시된 호스트 키 지문이 대상 Pi의 것인지 확인한 뒤
등록한다. `.local` 이름이 해석되지 않으면 공유기 또는 핫스팟의 연결 장치
목록에서 `rosy-01`의 IPv4 주소를 찾고 다음처럼 접속한다.

```powershell
ssh rosy@192.168.1.42
```

Pi에서 네트워크를 직접 진단할 때는 다음 항목을 따로 확인한다.

```bash
nmcli radio wifi
nmcli -t -f GENERAL.CONNECTION device show wlan0
ip -4 -o addr show dev wlan0 scope global
ip route show default dev wlan0
getent ahosts www.raspberrypi.com
curl --interface wlan0 -fsSIL --max-time 8 https://www.raspberrypi.com/
```

`wlan0` 주소만 있고 마지막 두 명령이 실패하면 로컬 접속은 가능하지만 DNS
또는 인터넷 경로에 문제가 있는 상태다.

## 4. Windows에서 Rosy 배포

배포 전에 이 기능 브랜치를 검증하고 배포할 커밋으로 확정한다. 저장소 루트의
PowerShell에서 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File deploy/robot/deploy-from-windows.ps1 `
  -RobotNumber 1 `
  -PiHost rosy-01.local `
  -PiUser rosy
```

스크립트는 다음 순서로 동작한다.

1. 작업 트리가 깨끗한지 확인한다.
2. 커밋된 `HEAD`만 `git archive`로 묶고 SHA-256을 계산한다.
3. `scp`로 Pi에 전송하고 원격에서 체크섬을 재검증한다.
4. Docker 공식 Debian 저장소를 사용해 Docker Engine과 Compose 플러그인을
   설치한다.
5. `/opt/rosy`에 릴리스를 설치하고 장비 내부에서 API 토큰을 생성한다.
   신원(`ROS_DOMAIN_ID` = 40 + N, `ROSY_NAMESPACE` = `rosy_%02d`)은 `-RobotNumber`
   에서 유도한다. 기본값은 없다 — 있으면 이 스크립트로 배포한 모든 기기가 같은
   도메인으로 뜬다 (ADR D-33). 이미 다른 번호로 자리잡은 기기에 다른 번호를
   주면 설치기가 두 값을 모두 이름 대어 거절한다.
6. 기본 `core` 모드로 `rosy-core`만 빌드·기동한다.
7. Wi-Fi, LAN, DNS, 인터넷, 런타임, API, 대시보드를 검증한다.
8. 배포 PC에서 Pi의 `wlan0` 주소로 API와 대시보드에 다시 요청해 다른
   Wi-Fi 단말의 접속까지 검증한다.

배포 스크립트는 기존 `/etc/rosy/rosy.yaml`과 데이터 디렉터리를 보존한다.
작업 트리가 더럽더라도 커밋된 버전만 의도적으로 배포하려면
`-AllowDirty`를 명시할 수 있지만, 정식 배포에서는 사용하지 않는 것이 좋다.

## 5. 대시보드 접속과 초기 토큰

설치 완료 후 Pi에서 한 번만 초기 토큰을 확인한다.

```bash
sudo cat /etc/rosy/initial-credentials.txt
```

토큰을 승인된 비밀 저장소에 기록한 뒤 평문 초기 파일을 제거한다.

```bash
sudo rm -f /etc/rosy/initial-credentials.txt
```

같은 Wi-Fi의 브라우저에서 다음 주소를 연다.

```text
http://rosy-01.local:8080/dashboard
```

이름으로 접속되지 않으면 검증 스크립트가 출력한 `wlan0` IPv4 주소를 쓴다.

```text
http://192.168.1.42:8080/dashboard
```

FastAPI가 HTML/CSS/JavaScript를 직접 제공하므로 Pi에 별도 Node.js 서버는
필요하지 않다. 토큰은 브라우저 탭의 `sessionStorage`에만 보관된다.

대시보드의 `DDS / ROS GRAPH` 패널에서는 다음을 함께 확인한다.

- `DOMAIN ID`와 `NAMESPACE`가 장비 배포 대장 값과 같은지
- `DDS ISOLATION`이 `LOOPBACK ONLY`인지
- 예상하지 않은 namespace 또는 중복 노드 경고가 없는지
- 노드·토픽 수가 기동 전후 기대 범위인지
- RX/TX 그래프가 Wi-Fi 사용량 급증을 보이는지

DDNS 또는 `rosy-01.local`은 브라우저 접속 주소만 해결한다. ROS 장비 간
충돌은 장비별 `ROS_DOMAIN_ID`, 고유 namespace, loopback CycloneDDS 설정으로
막는다. 외부 노트북이 ROS DDS에 직접 접속하도록 `wlan0`로 DDS 인터페이스를
변경하지 않는다. 원격 상태 확인은 FastAPI 대시보드를 사용한다.

## 6. 설치 후 재검증

Pi에서 인터넷까지 필수로 판정한다.

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh --require-internet
```

현장 인터넷 없이 로컬 대시보드만 점검할 때는 옵션을 뺀다. 이 경우 인터넷
실패는 경고지만 Wi-Fi 주소, 런타임, API 또는 대시보드 실패는 전체 실패다.

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh
```

재부팅 후에도 확인한다.

```bash
sudo reboot
# 다시 SSH로 접속한 뒤
systemctl status rosy-runtime.service --no-pager
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh
```

## 7. 하드웨어 제어 모드 전환

첫 설치의 `ROSY_RUNTIME_MODE=core`는 FastAPI, 대시보드, ROS 미들웨어만
기동하고 UART 장치에 접근하는 `rosy-io`는 시작하지 않는다. UART 경로,
모터 방향, 하드웨어 E-stop, 소프트웨어 deadman을 실제 장비에서 승인한 뒤에만
전환한다. Raspberry Pi GPIO UART는 3.3 V 신호이므로 DYNAMIXEL 버스에 전기적으로
직결하지 말고 Pinky Pro의 검증된 half-duplex 인터페이스/레벨 변환 보드를
사용한다. 아래 단계에서는 바퀴를 띄우고 물리 전원 차단을 손 닿는 곳에 둔다.

```bash
sudo /opt/rosy/deploy/robot/configure-uart-pi5.sh
sudo reboot
# 재접속 후 motor runtime이 꺼진 core 상태에서 무토크 ping/read:
# docker compose 를 언급하며 거절하면 하드웨어가 아니라 설정 문제다 —
# 이 스크립트는 모터 런타임이 꺼졌는지 확인할 수 없으면 닫히는 쪽으로 실패한다.
sudo /opt/rosy/deploy/robot/verify/verify-motors.sh

sudoedit /opt/rosy/deploy/robot/.env
# ROSY_RUNTIME_MODE=motor 로 변경
# 초기 벤치 제한값을 확인:
# ROSY_MAX_LINEAR_MPS=0.25
# ROSY_MAX_ANGULAR_RPS=2.5
# ROSY_MAX_WHEEL_RPM=100.0
# ROSY_MOTOR_PROFILE_ACCELERATION=200
sudo systemctl restart rosy-runtime.service
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh
```

모터 명령은 `APPLIED`, `LIMITED`, `REJECTED`, `DRIVER_ERROR` 중 하나로
판정된다. 제한을 넘은 정상 숫자는 좌우 바퀴 비율을 유지한 채 축소되고,
NaN·무한대·숫자가 아닌 값은 UART 쓰기 전에 거부된다. 거부 또는 드라이버
오류가 발생하면 별도의 zero-RPM 정지를 즉시 시도하고, 확인되지 않으면
deadman이 계속 재시도한다.

`motor` 모드는 `rosy-core`와 모터 노드만 실행하므로 LiDAR가 없어도 대시보드의
저속 직접 제어를 시험할 수 있다. operator 토큰으로 접속해 `MANUAL` 모드로
전환하고 벤치 안전 확인란을 선택한 다음 방향 버튼을 누르고 있는 동안만
명령을 보낸다. 버튼 해제, 포인터 이탈, 탭 숨김, 브라우저 포커스 상실 또는
통신 오류에는 zero 명령을 보내며 core와 driver의 500 ms watchdog도 유지된다.

모터와 LiDAR를 모두 승인한 뒤에만 `.env`의 모드를 `hardware`로 승격한다.

문제가 있으면 즉시 core 모드로 되돌린다.

```bash
sudo sed -i 's/^ROSY_RUNTIME_MODE=.*/ROSY_RUNTIME_MODE=core/' /opt/rosy/deploy/robot/.env
sudo systemctl restart rosy-runtime.service
```

소프트웨어 정지는 안전 인증된 물리 E-stop을 대신하지 않는다. 실제 모터,
UART, 재부팅 복구, 열, SD 카드 로그 증가 시험이 끝날 때까지 하드웨어 운용
판정은 **HOLD**다.

## 8. 문제 해결

| 증상 | 가장 먼저 볼 항목 |
|---|---|
| Pi가 Wi-Fi에 안 보임 | Imager의 SSID 대소문자, 비밀번호, `KR`, 2.4/5 GHz 수신 범위 |
| `.local`만 실패 | 공유기 장치 목록의 IPv4로 접속; mDNS 지원/방화벽 확인 |
| 인터넷은 되지만 대시보드 접속 실패 | 게스트/AP isolation 해제, 운영 단말이 같은 WLAN인지 확인 |
| 대시보드는 되지만 인터넷 실패 | `ip route`, DNS, Captive Portal 또는 핫스팟 데이터 상태 확인 |
| 8080 포트 응답 없음 | `systemctl status rosy-runtime`, `docker compose ... ps`, 검증 스크립트 실행 |
| `/dev/ttyAMA4` 없음 | `configure-uart-pi5.sh` 실행 후 재부팅, `/boot/firmware/config.txt`의 `uart4-pi5` 확인 |
| 모터 ping 실패 | 모터 전원, 3.3 V 인터페이스 보드, baud 1 Mbps, ID 1·2, 배선 방향 확인 |
| motor 모드에서 LiDAR 오류 | `.env`가 `motor`인지 확인; `hardware`는 LiDAR도 요구함 |
| 배포 후 기존 설정이 유지됨 | 정상 동작; 설치기는 기존 `/etc/rosy/rosy.yaml`을 덮어쓰지 않음 |

여러 Pi에 반복 배포할 커스텀 `.img`가 필요해지면 공식 `pi-gen`으로 OS와
설치기까지만 자동화하고, Wi-Fi/SSH/API 비밀정보는 첫 부팅 프로비저닝 단계에
남겨야 한다. 현재 한 대를 검증하는 단계에서는 이 절차가 더 단순하고 안전하다.
