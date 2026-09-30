## D-387 로봇은 카드 이미지까지 모든 계층을 저장소 릴리스에서 네트워크로 받고, 운영자가 승인하면 한 대씩 자동으로 펼친다 — 쓰는 중인 로봇은 건드리지 않는다

**Status:** Proposed (2026-10-01). 문서만 있다. 구현 GO, DEVICE·FIELD 승격, 로봇 조작이 아니다. 사용자가 고른 운용 방식은 "승인 후 자동"이다.

- [D-225](D-225-update-without-reflash-and-faster-card-writes.md)의 세 계층 모델을 네 계층으로 넓힌다. D-225가 "보류"로 둔 Pi 펌웨어 A/B와, 기각한 RAUC 계열은 **4계층(전체 이미지)에서만** 다시 연다.
- D-388 이미지 계층 동기화(`feat/release-image-layer-sync`, 미병합, 실기 2026-10-02)를 2계층의 전제로 둔다.

**번호:** 2026-10-01에 D-385가 세 브랜치에서 충돌해 다시 매겼다. main의 D-385는 `feat/expressive-rosy`, D-386은 `omx-sim-phases`, 이미지 계층 동기화는 D-388(`feat/release-image-layer-sync`), 긴급 카드 쓰기는 D-389(`fix/card-write-confirm-and-artifact-download`)다. 이 ADR은 D-387이다.

### Context

**1. 계층과 지금 상태**

사용자가 합의한 계층 모델이다. 코드 사실은 main `ab8f08ee` 기준이다.

| 계층 | 내용 | 지금의 갱신 경로 | 되돌림 |
|---|---|---|---|
| 1 앱 payload | `/opt/rosy/releases/<id>`(`install/`, 릴리스 사본 `deploy/robot/native/`) | PC `rosy-release-push.ps1`이 ssh/scp로 보내고 `activate-release.sh` → `native/native_release.py activate`를 부른다 | `current`/`previous` 링크와 journal을 쓴다. `rosy-runtime.target` 시작이 실패하면 자동으로 되돌린다. 이 실패는 `rosy-core.service` `ExecStartPost=wait-core-ready.py`가 45 s 안에 준비되지 못할 때 생긴다. 부팅 때는 `recover()`가 복구한다 |
| 2 이미지 계층 | 유닛, `/opt/rosy/native-runtime`, udev, modprobe | 지금은 손으로 깐다(`rosy-release-push` 스킬 6단계). D-388는 릴리스 안의 `sync-image-layer.py`를 PC가 부르게 한다 | D-388의 백업 매니페스트, 롤백 때 복원, `pending.json` |
| 3 기반 시스템 | apt 집합·핀, `/usr/local` 파이썬, `config.txt`/`cmdline.txt`, 커널·모듈 | 카드를 다시 굽는 것뿐이다 | 없다 |
| 4 전체 이미지 | 파티션, 루트 파일시스템 전체 | 카드를 다시 굽는다(D-164, D-291, D-180/D-187 readback) | 옛 카드 |

- **자리를 잡지 못한 두 번째 경로.** Docker 시대의 `release/updater.py`, `delivery.py`, `host_agent.py`, `host_agent_server.py`와 `rosy-release` CLI가 있다.
  - 이 경로에는 다음이 있다: 스테이징, 세대 스냅샷, `recovery-hold.json`, administrator와 `confirmed=true`를 요구하는 호스트 에이전트 허용 목록(`release.install|rollback|clear_hold`), 감사 로그.
  - 네이티브 이미지는 이 경로를 깔지 않는다. `rosy-update-check.service`/`.timer`는 `install-update-tools.sh`만 깐다. `customize-rootfs.sh`의 enable 목록에 없고, `cli.py`는 `os_suite`로 bookworm과 trixie만 받는다.
  - GitHub polling(`cli.py check --download`)은 D-197/D-198이 퇴역시켰다. 내려받기는 `.part`에 받아 크기와 sha256을 검사하지만, 이어받기와 delta는 없다.
- **신뢰.** Ed25519 서명이 `SHA256SUMS`의 바이트 그대로를 덮는다(`release/signing.py`). 로봇은 `/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem`으로 검증한다. 개인 키는 오프라인 운영 PC에 있다(D-145/D-146).
- **런타임 id.** 릴리스의 `python-runtime.sha256`이 이미지의 `/usr/local/share/rosy/python-runtime.sha256`과 같아야 한다(D-189). 이 값은 `device-python-requirements.txt` 파일 전체의 sha256이다.
- **잠금.** `native_release.py`는 `native-release.lock`에 flock을 걸고, 잡혀 있으면 `NATIVE_RELEASE_BUSY`로 거절한다. 로봇이 움직이는지, 미션이나 teleop 중인지는 **아무도 보지 않는다**.
- **Fleet(`src/site/fleet`).** 릴리스 카탈로그와 업데이트 엔드포인트가 없다. 릴리스 정보는 발견 단계의 `release` 문자열뿐이다.
  - 유휴 판정은 디스패치용 술어다(`server/app.py`): online, 대기 작업 없음, goal 없음, `navigation`이 IDLE/ARRIVED/CANCELED/FAILED 중 하나, `mode`가 IDLE 또는 NAVIGATION, 능력 저하 없음, estop 거짓.
  - `roster.removal_blockers`와 `fleet_action_claims`(`lease_until`)가 있다.
  - 스키마에는 `battery`와 `battery_status.charging`이 있지만 `docked` 필드는 없다.
- **등록과 토큰(D-361).** Fleet은 로봇별 operator 토큰을 AES-GCM으로 봉인해 보관한다. administrator 코드는 받지 않는다. CORE의 `POST /api/v1/host/release/install|rollback`은 admin 권한이 필요하다. 그래서 **지금 콘솔은 설치를 부를 수 없다**. D-382는 통신 적합성만 판정한다.
- **CORE의 바쁨 개념.**
  - 모드 상태기계(IDLE/MANUAL/NAVIGATION/DOCKING/EMERGENCY)와 도킹 슬롯(`MODE_CONFLICT`)이 있다.
  - `feat/calibration-session-mode`(a527920a, 미병합)가 교정 세션 리스를 더한다. 리스가 살아 있으면 `activity: CALIBRATING`이 되고, 다른 토큰의 teleop, mode, line-follow 쓰기는 409를 받는다.
  - teleop 리스와 미션 진행 잠금은 CORE에 없다.

