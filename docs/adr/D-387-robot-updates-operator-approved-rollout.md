## D-387 로봇은 카드 이미지까지 모든 계층을 저장소 릴리스에서 네트워크로 받고, 운영자가 승인하면 한 대씩 자동으로 펼친다 — 쓰는 중인 로봇은 건드리지 않는다

**Status:** Accepted (2026-10-01).
- 사용자가 운용 방식 "승인 후 자동"을 골랐고, "사용자 결정"의 다섯 기본값을 쓴 그대로 승인했다(2026-10-01).
- **2026-10-01 개정 참조:** [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md)이 결정 2(카탈로그)·결정 5(운영자 승인)와 Alternatives의 "완전 자동 기각"·"GitHub에서 직접 받기 기각"을 개정한다. 사용자가 같은 날 완전 자동(유휴 시)·GitHub Releases·로봇별 hold를 골랐다.
- 독립 리뷰 판정은 ACCEPT WITH EDITS였고, 이 판에 그 수정을 모두 반영했다(2026-10-01).
- 결정은 이 문서의 설계를 받아들인다는 뜻이다. 구현 GO, DEVICE·FIELD 승격, 로봇 조작이 아니다. 각 단계는 결정 16의 게이트를 따로 통과해야 한다.

**관계**
- [D-225](D-225-update-without-reflash-and-faster-card-writes.md)의 세 계층 모델을 네 계층으로 넓힌다. D-225가 "보류"로 둔 Pi 펌웨어 A/B와 기각한 RAUC 계열은 **4계층(전체 이미지)에서만** 다시 연다.
- D-388 이미지 계층 동기화(`feat/release-image-layer-sync`, 미병합, 실기 2026-10-02)를 2계층의 전제로 둔다.

**번호:** 2026-10-01에 D-385가 세 브랜치에서 충돌해 다시 매겼다.
- main의 D-385는 `feat/expressive-rosy`다.
- D-386은 `omx-sim-phases`다.
- 이미지 계층 동기화는 D-388(`feat/release-image-layer-sync`)이다.
- 긴급 카드 쓰기는 D-389(`fix/card-write-confirm-and-artifact-download`)다.
- 이 ADR은 D-387이다.

### Context

**1. 계층과 지금 상태**

사용자가 합의한 계층 모델이다. 코드 사실은 main `ab8f08ee`와 `532b9813` 기준이다.

| 계층 | 내용 | 지금의 갱신 경로 | 되돌림 |
|---|---|---|---|
| 1 앱 payload | `/opt/rosy/releases/<id>`(`install/`, 릴리스 사본 `deploy/robot/native/`) | PC의 `rosy-release-push.ps1`이 ssh/scp로 보낸다. `rosy-release-unpack.sh`로 풀고, `activate-release.sh` → `native/native_release.py activate`를 부른다 | `current`/`previous` 링크와 journal을 쓴다. `rosy-runtime.target` 시작이 실패하면 자동으로 되돌린다. 이 실패는 `rosy-core.service`의 `ExecStartPost=wait-core-ready.py`가 45 s 안에 준비되지 못할 때 생긴다. 부팅 때는 `recover()`가 복구한다 |
| 2 이미지 계층 | 유닛, `/opt/rosy/native-runtime`, udev, modprobe | 지금은 손으로 깐다(`rosy-release-push` 스킬 6단계). D-388은 릴리스 안의 `sync-image-layer.py`를 PC가 부르게 한다 | D-388의 백업 매니페스트, 롤백 때 복원, `pending.json` |
| 3 기반 시스템 | apt 집합과 핀, `/usr/local` 파이썬, `config.txt`/`cmdline.txt`, 커널과 모듈 | 카드를 다시 굽는 것뿐이다 | 없다 |
| 4 전체 이미지 | 파티션, 루트 파일시스템 전체 | 카드를 다시 굽는다(D-164, D-291, D-180/D-187 readback) | 옛 카드 |

**자리를 잡지 못한 두 번째 경로.** Docker 시대의 `release/updater.py`, `delivery.py`, `host_agent.py`, `host_agent_server.py`와 `rosy-release` CLI가 있다.
- 이 경로에 있는 것: 스테이징, 세대 스냅샷, `recovery-hold.json`, administrator와 `confirmed=true`를 요구하는 호스트 에이전트 허용 목록(`release.install|rollback|clear_hold`), 감사 로그.
- 네이티브 이미지는 이 경로를 깔지 않는다.
  - `rosy-update-check.service`/`.timer`는 `install-update-tools.sh`만 깐다. `customize-rootfs.sh`의 enable 목록에 없다.
  - `cli.py`는 `os_suite`로 bookworm과 trixie만 받는다.
- GitHub polling(`cli.py check --download`)은 D-197/D-198이 퇴역시켰다. 내려받기는 `.part`에 받고 크기와 sha256을 검사하지만, 이어받기와 delta는 없다.

**신뢰와 서명 검사 시점**
- Ed25519 서명이 `SHA256SUMS`의 바이트 그대로를 덮는다(`release/signing.py`). 로봇은 `/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem`으로 검증한다. 개인 키는 오프라인 운영 PC에 있다(D-145/D-146).
- `rosy-release-unpack.sh`(6~7행 주석)는 tar 멤버 형식만 거르고 서명을 검증하지 않는다. 기기에서 서명을 처음 검사하는 곳은 `native_release.py activate`의 `verify()`다.
- 이미지의 `native_release.py`에는 `verify --release-id` CLI가 따로 있다.

**런타임 id**
- 릴리스의 `python-runtime.sha256`이 이미지의 `/usr/local/share/rosy/python-runtime.sha256`과 같아야 한다(D-189). 이 값은 `device-python-requirements.txt` 파일 전체의 sha256이다.
- `check_python_runtime`(`native_release.py:254`)는 `activate`(:306)와 `rollback`(:341)이 부른다. `recover`(:365)는 의도적으로 부르지 않는다.

**잠금과 `/run`**
- `native_release.py`는 `native-release.lock`에 flock을 걸고, 잡혀 있으면 `NATIVE_RELEASE_BUSY`로 거절한다. 로봇이 움직이는지, 미션이나 teleop 중인지는 **아무도 보지 않는다**.
- `/run/rosy`는 `rosy-core.service`가 소유한다(`RuntimeDirectory=rosy`, `RuntimeDirectoryPreserve=restart`, 56·60행). CORE가 멈추면 지워진다. `rosy-boot-status.service` 15행은 이곳에 쓰지 말라고 적는다.
- 운영자 계정은 암호 없이 모든 명령을 sudo로 실행할 수 있다(`image/first-boot/rosy-first-boot.py:418`의 sudoers 규칙). ssh 세션은 무엇이든 재시작할 수 있다.

**`rosy-io`의 드라이브 설정.** `rosy-io.service`는 `Environment=ROSY_IO_DRIVE_ENABLED=false`(17행) 뒤에 `EnvironmentFile=/etc/rosy/runtime.env`(18행)를 둔다. 그래서 장치별 드라이브 승인이 기본값을 이긴다. `ExecStartPre`(39·42행)는 모드와 드라이브 플래그의 조합을 검사한다.

**Fleet(`src/site/fleet`)**
- 릴리스 카탈로그와 업데이트 엔드포인트가 없다. 릴리스 정보는 발견 단계의 `release` 문자열뿐이다.
- 유휴 판정은 디스패치용 술어다(`server/app.py`): online, 대기 작업 없음, goal 없음, `navigation`이 IDLE/ARRIVED/CANCELED/FAILED 가운데 하나, `mode`가 IDLE 또는 NAVIGATION, 능력 저하 없음, estop 거짓.
- `roster.removal_blockers`와 `fleet_action_claims`(`lease_until`)가 있다.

**CORE 상태로 이동과 도킹을 알 수 있다.** 코드에서 확인했다.
- `GET /api/v1/robot/state`(viewer, `src/runtime/api_web/core_api_web/api/v1/robot.py:17-19`)는 `StateSnapshot`(`src/contracts/foundation/core_common/protocol/schemas.py:984-1010`)을 돌려준다. 담긴 필드는 다음과 같다.
  - `velocity.linear`/`angular`: odom에서 채운다(`src/runtime/gateway/core/bridge/ros_bridge.py:219`).
  - `evidence["velocity"]`: 신선도. 0.5 s가 지나면 stale이다(`core_common/protocol/evidence.py:21`).
  - `mode`, `navigation`, `line_follow`, `safety`, `battery`, `battery_status`
  - `docking.state`: UNDOCKED/DOCKING/DOCKED/CHARGING/UNDOCKING/DOCK_FAILED(`schemas.py:807-831`).
