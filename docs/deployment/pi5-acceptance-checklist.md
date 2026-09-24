# Raspberry Pi 5 실기 인수 체크리스트 (WP-6 / WP-7)

- **Document ID:** ROSY-DEPLOY-ACCEPT-001
- **Status:** 인계 문서 — 아래 게이트는 **아직 하나도 통과하지 않았다**
- **Related:** `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md` §12,
  `docs/deployment/release-signing-key.md`, `docs/deployment/release-retention.md`

## 0. 이 문서의 위치

WP-1(릴리스 계약)과 WP-2(불변 layout·updater)는 하드웨어 없이 구현·검증했다.
`BUILD_GO`부터는 실제 Pi 5, SD 카드, 서명 환경이 필요하다. 이 문서는 그 지점에서
사람이 이어받기 위한 것이다.

**현재 게이트 상태 — 어느 것도 통과로 표시하지 않았다:**

| Gate | 상태 | 막고 있는 것 |
|---|---|---|
| `BUILD_GO` | **HOLD** | native ARM64 빌드 호스트에서 이미지를 만든 적 없음 |
| `BOOT_GO` | **HOLD** | 실제 Pi 5가 그 이미지로 부팅한 적 없음 |
| `NETWORK_GO` | **HOLD** | 실기 Wi-Fi 프로비저닝·복구·peer 접속 미검증 |
| `UPDATE_GO` | **HOLD** | 실기 update/rollback 미검증 (tmpdir 검증만 완료) |
| `MOTOR_HOLD` | **정상 상태** | UART·모터 미승인. 유지되어야 한다 |
| `FIELD_GO` | **HOLD** | 위 전부의 후행 |

컨테이너 health가 초록이어도 `MOTOR_HOLD`는 풀리지 않는다. `BUILD_GO`는
`BOOT_GO`를 대신하지 않는다.

## 1. 준비물

- **Raspberry Pi 5 8 GB** — 인수 대상 장비
- **native ARM64 빌드 호스트** — Raspberry Pi OS arm64가 도는 Pi 5.
  인수 대상과 같은 장비를 써도 되지만, 이미지를 구우면 그 장비의 OS가 지워지므로
  **별도 장비 1대를 권장**한다. x86 QEMU 빌드는 개발 검증용이며 최종 릴리스
  이미지의 근거로 삼지 않는다(설계 §7.1).
- **SD 카드 32 GB 이상 2장** — 최소 용량 근거는 `release-retention.md` §2.
  1장은 굽기 대상, 1장은 롤백 실패 시 복구용.
- **서명 환경** — `release-signing-key.md` §3~5. 개인키를 빌드 호스트에 두지 않는다.
- **사업장 Wi-Fi 자격정보** — SSID, PSK, 국가 코드
- **두 번째 단말** — peer 접속 확인용 (노트북 또는 휴대폰)
- **모니터·키보드** 또는 **UART 콘솔** — 부팅 실패 시 화면을 봐야 한다. UART 콘솔은 Pi 5 **디버그 3핀 UART**
  (`ttyAMA10`, 115200)다. GPIO 14/15(`ttyAMA0`)는 LiDAR 버스라 콘솔을 두지 않는다(D-192 2026-09-24 보완)

## 2. WP-6 착수 전에 검증할 미확인 가정

아래는 설계가 전제하지만 **아직 아무도 확인하지 않은 것**이며,
`deploy/image/inputs.lock.yaml`에 `verified: false`로 기록되어 있다.
`deploy/image/verify-inputs.sh`가 이 값들이 남아 있는 한 빌드를 거부한다 —
고정되지 않은 입력으로 만든 이미지는 provenance를 진술할 수 없고, 그것이
설계 §7.2가 요구하는 유일한 것이다.

버리는 이미지 한 장으로 먼저 확인하는 편이 싸다. 하나라도 어긋나면
manifest의 `target.os_suite`부터 바뀐다.