**2. 2026-10-01 사고.** 에이전트 세션 셋이 조율 없이 같은 로봇에 푸시하거나 재시작했고, 그 가운데 하나가 교정 주행을 끊었다. 막을 장치가 없었다.
- `native-release.lock`은 전환 몇 초 동안만 잡힌다.
- ssh 재시작과 D-388의 유닛 재시작은 그 잠금을 아예 거치지 않는다.

**3. 2026-10-01 교훈 네 건.** 설계가 각각을 어떻게 막는지는 결정 12에 적는다.
- `payload-runtime-id-hashes-comments-too`: 주석을 고친 것만으로 모든 로봇이 payload를 받지 못하게 됐다.
- `blanket-path-rewrite-hits-on-device-release-paths`: 저장소 경로를 일괄로 바꾸면서 기기의 릴리스 경로까지 바꿨다.
- `payload-push-leaves-the-image-layer-stale`: payload 푸시 뒤에도 유닛과 udev가 옛것으로 남았다.
- `card-readback-slows-under-parallel-cpu-load`: 2026-10-01 재발 때 readback이 CPU를 빼앗겨 0.2~4 MB/s로 떨어졌다.

**4. 외부 사실.** 2026-10-01에 조사했다. **V**는 1차 출처로 확인한 것, **A**는 가정이라 기기에서 확인해야 하는 것이다.

- **V** — `reboot "0 tryboot"`은 한 번만 켜지는 tryboot 플래그를 세운다. firmware는 `[tryboot]` 조건 절을 적용한다. `tryboot_a_b=1`이 없으면 `config.txt` 대신 `tryboot.txt`를 읽고, 있으면 `autoboot.txt`의 `[tryboot]` `boot_partition`으로 파티션을 바꾼다. 다음에 리셋하면 플래그가 지워져 원래 설정으로 부팅하고, `autoboot.txt`를 고쳐야 커밋된다. 출처: https://www.raspberrypi.com/documentation/computers/config_txt.html#autoboot-txt
- **V** — firmware는 부팅 시도를 세지 않는다. 멈춘 부팅을 되돌리려면 리셋이 필요하고, 그래서 watchdog이 있어야 한다. 관련 설정은 `dtparam=watchdog=on`, `kernel_watchdog_timeout`, `kernel_watchdog_partition`이다. 출처: 위 문서, https://bootlin.com/blog/safe-updates-using-rauc-on-raspberry-pi-5/
- **A** — 사용자 공간이 멈췄을 때 리셋되려면 systemd `RuntimeWatchdogSec`와 cmdline `panic=N`이 함께 있어야 한다. 1차 출처를 찾지 못했다.
- **V** — Ubuntu의 `piboot-try` A/B는 25.10(`flash-kernel-piboot`, `current/`·`new/`·`old/`, `os_prefix`, `[tryboot]`)부터다. 출처: https://ubuntu.com/hardware/docs/boards/explanations/piboot-ab/, https://launchpad.net/ubuntu/+source/flash-kernel/+changelog
- **A** — 24.04 noble에는 이것이 백포트되지 않았다. 확인은 기기의 `apt policy flash-kernel`로 한다.
- **A** — noble의 `flash-kernel`은 커널 패키지를 갱신할 때 `/boot/firmware`에 커널과 initrd를 복사한다. 그래서 커널을 apt에 맡기면 우리 tryboot 슬롯과 충돌할 수 있다.
- **V** — noble universe에 `rauc` 1.11.3과 `swupdate` 2023.12.1이 있다(arm64 포함).
  - RAUC는 Pi 5 firmware backend가 공식에 없다. PR rauc#1599가 열려 있고, custom backend 참조 구현과 Home Assistant OS의 선례가 있다.
  - RAUC는 X.509/CMS 서명, `verity` 번들, `block-hash-index` adaptive 갱신, casync를 지원한다.
  - Mender는 Pi 5에서 U-Boot와 Debian/Raspberry Pi OS 기준이고, Ubuntu Pi 5 지원이 없다.
  - 출처: https://rauc.readthedocs.io/en/latest/reference.html, https://packages.ubuntu.com/rauc, https://launchpad.net/ubuntu/noble/+package/swupdate, https://docs.mender.io/operating-system-updates-debian-family/convert-a-mender-debian-image
- **A** — RAUC CMS 서명에 Ed25519 인증서를 쓸 수 있다(OpenSSL CMS 경유). 문서에 명시돼 있지 않다.

### Decision

**1. 한 서명 릴리스가 1~3계층을 함께 싣고, 4계층은 같은 키로 서명한 별도 산출물이다.**

- 릴리스 id(`YYYY.MM.DD-NNN`)는 하나다. 매니페스트에 다음 필드를 둔다.
  - `layers`: 이번 릴리스가 바꾸는 계층. `release/artifact_impact.py`의 판정을 쓴다.
  - `image_layer`: D-388 허용 목록 사본.
  - `migrations`: 결정 6.
  - `requires`: 최소 migration 수준, 허용하는 런타임 id 집합, 최소 이미지 세대.
- 로봇은 `requires`를 만족하지 못하는 릴리스를 스테이징 단계에서 **거절하고 이유를 보고**한다. 활성화 도중에 거절하지 않는다.
- 전체 이미지(`rosy-os-pinky-pro-<id>-arm64.img.xz`, D-164)는 같은 `SHA256SUMS`/Ed25519 형식을 유지한다. 4계층이 A/B 번들을 쓰게 되면 번들도 같은 키로 서명한 `SHA256SUMS`가 덮는다.

**2. 카탈로그는 사이트 Fleet에 두고, 운영 PC는 서명하고 발행만 한다.**

- 운영 PC가 서명한 릴리스를 Fleet 카탈로그에 올린다(`POST /api/v1/releases`, operator 이상, 감사 기록).
- Fleet은 **내용을 믿지 않는 전달자**다. 릴리스를 보류하거나 늦출 수는 있어도 위조할 수는 없다. 로봇이 서명을 검증한다.
- 로봇은 사이트 LAN의 Fleet에서만 받는다. 인터넷도 GitHub도 쓰지 않는다.
- P1에서는 Fleet 카탈로그가 아직 없다. 그동안은 운영 PC의 릴리스 폴더를 카탈로그로 삼는다. PC가 밀어 넣고, 로봇은 끌어오지 않는다.