- teleop 리스와 미션 진행 잠금은 CORE에 없다. teleop은 `mode: MANUAL`로만 보인다.
- 교정 세션(`activity: CALIBRATING`)은 `feat/calibration-session-mode`(a527920a)에만 있고 main에는 없다.

**등록과 토큰(D-361).**
- Fleet은 로봇별 operator 토큰을 AES-GCM으로 봉인해 보관하고, administrator 코드는 받지 않는다.
- CORE의 `POST /api/v1/host/release/install|rollback`은 admin 권한이 필요하다. 그래서 **지금 콘솔은 설치를 부를 수 없다**.

**2. 2026-10-01 사고.** 에이전트 세션 셋이 조율 없이 같은 로봇에 푸시하거나 재시작했다. 그 가운데 하나가 교정 주행을 끊었다. 막을 장치가 없었다.
- `native-release.lock`은 전환하는 몇 초 동안만 잡힌다.
- ssh 재시작과 D-388의 유닛 재시작은 그 잠금을 아예 거치지 않는다.

**3. 2026-10-01 교훈 네 건.** 설계가 각각을 어떻게 막는지는 결정 12에 적는다.
- `payload-runtime-id-hashes-comments-too`: 주석을 고친 것만으로 모든 로봇이 payload를 받지 못하게 됐다.
- `blanket-path-rewrite-hits-on-device-release-paths`: 일괄 경로 치환이 기기의 릴리스 경로까지 바꿨다.
- `payload-push-leaves-the-image-layer-stale`: payload 푸시 뒤에도 유닛과 udev가 옛것으로 남았다.
- `card-readback-slows-under-parallel-cpu-load`: 2026-10-01 재발 때 readback이 CPU를 빼앗겨 0.2~4 MB/s로 떨어졌다.

**4. 외부 사실.** 아래 항목은 모두 **가정(A)**이다.
- 출처 URL은 2026-10-01 조사 에이전트가 가져왔다. 이 문서를 쓰면서 원문을 다시 확인하지 않았고, 기기에서 확인한 것도 없다.
- P2 첫 게이트(사용자 결정 5)가 기기에서 확인한다. 결과가 다르면 결정 7을 먼저 고친다.

- **A — tryboot 동작.**
  - `reboot "0 tryboot"`은 한 번만 켜지는 tryboot 플래그를 세운다. firmware는 `[tryboot]` 조건 절을 적용한다.
  - `tryboot_a_b=1`이 없으면 `config.txt` 대신 `tryboot.txt`를 읽는다. 있으면 `autoboot.txt`의 `[tryboot]` `boot_partition`으로 파티션을 바꾼다.
  - 다음 리셋(전원을 껐다 켜는 것 포함)에서 플래그가 지워진다.
  - 출처: https://www.raspberrypi.com/documentation/computers/config_txt.html#autoboot-txt
- **A — 부팅 시도 수.** firmware는 부팅 시도를 세지 않는다. 멈춘 부팅을 되돌리려면 리셋이 필요하다. 관련 설정은 `dtparam=watchdog=on`, `kernel_watchdog_timeout`, `kernel_watchdog_partition`이다.
  - 출처: 위 문서, https://bootlin.com/blog/safe-updates-using-rauc-on-raspberry-pi-5/
- **A — 사용자 공간 멈춤.** 사용자 공간이 멈췄을 때 리셋되려면 systemd `RuntimeWatchdogSec`와 cmdline `panic=N`이 함께 있어야 한다. 1차 출처를 찾지 못했다.
- **A — `os_prefix`.** `os_prefix`는 커널, initramfs, dtb, overlay와 `cmdline.txt`를 접두 디렉터리에서 읽게 한다.
- **A — Ubuntu 25.10 이후.** Ubuntu의 `piboot-try` A/B는 25.10부터다(`flash-kernel-piboot`, `current/`·`new/`·`old/`, `os_prefix`, `[tryboot]`). 24.04 noble에는 백포트되지 않았다.
  - 출처: https://ubuntu.com/hardware/docs/boards/explanations/piboot-ab/, https://launchpad.net/ubuntu/+source/flash-kernel/+changelog