- [ ] **`rpi-image-gen` v2.7.0이 실제로 필요한 일을 하는가.** 태그와 전체 commit
      SHA를 lock 파일에 기록한다.
- [ ] **Raspberry Pi OS Lite arm64 `trixie`가 릴리스 대상으로 준비되어 있는가.**
      아니면 `bookworm`으로 후퇴하고 설계 §6/§7.1의 suite 표기를 함께 고친다.
- [ ] **Docker apt 저장소(`download.docker.com/linux/debian`)에 trixie suite가
      올라와 있는가.** 현재 `deploy/robot/install-pi.sh`가 이 경로를 쓴다.
      없으면 위와 같은 후퇴가 필요하다.
- [ ] `ros:jazzy-ros-base`의 arm64 이미지 digest를 고정했는가.
- [ ] 빌드 호스트의 Docker Engine / Compose plugin 정확한 버전을 lock에 기록했는가.

## 3. BUILD_GO — 이미지와 부속 산출물

native ARM64 빌드 호스트에서:

- [ ] 고정된 입력(§2의 lock)으로 이미지를 빌드한다
- [ ] 산출물이 모두 생성되었는가 — 설계 §7.4
      - `rosy-pi5-<release-id>.img.xz`
      - `rosy-pi5-<release-id>.bmap`
      - `manifest.json`
      - `SHA256SUMS`, `SHA256SUMS.sig`
      - `sbom.spdx.json`
      - `release-notes.md`
- [ ] `python3 deploy/release/manifest.py dist/<release-id>/manifest.json --json` 통과
- [ ] 서명 환경에서 `SHA256SUMS`에 서명하고, 빌드 호스트에서
      `verify_release_files()`가 통과하는가
- [ ] 이미지 안에 비밀이 없는가 — `deploy/release/secret_scan.py`의 matcher를
      마운트한 이미지 트리에 적용한다 (공통 비밀번호, API 토큰, Wi-Fi PSK, SSH 개인키)
- [ ] 이미지에 release 공개키가 들어 있고 개인키는 없는가
- [ ] 필수 systemd unit이 enable 되어 있고 순서가 맞는가 —
      `rosy-release-recover.service`가 `rosy-runtime.service`보다 **먼저** 실행되며
      runtime이 이를 `Requires=`/`After=`로 의존하는가
- [ ] UART overlay는 존재하되 motor service는 비활성인가
- [ ] 기본 `ROSY_RUNTIME_MODE=core`인가
- [ ] 이미지 압축 해제 후 checksum 재검증이 통과하는가

### 3.1 자동화된 부분

§3의 항목 중 상당수는 `deploy/image/verify-artifacts.sh`가 실행한다.

```bash
sudo losetup -Pf --show rosy-pi5-<release-id>.img   # 압축 해제 후
sudo mount /dev/loopXp2 /mnt/rosy
ROSY_IMAGE_MOUNT=/mnt/rosy ./deploy/image/verify-artifacts.sh dist/<release-id>
```

`ROSY_IMAGE_MOUNT` 없이 실행하면 **BUILD_GO를 보고하지 않고 실패한다.** 배포
디렉터리만 검사하는 것은 §12.2가 요구하는 이미지 검사가 아니기 때문이다.

`deploy/release/image_checks.py`가 검사하는 것 (전부 tmpdir 트리로 테스트되어
있으며, 실기에서는 마운트된 실제 트리에 같은 코드가 돈다):

- 필수 unit 존재와 **enable 여부** — 아무도 enable 하지 않은 unit을 넣는 것은
  넣지 않은 것과 같다
- `rosy-runtime.service`가 recovery gate를 `Requires=`로 의존하고 `After=`로
  정렬하는지. **`Wants=`이면 홀드된 장비가 그냥 부팅한다**