**3. 스테이징과 적용을 나눈다.**

- **스테이징**은 로봇의 자동 작업이다. 확인, 내려받기, 검증, 풀기를 한다.
  - 1계층은 `/opt/rosy/releases/<id>`에 풀고, 2~3계층 파일은 그 안에 그대로 둔다.
  - `current`를 옮기지 않고, 유닛을 재시작하지 않고, `/etc`·`/boot`·`/usr/local`을 쓰지 않는다.
  - 로봇이 쓰는 중이어도 스테이징은 허용한다. 대신 `Nice=19`, `IOSchedulingClass=idle`, 대역 상한을 두고, 로봇이 이동 중이면 멈춘다. 교훈 4가 이유다: 검증과 압축 해제는 CPU를 먹는다.
  - 스테이징이 끝나면 로봇이 `release.staged{id, layers, requires_ok, bytes}` 이벤트를 FleetAgent로 보낸다.
- **적용**은 운영자 승인(결정 5)과 기기 리스(결정 4)가 모두 있어야만 한다. 적용 순서는 다음과 같다.
  1. 리스를 획득한다.
  2. 적격성을 다시 검사한다.
  3. 3계층 migration(userspace)을 적용한다.
  4. 1계층을 활성화한다.
  5. 2계층을 동기화한다(D-388).
  6. 바뀐 유닛을 재시작한다.
  7. 건강 판정을 한다.
  8. boot migration이 있으면 tryboot 재부팅으로 넘어간다.
  9. 커밋하고 리스를 놓는다.
- 어느 단계든 실패하면 **역순으로 되돌린다**(결정 8).

**4. 기기 쪽 정비 리스(`maintenance lease`)가 사람과 에이전트를 서로 막는다.**

- **소유자는 CORE가 아니라 호스트다.** 적용 중에 CORE가 재시작되므로 리스가 CORE보다 오래 살아야 한다. 호스트 에이전트(`host_agent.py` 계약을 네이티브로 옮긴 것) 또는 같은 역할의 root oneshot이 관리한다.
  - 상태는 `/run/rosy/maintenance.lease`(tmpfs)에 둔다. 획득과 해제 기록은 `/var/lib/rosy/maintenance/history.jsonl`에 남긴다.
  - 필드: `holder`(사람·세션·콘솔 id), `purpose`(`update`·`calibration-restart`·`bench`·`card-prep` 등), `acquired_at`, `expires_at`, `heartbeat_at`.
- **획득 규칙.** 다음 가운데 하나라도 참이면 거절한다.
  - 다른 리스가 살아 있다.
  - CORE가 쓰는 중이라고 보고한다: `activity`가 CALIBRATING이다, 모드가 MANUAL·NAVIGATION·DOCKING이다, goal이나 미션이 진행 중이다, teleop 입력이 최근 N초 안에 있었다.
  - 로봇이 이동 중이다.
- **무기한 리스는 없다.** TTL은 기본 15분이고 heartbeat로 연장한다. 끊긴 세션의 리스는 만료된다.
  - 강제 해제는 administrator가 이유를 적어야 하고, 기록이 남는다.
- **리스가 살아 있는 동안.** CORE 스냅샷은 `activity: MAINTENANCE`를 싣는다. 움직임을 시작하는 요청(teleop, mode, goal, line-follow, dock)은 모두 409 `MAINTENANCE_ACTIVE`를 받는다. 비상정지와 정지 경로는 늘 열려 있다. 교정 세션 리스와 같은 모양을 쓰고, 두 리스는 서로 배타다.
- **리스를 반드시 잡아야 하는 도구.**
  - `rosy-release-push.ps1`과 D-388 동기화
  - `rollback-release.sh`
  - 유닛을 재시작하는 모든 스킬과 스크립트: `rosy-hw-bringup`, `rosy-device-access`의 재시작 단계, `rosy-release-push`
  - 콘솔의 Apply
  - 에이전트 세션의 ssh `systemctl restart rosy-*`

  리스 없이 `rosy-*` 유닛을 재시작하는 것은 규칙 위반으로 본다. P3에서는 sudoers 규칙과 호스트 에이전트로 이것을 강제한다(결정 13).
- **리스 전의 잠정 규칙(P1부터, 이미지 변경 없음).**
  - `rosy-release-push.ps1`과 스킬이 ssh로 `/run/rosy/claim.json`(holder, purpose, expires_at)을 먼저 확인하고 만든다. 다른 holder의 유효한 claim이 있으면 멈춘다.
  - CORE `/api/v1/robot/state`를 읽어 이동, 모드, `activity`를 확인하고, 쓰는 중이면 멈춘다.
  - 에이전트 규칙: 로봇 한 대를 만지기 전에 claim을 잡고, 끝나면 지운다. 운영자는 콘솔이나 채팅으로 "rosy-pinky-xxxx를 HH:MM까지 씀"을 알린다.
  - 이 claim은 협조용일 뿐 강제력이 없다. P3의 리스로 대체한다.

**5. 승인 기록과 감사.**

- 운영자는 콘솔에서 (릴리스 id, 대상 로봇 집합, 롤아웃 정책)을 보고 Apply를 누른다. 콘솔은 다음을 함께 보여 준다.
  - 매니페스트 sha256
  - 바뀌는 계층
  - 재부팅 여부
  - 로봇별 적격성
- Fleet은 승인 레코드를 추가 전용 감사 표에 남긴다(D-341 감사 표 재사용). 레코드 필드: `approval_id`, `operator`, `approved_at`, `release_id`, `manifest_sha256`, `targets`, `policy`(배터리 문턱, soak 시간, 실패 시 중단).
- **승인과 서명은 다른 권한이다.** 서명은 내용을 허가하고, 승인은 시점과 대상을 허가한다. 승인은 서명되지 않은 릴리스를 적용하게 할 수 없다. 서명은 승인 없이 적용을 일으키지 않는다.
- 로봇은 적용 이력을 `/var/lib/rosy/updates/history.jsonl`에 남기고 이벤트로 보낸다. 이벤트: `release.apply_started|committed|rolled_back|refused`. 각 이벤트에 `approval_id`와 단계, 이유가 실린다.
- **권한.** 콘솔의 operator 토큰으로는 설치할 수 없다(D-361). Fleet에 로봇별 업데이트 전용 자격을 새로 두고, 등록 흐름으로 발급한다.
  - 이 자격은 `release.stage|apply|rollback|status`와 리스 획득만 한다. 운전 권한도, administrator 전체 권한도 아니다.
  - administrator 토큰을 Fleet에 두는 안은 기각한다.