- **A — noble의 커널 갱신.** noble의 `flash-kernel`은 커널 패키지를 갱신할 때 `/boot/firmware`에 커널과 initrd를 복사한다.
- **A — 4계층 후보 패키지.** noble universe에 `rauc` 1.11.3과 `swupdate` 2023.12.1이 있다(arm64 포함).
  - RAUC의 Pi 5 firmware backend는 공식에 없다(PR rauc#1599). custom backend 참조 구현과 Home Assistant OS 선례가 있다.
  - RAUC는 X.509/CMS 서명, `verity` 번들, `block-hash-index`, casync를 지원한다.
  - Mender는 Pi 5에서 U-Boot와 Debian/Raspberry Pi OS 기준이다.
  - 출처: https://rauc.readthedocs.io/en/latest/reference.html, https://packages.ubuntu.com/rauc, https://launchpad.net/ubuntu/noble/+package/swupdate, https://docs.mender.io/operating-system-updates-debian-family/convert-a-mender-debian-image
- **A — Ed25519 인증서.** RAUC CMS 서명에 Ed25519 인증서를 쓸 수 있다.

### Decision

**1. 한 서명 릴리스가 1~3계층을 싣고, 4계층은 같은 키로 서명한 별도 산출물이다.**

- 릴리스 id(`YYYY.MM.DD-NNN`)는 하나다. 매니페스트에 다음 필드를 둔다.
  - `layers`: 이번 릴리스가 바꾸는 계층. `release/artifact_impact.py`의 판정을 쓴다.
  - `image_layer`: D-388 허용 목록 사본.
  - `migrations`: 결정 6.
  - `requires`: 최소 migration 수준, 필요한 런타임 id, 최소 이미지 세대.
  - `boot_change`: 참이면 결정 7의 단독 릴리스다.
- 로봇은 `requires`를 만족하지 못하는 릴리스를 스테이징 단계에서 **거절하고 이유를 보고**한다. 활성화 도중에 거절하지 않는다.
- 전체 이미지(`rosy-os-pinky-pro-<id>-arm64.img.xz`, D-164)는 같은 `SHA256SUMS`/Ed25519 형식을 유지한다. A/B 번들도 같은 키로 서명한 `SHA256SUMS`가 덮는다.

**2. 카탈로그는 사이트 Fleet에 두고, 운영 PC는 서명하고 발행만 한다.**

- 운영 PC가 서명한 릴리스를 Fleet 카탈로그에 올린다(`POST /api/v1/releases`, operator 이상, 감사 기록).
- Fleet은 **내용을 믿지 않는 전달자**다. 보류하거나 늦출 수는 있어도 위조할 수는 없다. 로봇이 서명을 검증한다(결정 3).
- 로봇은 사이트 LAN의 Fleet에서만 받는다. 인터넷도 GitHub도 쓰지 않는다.
- P1에서는 운영 PC의 릴리스 폴더를 카탈로그로 삼는다. PC가 밀어 넣는다.

**3. 스테이징과 적용을 나누고, 적용은 로봇 위의 한 트랜잭션이다.**

**스테이징**은 로봇의 자동 작업이다. 확인, 내려받기, 풀기, 검증을 한다.
- 1계층은 `/opt/rosy/releases/<id>`에 풀고, 2~3계층 파일은 그 안에 그대로 둔다.
- `current`를 옮기지 않는다. 유닛을 재시작하지 않는다. `/etc`, `/boot`, `/usr/local`을 쓰지 않는다. 릴리스 안의 코드를 실행하지 않는다.
- 로봇이 쓰는 중이어도 스테이징은 허용한다. 대신 `Nice=19`, `IOSchedulingClass=idle`, 대역 상한을 두고, 로봇이 이동 중이면 멈춘다.
- 스테이징이 끝나면 `release.staged{id, layers, requires_ok, bytes}` 이벤트를 보낸다.

**서명 검사는 릴리스 코드가 실행되기 직전에 한다.**
- 릴리스 안의 코드(적용 러너, migration, `sync-image-layer.py`)가 root로 돌기 **바로 앞에서**, 이미 설치된 검증기가 검사한다: `/usr/bin/python3 -B /opt/rosy/native-runtime/native_release.py verify --release-id <id>`. 신뢰 키는 `/etc/rosy/trusted-release-keys/`에 있다.
  - 이 검증기는 이미지의 사본이거나, 이전에 검증된 릴리스에서 D-388이 동기화한 사본이다.
- 검증이 실패하면 아무것도 실행하지 않는다.
- 검증과 실행 사이에 릴리스 트리는 root만 쓸 수 있다.
- unpack 단계의 검사(`rosy-release-unpack.sh`)는 형식 검사로 남기고, 신뢰 검사로 세지 않는다.

**적용 트랜잭션.** 운영자 승인(결정 5)과 기기 리스(결정 4)가 모두 있어야만 한다.
- 로봇 위에서 `systemd-run --unit=rosy-apply-<id>`로 도는 러너 하나가 모든 단계를 한다.
  - 러너는 릴리스 안의 `deploy/robot/native/rosy-apply.py`다. 위 검증을 통과한 뒤에만 실행된다.
- 러너는 단계마다 `/var/lib/rosy/updates/apply-journal.json`에 journal을 먼저 쓴다. 필드는 단계, 이전 값, `boot_id`다.
- PC와 콘솔은 러너를 시작하고 `systemctl show`와 journal로 지켜보기만 한다. 연결이 끊겨도 러너는 끝까지 가거나 되돌린다.
- 러너가 죽거나 전원이 끊기면, 다음 부팅의 `rosy-update-resume.service`가 journal을 읽고 마지막으로 좋았던 상태로 되돌린다. 이 서비스는 `rosy-release-recover.service` 다음, `rosy-core.service` 앞에서 돈다(결정 8).

**단계(1~3계층, 재부팅 없음)**
1. 리스를 확인하고 러너로 옮긴다. 결정 4의 획득 규칙을 다시 적용한다.
2. 적격성을 다시 검사한다(결정 10).
3. 3계층 userspace migration을 적용한다. 새 런타임은 나란히 설치만 한다.
4. 런타임 기록을 바꾼다(결정 6). 이전 값은 journal에 둔다.
5. 1계층을 활성화한다(`native_release.py activate`, 드라이브 끔 override 아래에서, 결정 13.5).
6. 2계층을 동기화한다(D-388). 바뀐 유닛을 재시작한다.
7. 건강 판정을 한다(결정 9).
8. 커밋한다. 드라이브 끔 override를 치우고 `rosy-io`를 정해진 방식으로 재시작한다(결정 13.5). journal을 닫고 리스를 놓는다.

- 어느 단계든 실패하면 **이미 한 단계만 역순으로** 되돌린다(결정 8).
- `boot` 변경은 이 트랜잭션에 섞지 않는다(결정 7).

**4. 기기 쪽 정비 리스(`maintenance lease`)가 사람과 에이전트를 서로 막는다.**

**소유는 호스트다.** 적용 중에 CORE가 재시작되므로 리스는 CORE보다 오래 살아야 한다.
- 사용자 결정 3에 따라, `host_agent.py` 계약을 네이티브 root 서비스(`rosy-host-agent.service`)로 옮겨 소유하게 한다.
- **휘발 상태**는 이 서비스가 소유하는 `/run/rosy-maintenance/lease.json`에 둔다(`RuntimeDirectory=rosy-maintenance`, `RuntimeDirectoryPreserve=yes`). `/run/rosy`는 CORE 소유이고 CORE가 멈추면 지워지므로 쓰지 않는다.
- **영속 기록**은 `/var/lib/rosy/maintenance/lease.json`에 둔다. 필드는 holder, purpose, `boot_id`, `apply_id`다. 획득과 해제 이력은 `history.jsonl`에 남긴다.
- **재부팅을 건너는 적용.** 재부팅이 있는 적용(tryboot, 결정 7)이나 전원 차단 뒤에는 영속 기록의 `boot_id`가 지금 부팅과 다르다.
  - `rosy-update-resume.service`는 `rosy-core.service` 앞에서 돈다. 이것이 **CORE가 뜨기 전에** 그 적용을 위해 리스를 다시 잡는다. 그래서 재부팅 직후에도 이동 요청은 409다.
  - 끝나지 않은 적용이 없으면 옛 기록을 닫는다.
- 필드: `holder`(사람·세션·콘솔 id), `purpose`(`update`·`calibration-restart`·`bench`·`card-prep` 등), `acquired_at`, `expires_at`, `heartbeat_at`.

**획득 규칙.** 다음 가운데 하나라도 참이면 거절한다.
- 다른 리스가 살아 있다.
- CORE가 쓰는 중이라고 보고한다.
  - `mode`가 MANUAL·NAVIGATION·DOCKING이다.
  - `navigation`이 진행 중이다.
  - `line_follow`가 켜져 있다.
  - `docking.state`가 DOCKING·UNDOCKING이다.
  - 교정 세션이 있다. 병합된 뒤부터 `activity: CALIBRATING`으로 본다.
- 이동 중이다. 기준은 결정 10과 같다.

**만료와 해제**
- 무기한 리스는 없다. TTL 기본 15분, heartbeat로 연장한다.
- 적용 중에는 러너가 heartbeat를 소유한다.
- 강제 해제는 administrator가 이유를 적어야 하고, 기록이 남는다.

**리스가 살아 있는 동안**
- CORE 스냅샷은 `activity: MAINTENANCE`를 싣는다.
- 움직임을 시작하는 요청(teleop, mode, goal, line-follow, dock)은 409 `MAINTENANCE_ACTIVE`를 받는다.
- 비상정지와 정지 경로는 늘 열려 있다.
- 교정 세션 리스와 같은 모양을 쓰고, 두 리스는 서로 배타다.

**반드시 리스를 잡는 도구**
- `rosy-release-push.ps1`과 적용 러너
- `rollback-release.sh`
- 유닛을 재시작하는 스킬과 스크립트
- 콘솔 Apply
- 에이전트 세션의 ssh 재시작

P3에서는 sudoers를 좁히고 호스트 에이전트를 거치게 해서 강제한다.

**리스 전의 잠정 규칙(P1부터, 이미지 변경 없음)**
- **claim은 원자적으로 만든다.** 푸시 스크립트와 스킬은 ssh로 `sudo mkdir /run/rosy-claim`을 한다. mkdir은 이미 있으면 실패하므로 원자적이다. 성공한 쪽만 그 안에 `claim.json`(holder, purpose, `expires_at`, `boot_id`)을 쓴다.
  - mkdir이 실패하면 멈추고 holder를 보여 준다.
  - 만료된 claim은 `mv /run/rosy-claim /run/rosy-claim.stale.<rand>`로 한 명만 치울 수 있고, 치운 쪽이 다시 mkdir한다.
  - `/run/rosy`는 쓰지 않는다.
- **쓰는 중이면 멈춘다.** `/api/v1/robot/state`를 10 s 동안 읽어 결정 10의 이동·모드 조건을 확인한다.
- **P1 산출물: 프로젝트 훅.** `.claude/settings.json`에 PreToolUse 훅을 둔다.
  - 훅은 `rosy-release-push.ps1` 밖에서 ssh로 부르는 다음 명령을 막는다: `systemctl (restart|stop|start) rosy-*`, `activate-release.sh`, `rollback-release.sh`, `native_release.py (activate|rollback)`, `sync-image-layer.py`.
  - 이 훅은 에이전트 세션만 막는다. 사람에게는 운영자 알림 규칙("rosy-pinky-xxxx를 HH:MM까지 씀")을 적용한다.
- 잠정 규칙은 협조용이고, P3의 리스로 대체한다.

**5. 승인 기록과 감사.**

**콘솔(P3)**
- 운영자는 콘솔에서 (릴리스 id, 대상 로봇 집합, 롤아웃 정책)을 보고 Apply를 누른다.
- 콘솔은 함께 보여 준다: 매니페스트 sha256, 바뀌는 계층, 재부팅 여부, 로봇별 적격성과 이유.
- Fleet은 승인 레코드를 추가 전용 감사 표에 남긴다(D-341 감사 표 재사용). 레코드 필드: `approval_id`, `operator`, `approved_at`, `release_id`, `manifest_sha256`, `targets`, `policy`.

**P1의 승인과 감사(Fleet 전)**
- 푸시 스크립트가 계획 표를 보여 준다. 운영자가 `APPLY <release-id>`를 입력해야 시작한다.
- 운영 PC의 감사 기록은 증거 폴더의 JSONL이다: `X:\DevTemp\rosy-rollout-evidence\<YYYY-MM-DD>\rollout.jsonl`. 항목은 계획, 입력한 승인, 로봇별 결과다.
- 로봇 쪽 기록은 `/var/lib/rosy/updates/history.jsonl`이다.

**권한 분리**
- 서명은 내용을 허가하고, 승인은 시점과 대상을 허가한다. 승인은 서명되지 않은 릴리스를 적용하게 할 수 없다. 서명은 승인 없이 적용을 일으키지 않는다.
- 로봇 이벤트: `release.apply_started|committed|rolled_back|refused|skipped`. 각 이벤트에 `approval_id`와 단계, 이유가 실린다.

**자격(사용자 결정 1)**
- 로봇마다 업데이트 전용 자격을 D-361 등록 흐름으로 발급한다.
- 권한은 `release.stage|apply|rollback|status`와 리스 획득뿐이다. 운전 권한과 administrator 권한은 없다.
- administrator 토큰을 Fleet에 두는 안은 기각한다.

**6. 3계층은 버전이 붙은 멱등 일회성 migration으로 싣고, 런타임은 릴리스가 고른다.**

**migration 형식**
- 릴리스의 `deploy/robot/migrations/<NNNN>-<slug>/`에 `migration.json`과 `check`, `apply`, `revert`를 둔다.
  - `migration.json` 필드: `id`, `class`(`userspace`|`boot`), `requires`, `touches`(허용 경로), `reboot`.
- `check`는 부작용 없이 판정한다. `apply`는 여러 번 돌려도 결과가 같아야 한다.
- 기기는 `/var/lib/rosy/migrations/applied.json`에 `{id, sha256, release_id, applied_at, class}`를 적는다.
  - 번호 순서대로만 적용한다.
  - 같은 id인데 sha256이 다르면 거절한다.

**`userspace` 클래스.** apt 핀, 추가 deb, `/usr/local` 파이썬, 허용된 `/etc` 파일이다.
- 적용 전에 바꿀 파일과 이전 패키지(.deb 캐시)를 백업한다.
- `revert`는 그 백업으로 되돌린다.
- **`revert`가 없는 migration은 받지 않는다.** 되돌릴 수 없는 변경은 카드(결정 14)나 P4 번들로 한다.

**런타임은 릴리스가 고른다.**
- 새 파이썬 런타임은 `/usr/local/lib/rosy-python/<runtime-id>/site-packages`에 나란히 깐다. `pip install --target`으로, hash 잠금 requirements를 쓴다. 이미지가 깐 원래 런타임은 그대로 있다.
- 각 릴리스는 `deploy/robot/native/python-runtime.env`를 싣는다.
  - 릴리스의 런타임 id가 이미지 기본 id와 같으면 이 파일은 비어 있다.
  - 다르면 `PYTHONPATH=/usr/local/lib/rosy-python/<id>/site-packages`를 담는다.
- D-388이 동기화하는 유닛은 `EnvironmentFile=-/opt/rosy/current/deploy/robot/native/python-runtime.env`를 읽는다. 그래서 **실제로 쓰는 런타임은 `current` 링크와 함께 원자적으로 바뀐다.**
- **런타임 기록**(`/usr/local/share/rosy/python-runtime.sha256`)은 활성화와 롤백의 허용 검사에만 쓴다(`check_python_runtime`). 불변식은 "기록 = `current` 릴리스의 런타임 id"다.
  - **적용:** 단계 4에서 기록을 새 id로 바꾸고, 이전 값을 journal에 둔다. 그다음 활성화한다. 옛 이미지의 검증기도 이 순서면 통과한다.
  - **롤백:** 기록을 **먼저** `previous` 릴리스의 id로 되돌리고, 그다음 `native_release.py rollback`을 부른다. `rollback()`의 `check_python_runtime`(:341)은 되돌린 기록과 비교하므로 통과한다.
  - **부팅 복구:** `recover()`(:365)는 런타임을 검사하지 않고 `old_current`로 되돌린다. 바로 뒤에 도는 `rosy-update-resume.service`가 journal을 읽어, 기록을 `current` 릴리스의 id로 맞춘다. 그래서 복구 뒤에도 불변식이 선다.
  - 나란히 깐 런타임 디렉터리는 롤백으로 지우지 않는다. 어떤 보관 릴리스도 쓰지 않게 된 뒤에 치운다.
- 런타임 id의 정의(파일 전체 sha256)는 **바꾸지 않는다**. 바꾸면 이미 구운 로봇의 검증기가 새 payload를 모두 거절한다. 새 이미지의 검증기는 나중에 "기록과 같음" 대신 "`rosy-python/<id>`가 있음"을 볼 수 있다. 그 변경은 별도로 한다.

**커널**
- `linux-raspi*`, `flash-kernel`, `linux-firmware-raspi`는 apt hold로 묶는다.
- 커널과 모듈 변경은 `boot` 클래스로만 한다.
- `unattended-upgrades` 상태는 P2 첫 게이트에서 확인한다.

**7. 부팅 변경(`config.txt`, `cmdline.txt`, 커널, 모듈)은 단독 릴리스로, 두 접두 디렉터리 사이에서 tryboot로 한다.**

**단독 릴리스**
- `boot_change: true`인 릴리스는 `boot` migration 하나만 담는다.
- 1·2계층 내용은 로봇의 `current`와 같아야 한다(`requires.current_release`). userspace migration도 섞지 않는다.
- 그래서 tryboot가 실패해 firmware 쪽만 되돌아가도, 되돌릴 다른 계층이 없다.

**레이아웃(P2, 파티션을 바꾸지 않는다)**
- 커널, initramfs, dtb, overlay, `cmdline.txt`는 `/boot/firmware/rosy-a/`와 `/boot/firmware/rosy-b/` 두 디렉터리에 둔다.
- `config.txt`는 짧은 고정 크기 파일이다. 담는 것은 `os_prefix=rosy-a/`와 `include rosy-a/config.txt`, 그리고 같은 길이를 맞추는 주석 패딩이다.
- 각 슬롯의 `cmdline.txt`에는 `rosy.bootslot=a|b`가 있다. 부팅한 슬롯은 `/proc/cmdline`으로 안다.
- 처음 변환(지금 `/boot/firmware` 루트의 파일을 `rosy-a/`로 옮김)은 watchdog migration과 함께 하는 첫 `boot` 적용이다(아래).

**적용**
1. 러너가 비활성 슬롯(예: `rosy-b/`)을 후보로 채우고 fsync한다.
2. `tryboot.txt`에 `os_prefix=rosy-b/`와 `include rosy-b/config.txt`를 쓴다.
3. `/var/lib/rosy/updates/boot-pending.json`에 적는다: 후보 슬롯, 이전 슬롯, migration id, `boot_id`, 시도 횟수 1. 이 파일은 재부팅을 건넌다.
4. 리스를 영속 기록에 남긴 채 `reboot "0 tryboot"`.

**판정**
- 다음 부팅에서 `rosy-update-resume.service`가 CORE보다 먼저 돈다. 리스를 다시 잡고 `boot-pending.json`을 읽는다.
- **부팅한 슬롯이 이전 슬롯이면** tryboot가 실패한 것이다(watchdog 또는 전원 리셋). 다음을 하고, 같은 migration을 다시 시도하지 않는다.
  - `release.rolled_back{reason: tryboot}`를 보고한다.
  - migration을 실패로 기록한다.
  - 후보 슬롯을 비운다.
  - pending을 지운다.
- **후보 슬롯이면** 건강 판정(결정 9)을 한다.
  - 통과하면 커밋한다.
  - 실패하면 pending에 실패를 적고 보통 재부팅한다. 플래그가 지워져 이전 슬롯으로 돌아오고, 위 경우로 보고된다.

**커밋**
- 커밋은 `config.txt` 한 파일을 제자리에서 같은 길이로 덮어쓰는 것이다. `rosy-a` ↔ `rosy-b` 한 글자와 include 경로만 바뀐다.
- rename도, 크기 변경도, 디렉터리 항목 변경도 없다. FAT에서 rename은 전원 차단에 안전하지 않기 때문이다.
- 한 섹터 안의 덮어쓰기가 전원 차단에 원자적이라는 것은 **가정(A)**이다. P2 DEVICE 게이트가 커밋 중 전원 차단을 시험한다.
- 커밋 뒤 한 번 더 보통 재부팅해 확인하고 pending을 지운다.

**watchdog migration**
- 첫 번째 `boot` migration은 watchdog을 켜고 슬롯 레이아웃으로 바꾸는 것이다. 넣는 설정: `dtparam=watchdog=on`, 가능하면 `kernel_watchdog_timeout`, systemd `RuntimeWatchdogSec`, cmdline `panic=10`.
- 이것 자체가 부팅 변경이다. 그 전에는 멈춘 부팅이 스스로 돌아오지 않는다.
- 그래서 **어느 로봇이든 첫 적용에는 현장에 운영자가 있어야 한다.** 멈추면 운영자가 전원을 껐다 켠다. 리셋이 tryboot 플래그를 지워 이전 설정으로 돌아온다.

**다른 제약**
- FAT 용량(두 슬롯)은 P2 첫 게이트에서 잰다.
- 나중에 25.10 이상으로 가면 Ubuntu `piboot-try`와 겹친다(위험 R4).

**8. 모든 계층에 되돌림이 있고, 순서는 적용의 역순이다.**

| 계층 | 되돌림 | 부팅 중·부팅 불가 |
|---|---|---|
| 2 | D-388 백업 매니페스트 복원 | `rosy-update-resume`이 journal로 복원을 이어 한다 |
| 1 | 런타임 기록을 `previous`의 id로 되돌린 **뒤** `native_release.py rollback` | `recover()`가 `old_current`로 되돌리고, `rosy-update-resume`이 기록을 `current`의 id로 맞춘다 |
| 3 userspace | migration `revert`와 .deb 캐시. 나란히 깐 런타임은 남긴다 | `rosy-update-resume`이 journal에 적힌 적용된 migration을 revert한다 |
| 3 boot(단독) | tryboot 플래그가 리셋으로 지워진다. 커밋 전이면 이전 슬롯이다 | watchdog 또는 전원 리셋 → 이전 슬롯 |
| 4 | A/B 슬롯(`autoboot.txt` `tryboot_a_b`) | watchdog 또는 전원 리셋 → 이전 슬롯 |

- 적용 순서는 3 → 기록 → 1 → 2다. 되돌림은 2 → 1(기록 먼저) → 3이다.
- `rosy-update-resume.service`는 부팅 때 `rosy-release-recover.service` 다음, `rosy-core.service` 앞에서 돈다.
  - 끝나지 않은 적용 journal이 있으면 위 표의 역순으로 되돌리고 `rolled_back{reason: interrupted}`를 보고한다.
  - 1계층은 `recover()`가 먼저 되돌렸으므로 기록만 맞춘다.
- 되돌림까지 실패하면 `recovery-hold`를 남긴다(`updater.py` 선례). 모드는 CORE 전용(`ROSY_IO_DRIVE_ENABLED=false` 강제, 결정 13.5의 override)으로 둔다. 운영자가 `release.clear_hold`로 풀기 전까지 다음 적용을 받지 않는다.

**9. 건강 판정은 "CORE 준비"보다 넓게 한다.** 커밋 전에 모두 확인한다. 상한은 120 s이고, 넘기면 실패다.

- CORE 준비(`wait-core-ready.py`)
- `rosy-io` 활성. 드라이브 끔 상태에서 센서와 엔코더 관측(`evidence` 신선)
- 실패한 `rosy-*` 유닛 0개
- `/cmd_vel` publisher가 CORE 하나뿐. 확인 방법은 결정 13.2를 따른다.
- 적용 전과 같은 `robot_id`와 등록 자격
- FleetAgent 재연결
- D-388 드라이런 결과가 비어 있음(이미지 계층 드리프트 없음)

**10. 롤아웃은 한 대씩, 쓰지 않는 로봇부터 한다.**

**적격성.** Fleet(P3)이나 푸시 스크립트(P1)가 계산해 보여 주는 것은 참고용이다. 러너가 단계 1~2에서 다시 확인한 결과가 권위다. 입력은 `/api/v1/robot/state` 한 곳이다(Context 1). 다음을 모두 만족해야 적격이다.
- online
- **이동하지 않음:** 10 s 동안 `|velocity.linear|` < 0.01 m/s이고 `|velocity.angular|` < 0.02 rad/s여야 한다. 그 동안 `evidence["velocity"]`가 신선해야 한다. stale이면 **부적격**이다. 모르면 움직이는 것으로 본다.
- `mode`가 IDLE, `navigation`이 IDLE·ARRIVED·CANCELED·FAILED 가운데 하나, `line_follow` 꺼짐
- `docking.state`가 DOCKING·UNDOCKING이 아님
- 대기열, claim, 편대가 없음(Fleet이 아는 경우). 교정 세션 없음(병합 뒤).
- estop 아님, RECOVERY HOLD 아님
- 배터리 40% 이상 또는 `docking.state`가 CHARGING. 재부팅이 있는 적용은 60% 이상(사용자 결정 2).
- 스테이징 완료

**순서**
1. `docking.state`가 DOCKED 또는 CHARGING인 유휴 로봇
2. 그냥 유휴인 로봇

**부적격 로봇은 건너뛴다.** 롤아웃을 멈추지 않는다.
- `skipped{reason}`로 기록하고 끝에 목록으로 보여 준다.
- 운영자가 나중에 그 로봇만 다시 돌린다.

**진행**
- 첫 로봇이 canary다. 커밋 뒤 10분(사용자 결정 2) 동안 되돌림이 없어야 다음 로봇으로 간다.
- 운영자는 대기를 줄일 수 있지만 0으로 건너뛸 수는 없다. 최소값은 1분이다.
- **되돌림이 한 번이라도 나면 롤아웃을 멈춘다.** `rolled_back` 또는 tryboot 실패가 여기에 든다.
- 동시에 적용 중인 로봇은 한 대다.

**11. 대역은 파일 단위 내용 주소 delta와 이어받기로 줄인다.**

- 1계층 매니페스트에는 파일마다 sha256이 있다. 로봇은 가진 릴리스에 없는 해시만 받고, 나머지는 로컬에서 하드링크하거나 복사한다.
  - HTTP `Range`로 이어받는다. 서명은 여전히 `SHA256SUMS` 전체를 덮는다.
- 전체 tarball 경로도 남긴다. P1 PC 푸시와 캐시가 없는 로봇이 쓴다.
- 이진 delta는 측정해서 필요가 드러날 때까지 들이지 않는다. 4계층은 RAUC `block-hash-index`나 casync가 맡는다.
- 공간은 `storage.check_update_headroom` 규칙을 쓴다. 보관하는 릴리스는 `current`, `previous`, staged 하나다.

**12. 2026-10-01 교훈이 설계에 들어가는 자리.**

| 교훈 | 막는 방법 |
|---|---|
| 런타임 id가 주석 바이트까지 해시한다 | `requires`를 스테이징에서 먼저 검사해, 불일치를 적용 전 `refused`로 드러낸다. id 정의와 `test_python_runtime_id.py` 핀은 그대로 둔다. 그 교훈의 "런타임을 올리려면 새 이미지가 필요하다"는 **이 ADR이 대체한다**: 런타임은 결정 6의 나란히 설치와 기록 전환 migration으로 올린다 |
| 일괄 경로 치환이 기기 릴리스 경로를 건드렸다 | 기기 경로는 기기 계약이다: `/opt/rosy/releases/<id>/deploy/robot/native/…`, `deploy/robot/migrations/…`, `/boot/firmware/rosy-{a,b}/`, `/var/lib/rosy/updates/…`, `/run/rosy-maintenance/`. 생산자(payload 빌더)에서 경로를 만들고, `test_release_layout_paths.py` 방식의 존재 검사로 지킨다 |
| payload 푸시가 이미지 계층을 옛것으로 남긴다 | D-388 동기화가 적용 트랜잭션의 필수 단계다. 건강 판정은 드리프트가 남으면 커밋하지 않는다 |
| readback이 CPU를 빼앗긴다 | **네트워크 경로에서만 피한다.** 이 경로는 카드 readback이 없고, 기기 쪽 검증은 스테이징에서 `Nice`와 idle IO로 돈다. 카드 경로(결정 14)에는 그 교훈의 규칙이 그대로다: **카드 쓰기의 확인 단계부터 receipt까지 운영 PC에서 백그라운드 에이전트와 무거운 작업을 돌리지 않는다.** 긴급 절차는 D-389를 따른다 |

**13. 안전 불변식.** 모든 단계의 시험이 이것을 고정한다.

1. **이동 중에는 적용하지 않는다.** 리스를 획득할 때와 각 단계 사이에 다시 확인한다. 적용 중에 이동 명령은 409로 거절한다. 비상정지는 늘 열려 있다.
2. **CORE만이 최종 `cmd_vel` publisher다.** 업데이트 도구, 러너, 호스트 에이전트, migration은 `cmd_vel`을 publish하지 않는다. 움직임 관련 토픽을 구독하거나 ROS 노드로 상주하지도 않는다.
   - 결정 9의 publisher 확인은 CORE가 보고하는 값을 먼저 쓴다.
   - 그것이 없으면 건강 판정 동안 한 번, publish하지 않는 짧은 관측(`ros2 topic info /cmd_vel`에 해당하는 읽기 전용 조회)만 한다.
3. **모든 계층에 되돌림이 있다**(결정 8). 되돌림이 없는 변경은 적용하지 않는다.
4. **부팅하지 못하는 로봇은 스스로 돌아온다.** 마지막으로 좋았던 슬롯이나 릴리스로 돌아온다. 수단은 watchdog 리셋 또는 전원 리셋에 따른 tryboot 플래그 해제, `recover()`, `rosy-update-resume`이다.
   - watchdog migration 전의 로봇에는 운영자 입회 없이 `boot` 변경을 적용하지 않는다.
5. **적용 중 `rosy-io`는 드라이브를 끈 채로 돈다. `/etc/rosy/runtime.env`는 건드리지 않는다.**
   - **적용 시작 때.** 러너가 휘발 drop-in `/run/systemd/system/rosy-io.service.d/50-rosy-update-drive-off.conf`를 쓴다. 내용은 다음과 같다.
     - `EnvironmentFile=`(목록 초기화)
     - `EnvironmentFile=/etc/rosy/runtime.env`
     - `EnvironmentFile=/run/rosy-maintenance/drive-off.env`. 뒤 파일이 이기고, 이 파일에는 `ROSY_IO_DRIVE_ENABLED=false`가 있다.
   - 그리고 `daemon-reload`를 한다. `rosy-io`의 `ExecStartPre` 조합 검사(core·motor·hardware에 false)는 이 상태를 받는다.
   - **커밋 때.** 러너는 다음 순서로 드라이브를 되살린다.
     1. drop-in을 지운다.
     2. `daemon-reload`를 한다.
     3. `runtime.env`의 드라이브 승인이 true이면 `rosy-io`를 한 번 재시작한다. 로봇은 정지 상태이고 리스는 아직 잡혀 있다.
     4. 새 인스턴스가 뜨고 CORE가 모터 준비를 보고하는지 확인한다.
     5. 리스를 놓는다.

     재시작이나 확인이 실패하면 커밋하지 않고 되돌린다.
   - **되돌릴 때와 RECOVERY HOLD 때.** 같은 drop-in을 쓴다. drop-in이 `/run`에 있으므로 재부팅하면 사라진다. 그래서 `rosy-update-resume`이 필요하면 다시 쓴다.
6. **긴급 카드 쓰기(D-389 `-Emergency`)는 마지막 수단으로 남는다.** 네트워크 경로가 이것을 대신하지 않고, 이것도 네트워크 경로를 대신하지 않는다.

**14. 카드가 여전히 필요한 경우.**

- 첫 설치. 새 로봇과 새 카드는 서명 이미지와 개인화로 시작한다(D-164, D-154).
- 물리적으로 망가진 카드, 또는 부팅도 되돌림도 안 되는 로봇
- A/B 레이아웃으로 바꾸는 한 번(P4). 로봇마다 한 번이다.
- P4 전의 큰 OS 업그레이드(24.04 → 26.04 등)
- 되돌릴 수 없는 기반 시스템 변경(결정 6에서 migration으로 받지 않는 것)

**15. 4계층(A/B 전체 이미지)을 열어 둔다.**

**목표 레이아웃(P4).** 사용자 결정 4에 따라 GPT, 32 GB 이상 카드다. 파티션은 다음과 같다.
- `autoboot.txt`만 든 작은 FAT
- boot A와 boot B(FAT)
- root A와 root B(ext4)
- `data`(`/etc/rosy` 신원, `/var/lib/rosy`, 홈)

**P1~P3가 지킬 제약**
- 기기 상태는 선언된 경로 목록(`deploy/robot/state-paths.txt`, 새로 둠) 밖에 새로 두지 않는다. 이 ADR의 `/var/lib/rosy/updates`, `/var/lib/rosy/maintenance`, `/var/lib/rosy/migrations`도 목록에 든다.
- `boot` 변경은 boot 파티션 안의 파일로만 표현한다.
- `rosy-update-resume`과 건강 판정은 P4의 "mark good"으로 그대로 쓴다.
- 서명 형식과 카탈로그는 번들에도 그대로 쓴다.

**프레임워크.** 후보 순서는 RAUC(custom tryboot backend), in-house writer, SWUpdate다. Mender는 기각한다. 최종 선택은 P4 스파이크 뒤에 한다.

**16. 단계와 게이트.**
- 게이트 등급은 HOST(호스트 시험), DEVICE(벤치 로봇), FIELD(현장 운용)다.
- 앞 단계의 GO는 뒤 단계의 증거가 아니다(D-291 5항).

**P1 — PC가 여러 로봇에 1·2계층을 펼친다. 적용은 로봇 위 트랜잭션이다**

- **범위**
  - `rosy-release-push.ps1`이 로봇 목록을 받는다.
  - 먼저 계획 표를 보여 주고, `APPLY <release-id>` 입력을 받는다. 표의 열: 로봇, 현재 릴리스, 대상 릴리스, 바뀌는 계층, 적격성과 이유, 예상 재시작 유닛.
  - 그 뒤 로봇마다 한 대씩 다음을 한다.
    1. 원자적 claim
    2. 적격성(10 s 샘플)
    3. scp와 unpack
    4. `systemd-run`으로 러너 시작. 러너는 결정 3의 검증 뒤에 돈다.
    5. 러너 관찰
    6. claim 해제
  - 운영자에게는 로봇마다 단계와 결과가 한 줄씩 보이고, 끝에 요약(committed/rolled back/skipped와 이유)이 나온다.
  - 부적격이면 건너뛴다. 되돌림이 나면 멈춘다(결정 10).
  - 감사 기록은 PC의 증거 폴더 JSONL과 로봇의 `history.jsonl`이다(결정 5).
  - `rosy-update-resume.service`는 러너와 함께 릴리스에 싣고, D-388 허용 목록으로 설치한다.
  - 에이전트 세션을 막는 PreToolUse 훅(결정 4)도 P1 산출물이다.
- **증거와 게이트**
  - HOST:
    - 러너의 단계, journal, 역순 되돌림
    - 가짜 ssh에서 연결이 끊겨도 러너가 끝나는지
    - claim 경합: mkdir 두 번 가운데 하나만 성공
    - 이동 중·velocity stale이면 거절
    - 드라이브 끔 drop-in 생성과 제거, 롤백 때 기록을 먼저 되돌리는지
    - 훅이 금지 명령을 막는지
  - DEVICE:
    - 벤치 두 대에 연속으로 적용하고 롤백한다.
    - 한 대를 움직이는 상태로 두어 건너뛰는지 본다.
    - 적용 도중 PC 연결을 끊는다.
    - 적용 도중 전원을 끊어 `rosy-update-resume`이 되돌리는지 본다.
  - FIELD: 해당 없음.
- **선행 조건:** D-388 실기(2026-10-02)와 D-225 `UPDATE_GO`.
- **수동으로 남는 것:** 서명, 릴리스 선택, 푸시 시작과 승인 입력, 3·4계층.
- **열린 질문:** 에이전트 세션 식별자를 `holder`에 어떤 형식으로 적을지.

**P2 — 3계층 migration과 tryboot**

- **범위**
  - migration 형식과 `applied.json`
  - userspace revert
  - 런타임 나란히 설치와 `python-runtime.env`
  - 커널 hold
  - watchdog과 슬롯 변환 migration
  - 단독 `boot` 릴리스와 `boot-pending.json` 판정
- **첫 게이트(사용자 결정 5).** 벤치 한 대에서 읽기 전용으로 Context 4의 가정을 확인한다. 다르면 결정 7을 먼저 고친다.
- **증거와 게이트**
  - HOST:
    - migration 멱등, 순서, 해시 불변, revert
    - 롤백 순서(기록 → 1계층)가 `check_python_runtime`을 통과하는지
    - `recover()` 뒤 기록 맞춤
    - 가짜 `/boot/firmware`에서 슬롯, `tryboot.txt`, 같은 길이 `config.txt` 생성
  - DEVICE: 벤치 한 대에서 다음을 한다. 각 항목에 전원 차단 1회를 포함한다.
    - (a) watchdog과 슬롯 변환. 운영자 입회
    - (b) 일부러 부팅하지 못하게 한 슬롯이 이전 슬롯으로 돌아오고 `rolled_back{reason: tryboot}`가 보고되는지
    - (c) 커널 교체와 되돌림
    - (d) 런타임 전환과 롤백
    - (e) 커밋 중 전원 차단
  - FIELD: 현장 로봇마다 watchdog migration을 운영자 입회 아래 한 번씩 한다.
- **열린 질문:** `kernel_watchdog_timeout`의 의미, 되돌릴 수 없는 apt 변경을 migration에서 어떻게 막을지(검사 규칙).
- **수동으로 남는 것:** 적용 시작(PC)과 로봇마다 첫 watchdog 적용 입회.

**P3 — 기기 스테이징, 콘솔 승인, 정비 리스**

- **범위**
  - Fleet 카탈로그와 업로드
  - 로봇 쪽 스테이징 타이머. 새 이름으로 만들고, 레거시 `rosy-update-check`는 되살리지 않는다.
  - `rosy-host-agent.service`가 리스를 소유한다(`/run/rosy-maintenance`와 `/var/lib/rosy/maintenance`).
  - CORE `activity: MAINTENANCE`와 409
  - 업데이트 전용 자격
  - 콘솔 Apply, 롤아웃 오케스트레이터, 승인 감사, 파일 단위 delta와 이어받기
  - sudoers를 좁혀 리스 없는 재시작을 막는다.
- **이미 정한 것:** 리스 소유(사용자 결정 3), 도킹 판정(`docking.state`, Context 1), 배터리 문턱과 canary 대기(사용자 결정 2), 자격 유형(사용자 결정 1).
- **증거와 게이트**
  - HOST: 적격성 술어, 리스 배타(교정, 모드), 만료, 강제 해제 감사, 재부팅 뒤 CORE 전 재획득, 승인 없는 적용 거절, 서명 없는 카탈로그 거절, 이어받기.
  - DEVICE: 세 대로 롤아웃한다. 한 대는 MANUAL, 한 대는 CHARGING, 한 대에는 일부러 실패를 넣어 canary 중단을 확인한다.
  - FIELD: 현장 롤아웃 1회를 운영자가 승인한다.
- **열린 질문:** 업데이트 자격의 회수와 교체 절차, sudoers를 좁힌 뒤 벤치 작업(`rosy-hw-bringup`)을 어떻게 할지.
- **수동으로 남는 것:** 서명(오프라인 키), Apply 승인, RECOVERY HOLD 해제.

**P4 — A/B 전체 이미지**

- **범위**
  - A/B 레이아웃 이미지(GPT, 32 GB 이상)
  - 프레임워크 스파이크(RAUC custom backend 대 in-house)
  - 번들 서명 연결
  - 로봇마다 카드 한 번 변환
  - OS 메이저 업그레이드를 번들로
- **증거와 게이트**
  - HOST: 번들 서명과 검증, 슬롯 선택 로직.
  - DEVICE: 설치 → tryboot → 커밋, 멈춤 → watchdog → 이전 슬롯, 설치 중 전원 차단, `data` 보존, Pi 5 GPT 부팅.
  - FIELD: 한 대씩 변환한다.
- **열린 질문:** Ed25519와 CMS를 어떻게 잇거나 감쌀지, adaptive 갱신의 실제 절감량.
- **수동으로 남는 것:** 변환 카드 기록과 첫 설치.

### 사용자 결정 — 2026-10-01 승인

사용자가 아래 다섯 기본값을 쓴 그대로 승인했다(2026-10-01). 결정 본문은 이 값을 따른다.

1. **Fleet 업데이트 전용 자격(결정 5, P3).**
   - 로봇마다 D-361 등록 흐름으로 발급한다.
   - 권한은 `release.stage|apply|rollback|status`와 정비 리스 획득뿐이다. 운전 권한과 administrator 권한은 없다.
   - Fleet에 administrator 토큰을 두는 안은 기각한다.
2. **배터리 문턱과 canary 대기(결정 10).**
   - 배터리 40% 이상 또는 충전 중. 재부팅이 있는 적용은 60% 이상.
   - 첫 로봇 커밋 뒤 10분. 운영자는 줄일 수 있으나 건너뛸 수 없다.
3. **정비 리스 소유(결정 4).** `host_agent.py` 계약(허용 목록, confirm, 감사)을 네이티브 root 서비스로 옮겨 소유한다. CORE는 리스를 읽어 `activity: MAINTENANCE`와 409만 낸다.
4. **A/B 카드와 파티션 표(결정 15).**
   - 32 GB 이상, GPT. 지금 이미지 raw가 약 8.6 GB이므로 root 두 벌(각 약 10 GB)과 boot 둘, data가 들어간다.
   - Pi 5 GPT 부팅은 P4 DEVICE 게이트에서 실측한다.
5. **Ubuntu 24.04 tryboot 기기 확인(P2 첫 게이트).** 벤치 한 대에서 읽기 전용으로 확인한다. 가정과 다르면 결정 7을 고친 뒤 P2를 연다.
   - `apt policy flash-kernel`(`piboot-try` 없음)
   - 커널 갱신 때 `flash-kernel`이 `/boot/firmware`에 쓰는 것
   - `/boot/firmware` 여유 용량
   - `vcgencmd bootloader_version`
   - `unattended-upgrades` 상태
   - `os_prefix`로 `cmdline.txt`도 접두 디렉터리에서 읽는지

### Alternatives

- **완전 자동 적용(승인 없음).** 사용자가 고른 방식이 아니다. 쓰는 중인지 판정하는 데는 오판이 있을 수 있어, 사람이 마지막으로 시점을 보는 편이 싸다. 기각.
- **로봇이 GitHub나 인터넷에서 직접 받는다.** 현장에 인터넷이 없을 수 있고, D-197/D-198이 GitHub polling을 퇴역시켰다. 승인 감사가 둘로 갈린다. 기각.
- **운영 PC를 영구 카탈로그로 둔다.** PC는 늘 켜 있지 않고 세션에 묶인다. 사고가 이 구조에서 생겼다. P1 동안만 쓴다.
- **PC가 단계마다 ssh로 부른다(지금의 푸시 방식).** 활성화와 D-388 동기화 사이에 연결이 끊기면 로봇이 반쯤 바뀐 채 남는다. 로봇 위 러너와 journal로 대체한다. 기각.
- **정비 리스를 CORE 안이나 `/run/rosy`에 둔다.** 적용이 CORE를 멈추면 `/run/rosy`가 지워지고, tmpfs는 재부팅을 건너지 못한다. 호스트 서비스 디렉터리와 `/var/lib/rosy` 영속 기록을 쓴다. 기각.
- **`native-release.lock`을 늘려 리스로 쓴다.** flock은 프로세스가 사는 동안만 유지되고, 소유자, 목적, 만료가 없다. 기각.
- **잠정 claim을 "확인한 뒤 만들기"로 한다.** 두 세션이 동시에 확인하면 둘 다 통과한다. `mkdir`의 원자성을 쓴다. 기각.
- **적용 중 드라이브를 끄려고 `runtime.env`를 고친다.** 장치별 드라이브 승인(D-291)을 업데이트 도구가 다시 쓰게 되고, 실패하면 승인이 사라진다. `/run` drop-in을 쓴다. 기각.
- **부팅 변경을 1~3계층과 한 릴리스에 섞는다.** tryboot가 실패하면 firmware 쪽만 되돌아가고 나머지 계층은 새것으로 남는다. 단독 릴리스로 한다. 기각.
- **FAT에서 rename으로 커밋한다.** 전원 차단에 안전하지 않다. 같은 길이 `config.txt` 덮어쓰기로 두 슬롯 사이를 전환한다. 기각.
- **Docker 시대의 `updater.py`/`delivery.py`를 되살린다.** Docker 이미지 적재를 전제하고, `os_suite`가 맞지 않고, 활성 기록 모델이 다르다. 호스트 에이전트의 허용 목록과 confirm, 감사, `recovery-hold` 개념만 가져온다.
- **3계층을 이미지 재기록으로만 한다(현 상태).** 카드마다 15~18분이 걸리고 사람이 가야 하며 CPU 경쟁이 있다. 기각.
- **3계층을 apt 저장소와 `apt upgrade`로 한다.** 버전을 고정하기 어렵고, 되돌림이 불완전하고, `flash-kernel`이 부팅 파일을 건드린다. 기각.
- **config.txt를 제자리에서 고치고 재부팅한다.** 틀리면 카드로만 되살릴 수 있다. 기각.
- **파일 시스템 스냅샷(btrfs/LVM).** ext4에서 바꾸려면 카드 재기록이 필요하고, 그 비용이면 P4가 낫다. 기각.
- **4계층 프레임워크**
  - **RAUC**(1순위): noble universe에 있고, Pi 5 custom backend 선례가 있고, `verity`와 adaptive를 지원한다. 비용은 CMS 신뢰 사슬과 backend 유지다.
  - **SWUpdate**(2순위): Pi 5 tryboot 선례가 없다.
  - **Mender**: U-Boot와 Debian 기준이고, 이진 delta가 상용이다. 기각.
  - **in-house writer**: Ed25519를 그대로 쓰고 의존성이 없다. 대신 adaptive와 전원 차단 처리를 떠안는다. RAUC 스파이크가 실패하면 대안이다.
- **Ubuntu Core 또는 OSTree로 옮긴다.** 플랫폼이 바뀐다. D-225 사유 그대로 기각.

### Consequences

- 기존 로봇의 모든 계층이 카드 없이 갱신된다. 예외는 결정 14다.
- 적용은 느려진다. 리스, 적격성, canary 대기, 한 대씩 진행 때문이다. 급한 수정도 승인과 canary를 거친다. 운영자는 대기를 최소 1분까지 줄일 수 있지만 건너뛸 수 없다(사용자 결정 2).
- 로봇에 새 부품이 생긴다: 적용 러너, `rosy-update-resume.service`, `rosy-host-agent.service`, 업데이트 자격. D-22에 따라 CORE 밖에 두고 허용 목록 명령으로 제한한다.
- Fleet에 새 자격 유형과 카탈로그가 생긴다. Fleet이 뚫려도 내용은 위조할 수 없다. 시점 선택과 보류는 가능하므로, 기기 쪽 리스와 적격성이 권위를 갖는다.
- 에이전트 세션은 P1부터 훅 때문에 로봇 유닛을 직접 재시작할 수 없다. 사람은 P3의 sudoers 전까지 알림 규칙을 따른다.
- 활성 파이썬 런타임이 이미지 기본값이 아닐 수 있다. 진단 도구는 `current` 릴리스의 `python-runtime.env`를 봐야 한다.

### Risks

- **R1.** watchdog migration 전에 부팅이 멈추면 자동으로 돌아오지 않는다. **전원을 껐다 켜면** tryboot 플래그가 지워져 이전 설정으로 돌아온다(A, P2에서 확인). 그래서 카드는 필요 없지만 현장에 사람이 있어야 한다. watchdog migration의 첫 적용은 로봇마다 운영자 입회로 한다.
- **R2.** `revert`가 불완전한 userspace migration은 로봇을 반쯤 바뀐 상태로 둘 수 있다. `check`와 `revert`를 짝으로 시험하고, `touches` 허용 목록으로 제한한다.
- **R3.** 적격성 오판. velocity가 stale이면 부적격으로 보고, 적용 중 이동 명령 409와 드라이브 끔 drop-in으로 이중으로 막는다.
- **R4.** Ubuntu 25.10+ `piboot-try`나 noble `flash-kernel`과 우리 슬롯이 충돌할 수 있다. 커널 패키지 hold로 막고, OS 메이저 업그레이드는 P4 번들로만 한다.
- **R5.** 오프라인 서명 키가 병목이다. 의도한 비용이다. 키 교체는 옛 키로 서명한 신뢰 저장소 migration으로 한다.
- **R6.** 한 섹터 덮어쓰기의 원자성이 카드마다 다를 수 있다(A). P2 DEVICE 게이트의 커밋 중 전원 차단 시험이 판정한다. 실패하면 P2 부팅 변경을 멈추고 P4로 미룬다.
- **R7.** 레거시 `rosy-update-check`와 Docker 경로를 헷갈릴 수 있다. P3의 새 유닛 이름을 따로 두고, 레거시 파일은 퇴역 표시한다(별도 변경).
- **R8.** PreToolUse 훅은 명령 문자열을 보고 막으므로 우회할 수 있다. P3의 sudoers와 리스가 진짜 강제 수단이다.

### Validation

이 ADR은 문서만이라 여기서 시험하지 않는다. 각 단계 게이트(결정 16)가 실행 계획의 수용 기준이 된다. 각 단계 계획서(`docs/plans/`)는 다음을 적는다.
- HOST 시험의 파일 이름
- 새 방어마다 "깨뜨려 빨강, 되돌려 초록" 증명
- DEVICE와 FIELD 기록 위치(`deploy/logs.md`)

### References

- **결정:** D-22(호스트 권한 분리), D-145/D-146(오프라인 서명), D-154(개인화), D-161(네이티브 런타임), D-164(서명 이미지), D-174, D-180/D-187/D-188(카드 쓰기와 readback), D-189(런타임 id), D-197/D-198(Docker updater 퇴역), D-225, D-291, D-341(감사 표), D-361(등록과 토큰), D-382, D-388(이미지 계층 동기화, `feat/release-image-layer-sync`), D-389(긴급 카드 쓰기, `fix/card-write-confirm-and-artifact-download`)
- **코드:**
  - `deploy/robot/pinky_pro/native/native_release.py`(:254, :303, :334, :365)
  - `native/activate-release.sh`
  - `native/rosy-core.service`(:42, :56, :60)
  - `native/rosy-boot-status.service`(:15)
  - `native/rosy-io.service`
  - `native/rosy-release-recover.service`
  - `native/wait-core-ready.py`
  - `rosy-release-unpack.sh`
  - `rosy-release-push.ps1`
  - `image/first-boot/rosy-first-boot.py`(:418)
  - `release/{updater,delivery,host_agent,host_agent_server,cli,github_release,artifact_impact,storage,signing}.py`
  - `rosy-update-check.{service,timer}`, `install-update-tools.sh`
  - `src/runtime/api_web/core_api_web/api/v1/robot.py`
  - `src/contracts/foundation/core_common/protocol/{schemas,evidence}.py`
  - `src/runtime/gateway/core/bridge/ros_bridge.py`
  - `src/site/fleet/fleet/server/{app,roster,dispatch_admission,enrollment,enrollment_store,discovery}.py`
  - `docs/reference/rosy-host-agent-contract.md`
- **교훈** (`docs/solutions/workflow-issues/`):
  - `payload-runtime-id-hashes-comments-too-2026-10-01.md`
  - `blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md`
  - `payload-push-leaves-the-image-layer-stale-2026-10-01.md`
  - `card-readback-slows-under-parallel-cpu-load-2026-09-25.md`(2026-10-01 재발 절)
- **브랜치:** `feat/release-image-layer-sync`, `fix/card-write-confirm-and-artifact-download`, `feat/calibration-session-mode`
- **외부 출처:** Context 4항의 URL(가정으로 표시)