- release 공개키 존재, 개인키 부재 (확장자와 내용 양쪽)
- 기본 `ROSY_RUNTIME_MODE=core`, UART overlay 존재하되 motor unit 비활성
- **CORE 계정이 로그인 계정과 다른 uid인지** — Host Agent 계약 §3의 전제 조건
- OCI archive 존재 (첫 부팅에 인터넷이 필요하면 안 된다)
- 이미지 트리 전체 secret 스캔

**통과하면 `BUILD_GO`. 이것으로 `BOOT_GO`를 대신하지 않는다.**

## 4. BOOT_GO — 실제 부팅

- [ ] SD에 기록한다 (Raspberry Pi Imager Custom Image 또는 검증된 CLI + bmap)
- [ ] **유선 랜을 연결하지 않은 채** 부팅한다
- [ ] **한 번도 활성화된 적 없는 장비**가 스스로 RECOVERY HOLD에 들어가지 않는가.
      `rosy-release-recover.service`는 모든 부팅에서 runtime보다 먼저 도는데,
      "활성화 레코드 없음"을 홀드로 취급하면 박스에서 꺼낸 로봇이 첫 부팅에서
      스스로 잠기고 자기 첫 설치마저 거부한다. `updater._settled`가
      release-state.json 유무로 "아직 설치 안 됨"과 "레코드를 잃음"을 구분한다 —
      실기에서 이것이 실제로 성립하는지 확인할 것
- [ ] CORE가 기동하고 대시보드가 뜨는가
- [ ] **인터넷 없이** 기동이 완료되는가 — OCI archive 로컬 import가 동작해야 한다
- [ ] runtime mode가 `core`이고 `rosy-motor`/`rosy-io`가 시작되지 않았는가
- [ ] 전원 재인가 후 CORE가 자동 복구되는가

## 5. NETWORK_GO — 두 모드 모두

프로비저닝은 두 운용 모드가 같은 설정 AP를 공유한다(ADR D-26).

### 5.1 공통 — 첫 부팅 프로비저닝

- [ ] `ROSY-SETUP-<short-id>` AP가 자동으로 열리는가
- [ ] `http://10.42.0.1/setup`에서 설정 UI가 뜨는가
- [ ] setup PSK가 **LCD에만** 표시되고 로그·API에는 없는가
- [ ] 국가 코드·SSID·PSK·Robot ID·hostname을 입력할 수 있는가
- [ ] **틀린 PSK를 넣으면** 후보를 폐기하고 설정 AP로 돌아오며, 구체적 실패 사유를
      보여주는가 (기존 프로파일이 보존되어야 한다)
- [ ] 성공하면 설정 AP와 setup endpoint가 **비활성화**되는가
- [ ] 어떤 응답·로그에도 Wi-Fi 비밀번호가 없는가

### 5.2 `SITE_STA` (기본 모드)

- [ ] 사업장 WLAN에 STA로 붙는가
- [ ] 다른 단말에서 `http://rosy-NN.local:8080/dashboard`로 접속되는가 (mDNS)
- [ ] mDNS 미지원 단말에서 `wlan0` IPv4로 접속되는가
- [ ] **인터넷 도달**과 **peer 도달**을 각각 별도로 기록했는가 — 공유기의
      client isolation으로 peer만 실패할 수 있다
- [ ] 인터넷을 차단해도 로컬 대시보드가 유지되는가

### 5.3 `RELAY_AP_STA` (장비별 옵트인)

- [ ] 설정에서 릴레이를 켜고 재부팅하면 STA 연결을 유지한 채 자체 AP가 열리는가
- [ ] 사용자 단말이 **로봇 AP를 경유해** 대시보드에 접속되는가
- [ ] 릴레이 AP의 자격정보가 설정 AP의 것과 **다른가** (NET-005)
- [ ] **상위 업링크를 끊어도** 로봇 AP 서브넷 안에서 조회·제어가 유지되는가
- [ ] 상위 공유기 채널이 바뀔 때 로봇 AP가 따라가는지, 그때 접속이 끊기는지 기록
- [ ] 대시보드 네트워크 카드가 현재 모드를 `RELAY_AP_STA`로 표시하는가