**6. 3계층은 버전이 붙은 멱등 일회성 migration으로 싣는다.**

- 릴리스의 `deploy/robot/migrations/<NNNN>-<slug>/`에 `migration.json`과 `check`, `apply`, `revert`를 둔다.
  - `migration.json` 필드: `id`, `class`(`userspace`|`boot`), `requires`, `touches` 허용 경로, `reboot`.
  - `check`는 이미 적용됐는지를 부작용 없이 판정한다.
  - `apply`는 여러 번 돌려도 결과가 같아야 한다.
- 기기는 `/var/lib/rosy/migrations/applied.json`에 `{id, sha256, release_id, applied_at, class}`를 적는다.
  - 번호 순서대로만 적용한다.
  - 같은 id인데 sha256이 다르면 거절한다. 이미 적용된 migration의 내용은 바꿀 수 없다.
- **`userspace` 클래스.** apt 핀, 추가 deb, `/usr/local` 파이썬, `/etc` 설정 파일 가운데 허용된 것이다.
  - 적용 전에 바꿀 파일과 설치할 패키지의 이전 버전(.deb 캐시)을 백업한다.
  - `revert`는 백업으로 되돌린다. 거꾸로 돌릴 수 없는 migration은 `revert: none`을 선언한다. 그런 migration은 P2 게이트에서 따로 승인받고, 적용 전에 루트 스냅샷(결정 7의 `boot` 경로)이나 4계층이 있어야 한다.
- **파이썬 런타임.**
  - 새 런타임은 `/usr/local/lib/rosy-python/<runtime-id>/`에 옛 런타임과 나란히 깐다.
  - 활성 런타임 기록(`/usr/local/share/rosy/python-runtime.sha256`)은 1계층 전환과 같은 트랜잭션에서 바꾸고, 롤백 때 되돌린다.
  - 옛 이미지의 `native_release.py`는 기록과 같은지를 비교한다. 그래서 기록을 바꾸는 migration이 활성화보다 먼저 돌아야 한다.
  - 런타임 id의 정의(파일 전체 sha256)는 **바꾸지 않는다**. 바꾸면 이미 구운 로봇의 검증기가 새 payload를 모두 거절한다(교훈 1).
- **커널과 apt 커널 갱신.**
  - `linux-raspi*`, `flash-kernel`, `linux-firmware-raspi`는 apt hold로 묶는다.
  - 커널과 모듈 변경은 `boot` 클래스 migration으로만 한다.
  - 무인 업그레이드(`unattended-upgrades`)가 3계층을 움직이지 않는지 P2에서 기기로 확인한다.

**7. `config.txt`, `cmdline.txt`, 커널 변경은 Pi 5 tryboot를 거친다. 한 FAT 파티션 안에서 `os_prefix`를 쓴다.**

- **P2는 파티션을 바꾸지 않는다.** 방식은 다음과 같다.
  1. `boot` migration은 후보 커널, initramfs, dtb, overlay, `cmdline.txt`를 `/boot/firmware/rosy-try/`에 쓴다.
  2. 후보 설정을 `tryboot.txt`로 쓴다. `os_prefix=rosy-try/`와 새 `config.txt` 내용이 들어간다.
  3. `reboot "0 tryboot"`로 재부팅한다.
  4. 부팅 뒤 커밋 에이전트가 건강 판정(결정 9)을 통과하면, 후보를 기본 자리로 옮기고 `config.txt`를 바꾼 뒤 한 번 더 재부팅해 확인한다. 실패하거나 멈추면 리셋이 플래그를 지우고, 옛 `config.txt`와 커널로 돌아간다.
- 이 방식은 Ubuntu 25.10 `piboot-try`와 같은 모양이다. 나중에 25.10 이상으로 옮기면 Ubuntu 방식으로 갈아타거나 그것을 끈다(위험 R4).
- **첫 번째 boot migration은 watchdog을 켜는 것이다.** `dtparam=watchdog=on`, 쓸 수 있으면 `kernel_watchdog_timeout`, systemd `RuntimeWatchdogSec`, cmdline `panic=10`을 넣는다.
  - 이것 자체도 tryboot로 넣는다. 그 전에는 멈춘 부팅을 자동으로 되돌릴 수 없으므로, 벤치 로봇에서 사람이 지켜보며 적용한다.
- **FAT 파티션 용량.** 커널, initrd, dtb 두 벌이 noble raspi `/boot/firmware`(약 512 MB, **A**)에 들어가는지 P2 첫 벤치에서 잰다.
- **tryboot 실패는 실패로 끝나야 한다.** tryboot에서 실패한 로봇은 옛 설정으로 돌아와 `release.rolled_back{reason: tryboot}`를 보고한다. 그 뒤 같은 migration을 다시 시도하지 않는다.

**8. 모든 계층에 되돌림이 있고, 되돌림도 역순으로 한다.**

| 계층 | 되돌림 | 부팅할 수 없을 때 |
|---|---|---|
| 1 | `native_release.py` `previous`, 부팅 때 `recover()` | 옛 릴리스로 recover |
| 2 | D-388 백업 매니페스트 복원 | 다음 부팅에서 `pending.json`을 이어서 처리 |
| 3 userspace | migration `revert`와 .deb 캐시 | 1·2계층을 되돌린 뒤 revert, 실패하면 RECOVERY HOLD |
| 3 boot | tryboot 플래그가 리셋으로 지워진다(firmware) | watchdog 리셋 → 옛 `config.txt`와 커널 |
| 4 | A/B 슬롯(`autoboot.txt` `tryboot_a_b`) | watchdog 리셋 → 옛 슬롯 |

- 적용이 어느 단계에서 실패하든, 이미 한 단계만 역순으로 되돌린다.
- 되돌림까지 실패하면 `recovery-hold`를 남긴다(`updater.py` 선례). 모드는 CORE 전용(`ROSY_IO_DRIVE_ENABLED=false`, D-291)으로 둔다. 운영자가 `release.clear_hold`로 풀기 전까지는 다음 적용을 받지 않는다.

**9. 건강 판정은 "CORE 준비"보다 넓게 한다.** 커밋 전에 다음을 모두 확인한다.

