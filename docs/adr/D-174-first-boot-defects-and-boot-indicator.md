## D-174 첫 실기 부팅 결함을 고치고, 부팅 상태는 CORE 밖의 표시 계층이 사람에게 알린다

**Status:** Accepted (2026-09-22). D-173 카드의 첫 실기 부팅 결과에 대한 결정. D-161(CORE 비특권),
D-169(v1 장치 표면)를 유지한 채 그 위에 표시 계층을 얹는다. LCD·부저 편입은 이 ADR이 열지 않는다.

**Context:** D-173로 구운 `rosy-pinky-e4us`(18번, release `2026.09.22-002`)를 Pinky Pro에 꽂아
부팅했다. 사람이 볼 수 있는 부팅 신호가 없었고, 원격 접속도 되지 않았다. 장비 없이 카드만 회수해
Windows에서 ext4 루트를 읽기 전용으로 추출하고 journal을 읽었다. 확인된 사실은 다음과 같다.

| # | 결함 | 증거 | 영향 |
|---|---|---|---|
| F1 | `rosy-release-recover.service`가 `ModuleNotFoundError: No module named 'signing'`로 실패한다 | journal +7.96s. `native_release.py`는 `Path(__file__).parents[2] / "release"`로 모듈을 찾는다. 저장소(`deploy/robot/native/`)에서는 `deploy/release`지만 설치 위치(`/opt/rosy/native-runtime/`)에서는 없는 `/opt/release`다 | 복구 gate가 실패해 **`rosy-core`·`rosy-runtime.target`이 "Dependency failed"로 시작되지 않는다**. 8080 닫힘 |
| F2 | 첫 부팅은 `/etc/hostname`만 쓰고 실행 중 호스트 이름을 바꾸지 않는다 | `/etc/hostname`=`rosy-pinky-e4us`, avahi "Host name is ubuntu.local" | 재부팅 전까지 `rosy-pinky-e4us.local`로 찾을 수 없다. 라우터에는 이전 OS의 이름(`pinky-764e`)이 남는다 |
| F3 | 운영자 로그인 경로가 없다 | 이미지에 사람 계정·키 없음. cloud-init 기본값 `ssh_pwauth: false` | SSH가 publickey만 받아 원격 진단이 불가능하다. 런북의 `ssh rosy@…`는 존재하지 않는 계정이다 |
| F4 | 사람이 볼 수 있는 부팅 완료·실패 신호가 없다 | 공식 OS는 부팅 완료 시 부저를 울리고 LCD에 Wi-Fi 정보를 띄운다(`2026-09-21-pinky-pro-os-research.md:60`). 우리 이미지는 LCD·부저·LED 모두 D-169로 벤치 전용이다 | 부팅 성공, 진행 중, 실패를 현장에서 구분할 수 없다 |
| F5 | 이미지 검증이 설치 위치에서 진입점을 실행하지 않는다 | `verify-mounted-image.py`는 파일 존재만 본다. 저장소 테스트는 저장소 경로로 import한다 | F1 같은 설치 배치 의존 결함이 ARTIFACT를 통과한다 |
| F6 | `rosy-core` 사용자는 홈이 없고 `ProtectHome=true`인데 `ROS_HOME`·`ROS_LOG_DIR`가 없다 | `/etc/passwd` 홈 `/home/rosy-core`, unit에 로그 경로 없음 | 미검증. F1 뒤에 가려져 있으며 rclpy 로그 초기화 실패 가능성이 있다 |
| F7 | 같은 장치 신원으로 카드를 다시 구울 경로가 없다 | registry가 18번·이름·UID 재사용을 거부한다 | F1 수정 후 같은 로봇을 재기록하려면 신원을 새로 받아야 한다 |
| F8 | USB SD 리더에서는 `wsl --mount`가 동작하지 않는다 | 0x8007000f, 이후 디스크가 오프라인으로 남음 | 카드만으로 하는 진단에는 별도 읽기 전용 도구가 필요하다 |

첫 부팅 개인화(`PROVISIONED`, +26.3s), provision gate, Wi-Fi 연결(`192.168.1.201`), 서명 이미지와
매체 무결성은 정상이었다. 결함은 런타임 기동 경로와 사람·운영자 쪽 가시성에 있다.

**Decision:**

1. **F1·F5: 설치 배치에서 실행해 보고서야 통과시킨다.** 네이티브 런타임 도구는 저장소 상대 경로가
   아니라 설치 루트 기준으로 의존 모듈을 찾는다(`signing.py`를 `native-runtime`에 함께 설치). 이미지
   검증은 마운트된 rootfs 안에서 `recover-release.sh`의 import와 dry-run을 실제로 실행한다. 저장소
   계약 시험은 `/opt/rosy` 배치를 임시 디렉터리에 재현해 실행한다.