### 5.4 복구 AP

- [ ] 이미 프로비저닝된 장비가 **짧은 WLAN 단절만으로** recovery AP를 열지 않는가
      (`NETWORK_HOLD`에 머물러야 한다)
- [ ] 대시보드에서 다음 재부팅의 recovery mode를 예약하면 동작하는가
- [ ] 전원이 꺼진 장비의 FAT boot partition에 빈 `rosy-recovery` marker를 넣으면
      동작하는가
- [ ] recovery 요청이 **한 번만** 소비되는가 — 다음 부팅에 다시 적용되면 안 된다
- [ ] recovery boot에서 `core` 모드가 강제되고 motor/io가 정지했음을 확인한 뒤에만
      AP가 열리는가
- [ ] setup endpoint가 AP 인터페이스에서만 listen하고, 20분 무활동 후 닫히는가

## 6. UPDATE_GO — 실기 update와 rollback

서명 번들 staging·activation·rollback·전원손실 상태 복구는 임시 디렉터리에서 검증되어 있다
(`test_release_bundle.py`, `test_release_delivery.py`, `test_release_updater.py`).
실제 Pi 검증은 모두 HOLD다. ⚠는 아직 CLI와 연결되지 않은 통합 구현 항목이다.

- [ ] 정상 번들 설치 → `current`가 새 릴리스, `previous`가 이전 릴리스
      (서명 번들 staging CLI는 로컬 구현됨. 실제 Pi 시험은 HOLD; github-updates.md 참조)
- [ ] **손상된 번들** 거부 — payload를 1바이트 바꾼다 → `CHECKSUM_MISMATCH`
- [ ] **미서명 번들** 거부 → `SIGNATURE_MISSING`
- [ ] **다른 키로 서명된 번들** 거부 → `SIGNATURE_INVALID`
- [ ] **보드 불일치 manifest** 거부 → `MANIFEST_TARGET_MISMATCH`
- [ ] **health 실패 rollback** — 일부러 깨진 CORE 이미지를 담은 번들을 만들어
      90초 bound 안에 이전 릴리스로 돌아오는가
- [ ] **업데이트 중 전원 차단** — 활성화 도중 전원을 뽑는다. 재부팅 시
      `rosy-release-recover.service`가 runtime보다 먼저 돌고, 이전 릴리스가
      `core`로 올라오는가
- [ ] 위 모든 경우에 `rosy-motor`/`rosy-io`가 **시작되지 않았는가**
- [ ] ⚠ 대시보드에 current/previous/staged와 실패 사유가 표시되는가
- [ ] 롤백 후 이전 릴리스의 컨테이너 이미지가 남아 있는가 —
      `release-retention.md` §4의 prune 금지 규칙이 지켜지는가
- [ ] ⚠ 활성화 성공 후 staging 디렉터리가 정리되는가
      (`storage.clear_staging`. 롤백 경로에서는 정리하지 않는 것도 함께 확인)
- [ ] 여유 공간 부족 시 업데이트를 **시작하지 않고** 거부하는가
      (`Updater.check_headroom`. 거부 사유에 필요·가용 용량이 숫자로 나오는지)
- [ ] 이벤트가 상한에서 회전하고, **맵은 상한을 넘어도 삭제되지 않는가**

## 6.5 Host Agent — 실기에서만 확인 가능한 것

거부 판정 전체는 `test/test_host_agent.py`가 소켓 없이 검증한다(가드 14개를
하나씩 무력화해 잡히는 것 확인). 아래는 실기가 아니면 확인할 수 없는 것뿐이다.

- [ ] `/run/rosy/host-agent.sock`이 `root:rosy 0660`으로 생성되는가
- [ ] **CORE 컨테이너가 소켓에 연결되는가** — `:ro` 마운트로도 명령이 전달된다
      (`:ro`는 inode 교체만 막는다. 이것이 보호로 오해되면 안 된다)