- CORE 준비(`wait-core-ready.py`)
- `rosy-io` 활성, 모터 드라이브가 꺼진 상태에서 센서와 엔코더 관측
- 실패한 `rosy-*` 유닛 0개
- `/cmd_vel` publisher가 CORE 하나뿐
- 적용 전과 같은 `robot_id`와 등록 자격
- FleetAgent 재연결

판정이 끝나야 리스를 놓는다. 판정 시간 상한은 기본 120 s이며, 넘기면 실패로 본다.

**10. 롤아웃은 한 대씩, 쓰지 않는 로봇부터 한다.**

- **적격성.** Fleet이 계산해 콘솔에 보여 주는 것은 참고용이다. 기기가 리스를 잡을 때 다시 확인한 결과가 권위다. 적격 조건은 다음을 모두 만족하는 것이다.
  - online
  - 이동하지 않음: odom 속도가 문턱 아래로 10 s 이상, 최근 `cmd_vel` 0
  - 모드가 IDLE
  - goal, 대기열, claim, 편대, 교정 세션, teleop이 모두 없음
  - estop이 아님
  - RECOVERY HOLD가 아님
  - 배터리가 문턱 이상이거나 충전 중. 기본 문턱은 40%이고, 재부팅이 있는 적용이면 60%
  - 스테이징 완료
- **순서.**
  1. 도킹 중이거나 충전 중인 유휴 로봇
  2. 그냥 유휴인 로봇
  3. 쓰는 중인 로봇은 적격이 될 때까지 기다린다. 운영자가 "이 로봇은 건너뜀"을 고를 수 있다.
- **진행.**
  - 첫 로봇이 canary다. 커밋 뒤 soak 시간(기본 10분) 동안 다시 `rolled_back`이 나오지 않으면 다음 로봇으로 간다.
  - 한 대라도 되돌림이 나면 롤아웃을 멈추고 운영자에게 알린다.
  - 동시에 적용 중인 로봇은 한 대다.
- `docked` 필드가 스키마에 없다. 처음에는 `battery_status.charging`과 도킹 슬롯 상태로 추정하고, 필드는 P3에서 더한다(열린 질문).

**11. 대역은 파일 단위 내용 주소 delta와 이어받기로 줄인다.**

- 1계층 매니페스트에는 이미 파일마다 sha256이 있다. 로봇은 가지고 있는 어느 릴리스에도 없는 해시의 파일만 받고, 나머지는 로컬 릴리스에서 하드링크하거나 복사한다.
  - 전송은 HTTP `Range`로 이어받는다. 각 파일은 해시로 끝을 확인한다.
  - 서명은 여전히 `SHA256SUMS` 전체를 덮는다.
- 전체 tarball도 계속 받을 수 있다. P1 PC 푸시와 첫 적용, 캐시가 없는 로봇이 이 경로를 쓴다.
- 이진 delta(bsdiff, casync, zchunk)는 측정해서 필요가 드러날 때까지 들이지 않는다. 4계층에서는 RAUC `block-hash-index`나 casync가 그 자리를 맡는다.
- 스테이징 공간은 `storage.check_update_headroom` 규칙을 쓴다. 보관하는 릴리스는 `current`, `previous`, staged 하나까지다.

**12. 2026-10-01 교훈이 설계에 들어가는 자리.**

| 교훈 | 막는 방법 |
|---|---|
| 런타임 id가 주석 바이트까지 해시한다 | `requires.runtime_ids`를 스테이징에서 먼저 검사한다. 불일치는 적용 전 `refused`로 드러나고, 활성화 실패로 나타나지 않는다. 런타임을 바꾸는 일은 결정 6의 나란히 설치와 기록 전환 migration으로만 한다. id 정의와 `test_python_runtime_id.py` 핀은 그대로 둔다 |
| 일괄 경로 치환이 기기 릴리스 경로를 건드렸다 | 기기 경로(`/opt/rosy/releases/<id>/deploy/robot/native/…`, migration 경로, `/boot/firmware/rosy-try/`)는 기기 계약이다. 스키마와 생산자(payload 빌더)에서 경로를 만들고, `test_release_layout_paths.py` 방식의 존재 검사가 지킨다. migration 디렉터리 이름과 허용 경로도 같은 시험에 넣는다 |
| payload 푸시가 이미지 계층을 옛것으로 남긴다 | 2계층 동기화(D-388)를 적용 트랜잭션의 필수 단계로 둔다. 건강 판정에 "이미지 계층 드라이런 결과가 비어 있음"을 넣는다. 드리프트가 남으면 커밋하지 않는다 |
| readback이 CPU를 빼앗긴다 | 네트워크 경로는 카드 기록을 대체한다. 기기 쪽 검증은 스테이징 단계에서 `Nice`와 idle IO로 돌고, 시간 상한이 아니라 진행률로 판정한다. 카드 경로가 남는 경우(결정 14)의 규칙은 D-389 긴급 카드 쓰기 ADR과 해당 교훈을 따른다 |

**13. 안전 불변식.** 모든 단계의 시험이 이것을 고정한다.

1. **이동 중에는 적용하지 않는다.** 리스를 획득할 때와 각 단계 사이에 다시 확인한다. 적용 중에 이동 명령을 받으면 409로 거절한다. 비상정지는 늘 열려 있다.
2. **CORE만이 최종 `cmd_vel` publisher다.** 업데이트 도구, 커밋 에이전트, 호스트 에이전트, migration은 `cmd_vel`을 publish하지 않고 ROS graph에 참여하지 않는다. 적용 뒤 건강 판정이 이것을 확인한다(결정 9).
3. **모든 계층에 되돌림이 있다**(결정 8). 되돌림이 없는 변경은 적용 대상이 아니다.
4. **부팅하지 못하는 로봇은 마지막으로 좋았던 슬롯이나 릴리스로 스스로 돌아온다.** 조건은 watchdog, tryboot 한 번 플래그, `recover()`다. watchdog이 없는 로봇에는 `boot` 클래스를 적용하지 않는다.
5. **적용 뒤 첫 시작은 드라이브를 끈 채로 한다.** `rosy-io` 재시작은 모터를 멈춘다. 적용이 드라이브 승인(D-291 `/etc/rosy/runtime.env`)을 바꾸지 않는다.
6. **긴급 카드 쓰기(`-Emergency`, `fix/card-write-confirm-and-artifact-download`)는 마지막 수단으로 남는다.** 네트워크 경로가 이것을 대신하지 않고, 이것도 네트워크 경로를 대신하지 않는다.