2. **F2: 신원은 적용 즉시 살아 있는 시스템에 반영한다.** 첫 부팅은 `/etc/hostname`과 함께 실행 중
   호스트 이름을 바꾸고 avahi가 새 이름을 광고하게 한다.
3. **F3: 운영자 접근은 카드별 공개키로만 연다.** `prepare-rosy-sd.ps1`이 운영자 공개키를 개인화
   bundle에 넣고, 첫 부팅이 전용 `rosy` 계정에 설치한다. 비밀번호 로그인은 계속 끈다. 이미지 공통
   부분에는 키를 넣지 않는다(장치 중립).
4. **F4: 부팅 상태는 CORE 밖의 표시 계층이 알린다.** 표시는 CORE 기동을 막지 않고(`Wants`),
   CORE에 권한을 주지 않는다. 단계는 `BOOTING → PROVISIONED → CORE_READY` 또는 `FAILED(<unit>)`이다.
   - **T0(지금, 새 장치 권한 없음):** `rosy-boot-status` 서비스가 systemd 상태로 단계를 계산해
     `/run/rosy/boot-status.json`에 쓴다. Pi 보드 ACT LED 패턴(준비=heartbeat, 실패=빠른 점멸)으로
     표시하고, HDMI 콘솔 배너(`/etc/issue`)에 이름·IP·단계를 띄우고, avahi `_rosy._tcp` 서비스
     TXT로 단계를 광고한다.
   - **T1(후속 ADR):** 공식 OS처럼 LCD(ST7789, `/dev/spidev0.0`)에 이름·IP·단계를 보여 주는 전용
     unit. D-169의 좁은 예외(표시 전용 unit에 spidev0.0 + gpiochip만)이며 벤치 SPI 증거가 먼저다.
   - **T2(후속 ADR):** 부저. 핀·구동 방식이 공개되지 않았으므로 공식 OS 카드에서
     `capture-vendor-baseline.sh`로 핀과 서비스를 확인한 뒤 결정한다.
5. **F6: `rosy-core`는 상태 디렉터리 아래에 ROS 홈과 로그를 둔다**(`ROS_HOME`, `ROS_LOG_DIR` =
   `/var/lib/rosy/...`). 계약 시험으로 고정한다.
6. **F7: 같은 장치의 재기록은 이전 receipt로만 허용한다.** 같은 `device_uid`·이름·번호의 receipt를
   제시하면 registry 재사용을 허용하고, 새 receipt는 이전 것을 가리킨다.
7. **F8: 카드 진단 도구는 읽기 전용으로 저장소에 둔다.** 물리 디스크를 읽기 전용으로 열어 ext4에서
   진단 파일(provisioning 상태, journal, unit)만 꺼낸다. Wi-Fi 연결 파일은 읽지 않는다.

**Alternatives:**

- 부팅 신호를 CORE에 넣기: CORE는 인터넷 노출·비특권이 원칙이고(D-161), 실패한 CORE는 자기 실패를
  알릴 수 없다.
- LCD·부저를 지금 바로 배관하기: 부저 핀은 미확인이고 LCD SPI 충돌은 실기 증거가 없다(D-169). 넓힌
  권한만 남고 검증은 없다.
- 비밀번호 SSH 허용: 모든 카드가 같은 초기 비밀번호를 갖게 되어 D-33의 "공통 기본값 금지" 정신과
  충돌한다.
- 결함만 고치고 표시는 나중에: 다음 실패도 이번처럼 카드를 회수해야만 보인다.

**Consequences:** 다음 카드는 전원만 켜면 보드 LED, HDMI 콘솔, 네트워크(`_rosy._tcp`) 세 경로로
상태가 보이고, 운영자는 자기 키로 접속한다. 이미지 검증은 설치 배치 실행 때문에 느려진다. 카드마다
운영자 공개키 관리가 필요하다. LCD·부저가 들어오기 전까지는 공식 OS만큼 즉각적인 신호가 아니다.

**구현·처리 계획:**
[`docs/plans/2026-09-22-pinky-first-boot-fixes.md`](../plans/2026-09-22-pinky-first-boot-fixes.md).
완료 기준: release `003`을 같은 카드(18번 신원 유지)에 다시 구워 전원 투입 후 5분 안에 (a) ACT LED
heartbeat, (b) `rosy-pinky-e4us.local` 해석, (c) `_rosy._tcp` TXT `stage=CORE_READY`, (d) 운영자 키 SSH,
(e) 8080 `/api/v1` 응답을 확인하고, 이어서 런북 G0-G2를 실행한다.

**Validation / Transition:** 각 결함은 먼저 실패하는 계약 시험으로 재현한 뒤 고친다. F1은 설치
배치 재현 시험과 마운트 이미지 실행 검증이 함께 적색→녹색이어야 닫힌다. 부팅 표시 T0은 host 시험
(상태 계산)과 실기 관찰(LED·콘솔·mDNS) 둘 다 있어야 닫힌다. T1·T2는 각각 새 ADR로 연다.