- [ ] **uid 1000이 아닌 계정**으로 접속하면 즉시 끊기는가
- [ ] **`ROSY_UID`가 로그인 계정과 분리되어 있는가** — 계약 §3의 전제 조건이다.
      Raspberry Pi OS Lite 기본 uid 1000은 사람이 로그인하는 계정이므로, 분리되지
      않았다면 그 계정의 SSH 세션이 `release.install`과 `system.reboot`을 호출할 수
      있다. **이미지 빌드에서 `rosy` 시스템 사용자를 만들었는지 반드시 확인할 것**
- [ ] 재부팅 후 stale 소켓이 남지 않는가 (`/run`은 tmpfs)
- [ ] `nmcli` / `systemctl` 호출이 실제로 동작하는가 — 지금까지 검증된 것은
      인자 리스트 구성뿐이다
- [ ] 감사 로그(JSONL)에 PSK·토큰·개인키가 없는가

## 7. MOTOR_HOLD — 유지되어야 하는 상태

이 절은 통과시키는 것이 아니라 **깨지지 않았음을 확인**하는 것이다.

- [ ] 위 모든 시험 뒤에도 runtime mode가 `core`인가
- [ ] **모터 모드로 승인된 장비에서** 업데이트를 실패시켰을 때, 롤백 뒤에도
      `core`인가 (updater가 이전 record의 mode를 `core`로 강제한다 —
      실기에서 반드시 확인할 것)
- [ ] 열 상승과 저장소 로그 증가를 기록했는가 (설계 §12.3 10단계)
- [ ] UART·모터 승인은 별도 commissioning 절차로 남아 있는가
      (`deploy/robot/verify/verify-motors.sh`, `docs/deployment/power-bench-verification.md`)

모터를 돌리는 순간부터는 이 문서가 아니라 현장 안전 절차의 영역이다.

## 7.5 BATTERY_GO — 실기에서만 확인 가능한 것

잔량 계산과 단계 머신은 단위 테스트가 덮지만, **팩 실물과 분압 회로가 맞는지는
멀티미터로만 확인된다.** `ros_bridge`는 이 저장소의 테스트 환경에서 임포트조차
되지 않으므로(rclpy 부재) 아래 항목이 그 부분의 유일한 검증이다.

- [ ] 만충 직후 팩 전압을 멀티미터로 재고 `GET /api/v1/robot/battery`의 `voltage`와
      비교했는가. 차이가 0.1 V를 넘으면 `main_node.cpp`의 분압비(13/28)가 이
      하드웨어와 맞지 않는 것이다
- [ ] 방전 과정에서 최소 3점(만충 / 중간 / 20% 부근) 실측 전압과 보고 percent를
      기록했는가. 8.4 V→100%, 6.4 V→0% 근처로 나오는가
- [ ] **부팅 직후 크리티컬이 발화하지 않는가.** 3S 상수(12.6/10.0)가 남아 있으면
      percent가 0으로 고정되어 첫 표본에서 `RETURN_HOME`/E-Stop이 걸린다
- [ ] 정지 상태에서 모터를 급가속시켰을 때 percent가 크게 떨어지지 않고 E-Stop이
      걸리지 않는가 (필터·표본 수가 새그를 거르는지)
- [ ] **아무도 로봇 앞에 없는 상태에서** 20% 미만 주황, 10% 미만 빨강 점멸이
      보이는가. 근접 정보창 15초가 끝난 뒤에도 유지되어야 한다
- [ ] `STANDBY`로 내려간 뒤에도 경보 점멸이 유지되는가
- [ ] `deep`(5%) 도달 시 모터가 먼저 멈추고
      `/var/lib/rosy/battery-shutdown-request.json`이 생성되는가