**14. 카드가 여전히 필요한 경우.**

- 첫 설치. 새 로봇이나 새 카드는 서명 이미지와 개인화로 시작한다(D-164, D-154).
- 물리적으로 망가진 카드, 또는 부팅도 되돌림도 안 되는 로봇
- A/B 레이아웃으로 바꾸는 한 번(P4). 로봇마다 한 번이다.
- P4 전의 큰 OS 업그레이드(24.04 → 26.04 등). migration으로 하지 않는다.
- 3계층 migration 가운데 `revert: none`이면서 스냅샷 수단이 없는 것

**15. 4계층(A/B 전체 이미지)을 열어 둔다. P1~P3는 다음을 지킨다.**

- **목표 레이아웃(P4).** GPT 또는 MBR+extended로 다음 파티션을 둔다.
  - `autoboot.txt`만 든 작은 FAT
  - boot A와 boot B(FAT)
  - root A와 root B(ext4)
  - `data`(`/etc/rosy` 신원, `/var/lib/rosy`, 홈)
- **P1~P3가 지킬 제약.**
  - 기기 상태는 선언된 경로 목록(`deploy/robot/state-paths.txt`, 새로 둠) 밖에 새로 두지 않는다. 그래야 P4 변환이 상태를 `data`로 옮길 수 있다.
  - `boot` migration은 boot 파티션 안의 파일로만 표현한다.
  - 커밋 에이전트와 건강 판정(결정 7·9)은 P4의 "mark good"으로 그대로 쓴다.
  - 서명 형식과 카탈로그(결정 1·2)는 번들에도 그대로 쓴다.
- **프레임워크.** 후보 순서는 RAUC(custom tryboot backend, `verity` 번들, adaptive), in-house writer, SWUpdate다. Mender는 기각한다. 최종 선택은 P4 진입 게이트의 스파이크 뒤에 한다. 비교는 Alternatives에 있다.

**16. 단계와 게이트.** 게이트 등급은 HOST(호스트 시험), DEVICE(벤치 로봇), FIELD(현장 운용)다. 앞 단계의 GO는 뒤 단계의 증거가 아니다(D-291 5항).

**P1 — PC가 여러 로봇에 1·2계층을 민다**

- **범위**
  - `rosy-release-push.ps1`이 로봇 목록을 받아 한 대씩 돈다: claim 확인과 획득 → 적격성(CORE 상태 읽기) → 푸시 → 활성화 → D-388 동기화 → 건강 판정 → claim 해제.
  - 로봇 하나라도 실패하면 멈춘다.
  - 결정 4의 잠정 claim 규칙을 모든 스킬에 넣는다.
- **증거와 게이트**
  - HOST: 순서와 중단을 가짜 ssh로 시험하고, claim 충돌 시 멈추는지, 이동 중이면 거절하는지 시험한다.
  - DEVICE: 벤치 두 대에 연속 적용하고 롤백한다. 한 대를 이동시킨 채 두어 거절되는지 본다.
  - FIELD: 해당 없음.
- **선행 조건:** D-388 실기(2026-10-02)와 D-225 `UPDATE_GO`.
- **수동으로 남는 것:** 서명, 릴리스 선택, 푸시 시작, 3·4계층.
- **열린 질문:** claim 파일 위치와 에이전트 세션 식별자 규약.

**P2 — 3계층 migration과 tryboot**

- **범위**
  - migration 형식, `applied.json`, userspace revert, 런타임 나란히 설치, 커널 hold.
  - watchdog migration, 그다음 `os_prefix` tryboot 커밋 에이전트.
- **증거와 게이트**
  - HOST: migration 멱등, 순서, 해시 불변, revert, 가짜 `/boot/firmware` 트리에서 tryboot 파일 생성.
  - DEVICE, 각 항목에 전원 차단 1회 포함: 벤치 한 대에서 (a) watchdog migration, (b) 일부러 부팅하지 못하게 한 `config.txt`가 tryboot 뒤 되돌아옴, (c) 커널 교체와 되돌림, (d) 런타임 전환과 되돌림.
  - FIELD: 현장 로봇 한 대에서 운영자가 지켜보며 한다.
- **열린 질문**
  - noble의 `flash-kernel` 동작과 hold의 부작용
  - FAT 용량
  - `kernel_watchdog_timeout` 의미
  - `unattended-upgrades` 상태
  - 되돌릴 수 없는 apt 변경을 어떻게 다룰지
- **수동으로 남는 것:** 적용 시작(PC)과 첫 watchdog 적용 감시.

**P3 — 기기 스테이징, 콘솔 승인, 정비 리스**

- **범위**
  - Fleet 카탈로그와 업로드.
  - 로봇 쪽 스테이징 타이머. 새로 만들고, 레거시 `rosy-update-check`는 되살리지 않는다.
  - 호스트 쪽 정비 리스와 CORE `activity: MAINTENANCE`/409.
  - 업데이트 전용 자격.
  - 콘솔 Apply, 롤아웃 오케스트레이터(결정 10), 승인 감사, 파일 단위 delta와 이어받기.
  - sudoers를 좁혀 리스 없는 `rosy-*` 재시작을 막는다.
- **증거와 게이트**
  - HOST: 적격성 술어, 리스 배타(교정, teleop), 만료, 강제 해제 감사, 승인 없는 적용 거절, 서명 없는 카탈로그 거절, 이어받기.
  - DEVICE: 세 대로 롤아웃한다. 한 대는 teleop 중, 한 대는 도킹, 한 대에는 일부러 실패를 넣어 canary 중단을 확인한다.
  - FIELD: 현장 롤아웃 1회를 운영자가 승인한다.
- **열린 질문**
  - 리스 소유 프로세스: 네이티브 호스트 에이전트를 부활시킬지, 새 oneshot을 둘지
  - `docked` 필드
  - 배터리 문턱
  - soak 시간
  - 업데이트 자격의 발급과 회수
- **수동으로 남는 것:** 서명(오프라인 키), Apply 승인, RECOVERY HOLD 해제.

**P4 — A/B 전체 이미지**

- **범위**
  - A/B 레이아웃 이미지.
  - 프레임워크 스파이크(RAUC custom backend 대 in-house).
  - 번들 서명 연결.
  - 로봇마다 카드 한 번 변환.
  - OS 메이저 업그레이드를 번들로 한다.
- **증거와 게이트**
  - HOST: 번들 서명과 검증, 슬롯 선택 로직.
  - DEVICE: 설치 → tryboot → 커밋, 멈춤 → watchdog → 옛 슬롯, 설치 중 전원 차단, `data` 보존.
  - FIELD: 한 대씩 변환한다.
- **열린 질문**
  - 카드 최소 용량: root 두 벌과 data
  - GPT와 MBR 가운데 무엇을 쓸지
  - Ed25519와 CMS를 어떻게 잇거나 감쌀지
  - adaptive 갱신의 실제 절감량
- **수동으로 남는 것:** 변환 카드 기록과 첫 설치.

### 사용자 결정 필요

각 항목의 권장 기본값은 사용자가 달리 정하지 않으면 해당 단계 계획서가 따르는 값이다.

1. **Fleet 업데이트 전용 자격(결정 5, P3).**
   - 권장: 새 자격 유형을 둔다. D-361 등록 흐름으로 로봇마다 하나를 발급하고, 권한은 `release.stage|apply|rollback|status`와 정비 리스 획득만 준다. 운전 권한과 administrator 전체 권한은 주지 않는다.
   - 기각한 안: Fleet에 administrator 토큰을 보관하는 것.
2. **배터리 문턱과 canary 대기(결정 10).**
   - 권장: 배터리 40% 이상이거나 충전 중이어야 한다. 재부팅이 있는 적용은 60% 이상이어야 한다.
   - 권장: 첫 로봇이 커밋한 뒤 10분 동안 되돌림이 없어야 다음 로봇으로 간다. 운영자는 대기를 줄일 수 있지만 0으로 건너뛸 수는 없다.
3. **정비 리스 소유 프로세스(결정 4, P3).**
   - 권장: `host_agent.py` 계약(허용 목록, confirm, 감사)을 네이티브 이미지용 root 서비스로 옮겨 리스를 소유하게 한다. CORE는 이 리스를 읽어 `activity: MAINTENANCE`와 409만 낸다.
   - 대안: 적용 때만 도는 새 root oneshot. 이 경우 수명과 heartbeat를 따로 설계해야 한다.
4. **A/B 카드 크기와 파티션 표(결정 15, P4).**
   - 권장: 카드는 32 GB 이상, 파티션 표는 GPT다. 지금 이미지의 raw 크기가 약 8.6 GB라서, root 슬롯 두 개(각 약 10 GB)와 boot 두 개, data가 들어간다. MBR 4개 주 파티션 한계를 extended로 피하지 않아도 된다.
   - P4 스파이크에서 Pi 5 부트로더의 GPT 부팅을 실측으로 확인한 뒤 확정한다.
5. **Ubuntu 24.04 tryboot 기기 확인(Context 4, 결정 7, P2 첫 게이트).**
   - 권장: P2 착수 전에 벤치 로봇 한 대에서 읽기 전용으로 확인한다. 확인할 것:
     - `apt policy flash-kernel`로 noble에 `piboot-try`가 없는지
     - 커널 갱신 때 `flash-kernel`이 `/boot/firmware`에 무엇을 쓰는지
     - `/boot/firmware` 여유 용량
     - `vcgencmd bootloader_version`(EEPROM이 tryboot와 `boot_partition` 조건을 지원하는지)
     - `unattended-upgrades` 상태
   - 결과가 가정과 다르면 결정 7을 고친 뒤에 P2를 연다.

### Alternatives

- **완전 자동 적용(승인 없음).** 사용자가 고른 방식이 아니다. 또 쓰는 중인 로봇의 판정은 오판할 수 있어, 사람이 마지막으로 시점을 보는 편이 싸다. 기각.
- **로봇이 GitHub나 인터넷에서 직접 받는다.** 현장에 인터넷이 없을 수 있고, D-197/D-198이 GitHub polling을 퇴역시켰다. 카탈로그가 사이트 밖에 있으면 승인 감사가 둘로 갈린다. 기각.
- **운영 PC를 영구 카탈로그로 둔다.** PC는 항상 켜 있지 않고, 한 세션에 묶인다. 사고가 났던 여러 세션의 동시 접근이 바로 이 구조에서 생겼다. P1 동안만 쓴다.
- **정비 리스를 CORE 안에만 둔다.** 적용이 CORE를 재시작하므로 적용 중에 리스가 사라진다. 교정 리스와 같은 모양(API, 409)은 쓰되, 소유는 호스트에 둔다.
- **`native-release.lock`을 늘려 리스로 쓴다.** flock은 프로세스가 사는 동안만 유지되고, 소유자, 목적, 만료가 없다. ssh 재시작과 사람도 막지 못한다. 기각.
- **Docker 시대의 `updater.py`/`delivery.py`를 되살린다.** 런타임 포트가 Docker 이미지 적재를 전제한다. `os_suite`는 bookworm과 trixie만 받는다. 활성 기록이 `activation.json`이라 네이티브 링크 모델과 다르다. 대신 호스트 에이전트의 허용 목록과 confirm, 감사, 리스 거절 설계와 `recovery-hold` 개념은 가져온다. 코드는 되살리지 않는다.
- **3계층을 이미지 재기록으로만 한다(현 상태).** 카드마다 15~18분이 걸리고 사람이 로봇에 가야 한다. 교훈 4의 CPU 경쟁도 그대로다. P4 전까지는 migration이 더 싸다. 기각.
- **3계층을 apt 저장소와 `apt upgrade`로 한다.** 버전을 고정하기 어렵고, 되돌림이 불완전하다. 부팅 파일은 `flash-kernel`이 건드린다. 기각. 필요한 deb는 migration이 고정 버전으로 싣는다.
- **config.txt를 제자리에서 고치고 재부팅한다.** 틀리면 부팅하지 못하고 카드로만 되살릴 수 있다. tryboot가 이것을 막는다. 기각.
- **파일 시스템 스냅샷(btrfs/LVM)으로 3계층을 되돌린다.** 이미지를 ext4에서 바꿔야 한다. 그러려면 카드 재기록이 필요하고, 그 비용이면 P4 A/B로 가는 편이 낫다. 기각.
- **4계층 프레임워크 비교**
  - **RAUC:** noble universe에 있다. Pi 5 tryboot custom backend 선례(HAOS)가 있고, `verity`, adaptive, casync를 지원한다. 비용은 X.509/CMS 신뢰 사슬을 하나 더 두는 것과 backend 유지다. 1순위다.
  - **SWUpdate:** noble에 있고 delta 핸들러가 많다. 부트로더 인터페이스가 U-Boot/GRUB env 중심이고, Pi 5 tryboot 선례를 찾지 못했다. 2순위다.
  - **Mender:** Pi 5에서 U-Boot가 필요하고 Debian/Raspberry Pi OS 기준이다. 이진 delta는 상용이다. 기각.
  - **in-house writer:** 비활성 슬롯에 `dd`, 해시 검증, tryboot, 커밋 에이전트로 이룬다. Ed25519 신뢰를 그대로 쓰고 의존성이 없다. 대신 adaptive 갱신, 번들 형식, 전원 차단 처리를 우리가 떠안는다. RAUC 스파이크가 실패하면 쓰는 대안이다.