- [ ] 유예 시간 안에 충전기를 꽂으면 파일이 사라지고 **호스트가 꺼지지 않는가**
- [ ] 유예를 넘기면 호스트가 실제로 정상 종료되는가 (`journalctl -t rosy-lowbatt`)
- [ ] 그 상태로 재부팅했을 때 남아 있던 센티넬로 **다시 꺼지지 않는가**
      (`/var/lib/rosy`는 영속이므로 stale 가드가 실제로 도는지 확인)

## 7.6 DOCK_GO — 도크 실물이 생긴 뒤에만 확인 가능한 것

상태머신·재시도·인터록은 단위 테스트가 덮지만, **기구가 실제로 오차를 흡수하는지,
접점이 정말 통전하는지는 실물로만 확인된다.** `ros_bridge`의 도킹 조정부는 이
저장소에서 임포트되지 않으므로(rclpy 부재) 아래가 그 부분의 유일한 검증이다.

- [ ] 도크 전면 깔때기가 좌우 오차 ±2 cm 를 흡수하는가. 시작 포즈를 좌/우/정면
      각각으로 흩어 10회씩 진입시켜 성공률을 기록한다
- [ ] 접점 저항을 100 사이클 전후로 측정해 열화 폭을 기록했는가
- [ ] **도크가 코스트맵에 장애물로 찍히는가, 그리고 접근 구간 면제가 실제로
      풀리는가.** `docking/collision_exemption` 토픽만으로는 Nav2 가 반응하지
      않는다 — 로컬 코스트맵 연동이 실기에서 성립하는지 확인할 것
- [ ] 스테이징 도착 후 검출기가 도크를 획득하기까지의 시간을 기록했는가
- [ ] 접근 실패 시 후진→재스테이징 재시도가 실제로 도는가
- [ ] **접점은 닿았는데 전류가 없는 상황**을 인위로 만들어(접점에 절연 테이프)
      `DOCKED`에 머물고 `CHARGING`으로 넘어가지 않는가. 재착좌가 도는가
- [ ] 언도킹이 오도메트리만으로 완주하는가. 도크에 물린 채 LiDAR/카메라가
      무엇을 보는지도 함께 기록한다
- [ ] **도크가 부하 없이 통전하지 않는가.** 로봇 없이 접점을 멀티미터로 재서
      0 V 인지 확인한다 — 이 항목이 실패하면 나머지는 볼 필요가 없다
- [ ] 도크가 부하 이탈 시 즉시 차단하는가
- [ ] **4%에서 도킹한 로봇이 충전되는가, 그리고 꺼지지 않는가** (D-27 억제).
      `journalctl -t rosy-lowbatt` 에 halt 가 없어야 한다
- [ ] **가짜 도크가 셧다운을 막지 못하는가.** `charging: true` 를 상시 반환하는
      스텁을 같은 주소에 올리고, 전압이 계속 떨어질 때 억제가 성립하지 않는지
      확인한다 (2중 소스 방어)
- [ ] 20% 도달 시 임무를 접고 도크로 출발하는가. 수동 조작 중이면 보류되는가

## 8. 기록

각 게이트마다 남긴다: 날짜, 장비 시리얼, release_id, git revision, 이미지
digest, 통과/실패, 실패 시 오류 코드와 로그. **증거 없는 게이트는 통과로 표시하지
않는다.** 통과하지 못한 게이트는 HOLD로 남기고 그 이유를 적는다.
## 2026-09-13 current Rosy OS source/device checkpoint

The source and ROS-simulation gates are currently GO. An emulated Buildx
validation produced development candidates for the `core` and `io` targets,
but this does not satisfy `BUILD_GO`: the images are not signed or published,
and no Pi OS image has been flashed. `BOOT_GO`, `NETWORK_GO`, `UPDATE_GO`, and
`FIELD_GO` therefore remain HOLD. The next evidence must be retained from the
actual Pi installation and JSON readback before enabling motor, camera,
payload, or OMX capabilities.