- **Ubuntu Core 또는 OSTree로 옮긴다.** 플랫폼이 바뀐다. D-225의 기각 사유가 그대로 유효하다. 기각.

### Consequences

- 기존 로봇의 모든 계층이 카드 없이 갱신된다. 예외는 결정 14뿐이다. 사람이 로봇 옆에 있어야 하는 일은 첫 설치, 망가진 카드, P4 변환으로 줄어든다.
- 적용은 느려진다. 리스, 적격성, soak, 한 대씩 진행 때문이다. 급한 수정도 승인과 canary를 거친다. 운영자가 soak를 0으로 줄일 수는 있어도 건너뛸 수는 없다.
- 호스트에 새 권한 표면이 생긴다: 리스, 스테이징, 업데이트 자격. D-22(CORE는 호스트 관리자가 아님)에 따라 CORE 밖에 둔다. 표면은 허용 목록 명령으로 제한한다.
- Fleet에 새 자격 유형과 카탈로그 저장소가 생긴다. Fleet이 뚫려도 서명 때문에 내용은 위조할 수 없다. 대신 **악의적인 시점 선택과 보류는 가능하다.** 리스와 적격성 검사는 기기가 권위를 갖는 것으로 막는다.
- 에이전트 세션의 로봇 조작 방식이 바뀐다. P1부터 claim을 잡지 않은 재시작은 규칙 위반이다. P3부터는 sudoers가 막는다.

### Risks

- **R1.** watchdog이 켜지기 전의 `boot` 적용은 멈추면 카드로만 복구된다. 첫 watchdog migration은 벤치에서 사람이 지켜보며 한다. 그 전에는 `boot` 클래스 적용을 금지한다.
- **R2.** `revert`가 불완전한 userspace migration이 로봇을 반쯤 바뀐 상태로 둘 수 있다. `check`와 `revert`를 짝으로 시험하고, 부작용 경로는 `touches` 허용 목록으로 제한한다.
- **R3.** 적격성 오판. 예를 들어 이동 판정이 odom 정지를 놓칠 수 있다. 기기에서 여러 신호를 겹쳐 판정하고, 적용 중 이동 명령 409와 `rosy-io` 드라이브 끔으로 이중으로 막는다.
- **R4.** Ubuntu 25.10+ `piboot-try` 또는 noble `flash-kernel`과 우리 tryboot가 충돌할 수 있다. 커널 패키지 hold로 막는다. OS 메이저 업그레이드는 P4 번들로만 한다.
- **R5.** 오프라인 서명 키가 병목이다. 급한 수정도 서명 PC가 있어야 한다. 이것은 의도한 비용이다. 키 교체는 옛 키로 서명한 신뢰 저장소 migration으로 한다.
- **R6.** 리스의 TTL과 heartbeat가 끊겨 적용 도중에 리스가 만료될 수 있다. 적용 중에는 기기 쪽 적용 프로세스가 heartbeat를 소유한다. PC나 콘솔 연결이 끊겨도 적용은 끝까지 가거나 되돌린다.
- **R7.** 레거시 `rosy-update-check`와 Docker 경로를 헷갈릴 수 있다. P3에서 새 스테이징 유닛 이름을 따로 두고, 레거시 파일은 퇴역 표시한다(별도 변경).

### Validation

이 ADR은 문서만이라 여기서 시험하지 않는다. 각 단계 게이트(결정 16)가 실행 계획의 수용 기준이 된다. 각 단계 계획서(`docs/plans/`)는 다음을 적는다.
- 위 HOST 시험의 파일 이름
- 새 방어마다 "깨뜨려 빨강, 되돌려 초록" 증명
- DEVICE와 FIELD 기록 위치(`deploy/logs.md`)

### References

- 결정: D-22(호스트 권한 분리), D-145/D-146(오프라인 서명), D-154(개인화), D-161(네이티브 런타임), D-164(서명 이미지), D-174, D-180/D-187/D-188(카드 쓰기와 readback), D-189(런타임 id), D-197/D-198(Docker updater 퇴역), D-225, D-291, D-341(감사 표), D-361(등록과 토큰), D-382, D-388(이미지 계층 동기화, `feat/release-image-layer-sync`), D-389(긴급 카드 쓰기, `fix/card-write-confirm-and-artifact-download`)
- 코드: `deploy/robot/pinky_pro/native/native_release.py`, `native/activate-release.sh`, `native/rosy-core.service`, `native/wait-core-ready.py`, `rosy-release-push.ps1`, `release/{updater,delivery,host_agent,host_agent_server,cli,github_release,artifact_impact,storage,signing}.py`, `rosy-update-check.{service,timer}`, `install-update-tools.sh`, `src/site/fleet/fleet/server/{app,roster,dispatch_admission,enrollment,enrollment_store,discovery}.py`, `docs/reference/rosy-host-agent-contract.md`
- 교훈: `docs/solutions/workflow-issues/payload-runtime-id-hashes-comments-too-2026-10-01.md`, `blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md`, `payload-push-leaves-the-image-layer-stale-2026-10-01.md`, `card-readback-slows-under-parallel-cpu-load-2026-09-25.md`(2026-10-01 재발 절)
- 브랜치: `feat/release-image-layer-sync`, `fix/card-write-confirm-and-artifact-download`, `feat/calibration-session-mode`
- 외부 출처: Context 4항의 URL
