## D-888 Pinky 전체 OS 업데이트는 bootstrap 영속 입력과 별도 CMS 서명을 사용한다

**Status:** Proposed

### Context

D-387의 RAUC 전체 OS 업데이트와 D-879·D-881의 GPT 실험 구현을 함께 검토했다.
기존 실험 이미지는 양쪽 root에서 boot A를 등록·설정용으로 계속 마운트한다.
B에서 비활성 boot A를 교체하면 사용 중인 FAT를 덮어쓰고, 전원 중단 후 B의 상태 수용까지 막을 수 있다.
또한 Ubuntu 24.04의 OpenSSL 3.0.13에서 Ed25519 CMS 서명은 기본 digest 부재로 실패했다.
동일 환경의 ECDSA P-256 CMS 서명·검증은 성공했다. 이는 암호 기능 시험이며 제품 서명이나 이미지 수용이 아니다.

### Decision

1. 새 factory 이미지는 bootstrap 1에 등록·설정·진단 입력을 유지한다.
   boot A/B 2·3과 root A/B 4·5만 OS installer가 교체한다. 공통 data 6은 유지한다.
   descriptor schema 2, kernel marker `ab-v2`, boot ABI 2로 이 경계를 명시한다.
   새 SDK는 기존 schema 1/`ab-v1`과 새 프로토콜을 읽는다. 자동 OS 업데이트는 2만 허용한다.
   물리 카드의 자동 변환은 하지 않는다. 기존 MBR과 boot A 실험 이미지의 읽기·준비 호환은 유지한다.
   GPT 자체에는 등록 정책이 없으므로 서명된 layout의 `provision_role`을 실제 GPT 검증에 전달한다.

2. 배포 JSON과 native payload의 기존 Ed25519 검증은 유지한다.
   RAUC verity bundle의 CMS에는 별도로 고정한 ECDSA P-256 X.509 공개 인증서를 사용한다.
   인증서 검증·유효기간을 우회하지 않는다. 개인 키는 hosted CI에 넣지 않는다.
   기존 D-387의 동일 Ed25519 키 CMS 전제는 이 결정으로 정정한다.
   제품 인증서·키 설정, 실제 서명과 공개 게시에는 별도 권한과 증거가 필요하다.

3. Noble RAUC 1.11.3의 custom backend는 설치와 부팅 승격을 분리한다.
   `activate-installed=false`로 설치 후 검증을 마치고 현재 코드가 tryboot를 요청한다.
   실제 RAUC daemon에 비활성 root/boot만 쓰기 허용하고, bootstrap 변경은 별도 commit owner가 담당한다.
   후보 bundle의 hook·custom installer를 실행하지 않는다.
   영속 transaction과 motion inhibition을 재부팅 전후 유지하고, 최종 arm 직전에 새 상태로
   배터리 60% 이상·정지를 확인한다. 충전 중에도 OS 배터리 기준을 낮추지 않는다.
   native payload의 기존 정책은 별도로 유지한다.

4. trial은 독립 deadline과 watchdog 증거를 요구한다.
   동일 부팅의 trial·health·GOOD_ACK를 확인한 commit owner만 기본 슬롯을 바꾼다.
   상태 손상·불명확한 증거는 HOLD다. 정상 부팅을 trial timeout으로 재부팅하지 않는다.
   bootstrap FAT 손상으로 Linux 진입이 막히는 경우는 userspace 복구 보장에 포함하지 않는다.
   식별한 카드의 data를 보존하는 오프라인 복구 절차와 전원 중단 실물 시험이 필요하다.

5. OS feed는 payload feed와 이름·schema·버전 상태를 분리한다.
   서명된 `os-update.json`과 `os-rollout.json`을 파싱 전에 검증하고 RAUC 인증 metadata와 대조한다.
   실패·withdrawal·canary·승격 지연은 OS committed release를 기준으로 처리한다.
   공통 상태 schema 1을 유지하며 후보 코드의 migration을 실행하지 않는다.

### Consequences

배포 metadata는 기존 Ed25519로 원본 JSON 바이트를 먼저 검증한 뒤 중복 키와 예상 밖 필드를 거절한다. bundle 이름·SHA256·크기, board/arch, compatible, native factory, boot ABI 2와 state reader/writer 1, CMS signer SPKI를 결속한다. verifier는 private staging의 0400 일반 파일과 소유권·단일 link·동일 inode를 확인하고 전체 hash를 대조한다. CMS footer 크기를 먼저 제한한 뒤 RAUC 1.11.3의 실제 검증을 실행한다. JSON2의 인증된 inner metadata와 외부 metadata를 대조하고 hook·custom handler·adaptive 설치를 거절한다. CMS에는 고정된 P-256 인증서 하나만 허용하며 현재 시간의 유효기간 검사를 유지한다.

서명 검사에 사용하는 sealed slotless `bootloader=noop` 설정은 `info` 전용이다. 설치 설정은 fresh media capture로 현재 카드의 장치를 정하고 비활성 두 partition에 후보가 들어가는지 확인하여 별도로 생성한다. `bootloader=custom`, `activate-installed=false`, rootfs와 child boot의 A/B 묶음, 공통 RAUC data-directory를 사용한다. 동적으로 생성하는 DeviceAllow는 daemon에 적용할 입력이며 비활성 root/boot rw와 parent r, loop/verity 장치만 포함한다. 설정 생성 자체는 설치 권한이 아니다. OS-owned unit·root-only D-Bus 정책·transaction별 시작/정지/권한 회수 경로는 구현했으며, 실제 PID1/cgroup의 SYSTEM 검증과 전체 controller 연결은 남아 있다.

native image는 Noble `rauc=1.11.3-2` binary package와 실제 일반 binary 파일을 검사하고, 전역 제어를 여는 upstream `rauc-service` package를 거절한다. test tool은 공식 deb의 크기·SHA256을 확인해 pytest 임시 경로에만 추출하며 전역 package나 service를 설치하지 않는다. 임시 인증서와 실제 CMS/verity, frozen 설치 경로 실행 시험은 제품 인증서·ARM artifact·실물 설치 수용을 대신하지 않는다.

새 factory는 root별 `os-media.json`에 전체 GPT snapshot을 보관하고 kernel command line에 `rauc.slot=a/b`를 명시한다. 공통 `os-update/state.json`은 schema 1, committed A/release, pending null, failed_versions 빈 목록으로 초기화하며 RAUC/staging 디렉터리는 root 0700이다. 누락을 정상 idle로 추측하지 않는다. 현재의 순수 metadata 변환은 검증된 factory A의 fstab·descriptor·media snapshot·cmdline 네 파일만 받아, 기존 카드의 비활성 슬롯 UUID와 mount 배치로 렌더링한다. GPT·data·bootstrap을 쓰거나 후보 코드를 실행하지 않는다. 실제 installer의 서명 검증·장치 수용·write/재수용 연결은 별도다.

media admission은 현재 descriptor·mount·kernel RAUC slot, 전체 디스크 handle의 block identity, 실제 GPT 양쪽 사본과 snapshot을 대조한다. 여섯 kernel partition의 `start`·`size`도 GPT와 같아야 하며, 비활성 root/boot가 PID1이나 호출자 mount view에 남아 있으면 거절한다. capture 결과는 이후 쓰기 권한을 대신하지 않으며 실제 파괴 경계에서 다시 확인해야 한다.

독립 검토와 실제 Linux 읽기 시험에서 sysfs text attribute의 표시 크기를 작은 일반 파일처럼 취급하면 정상 장치를 거절함을 확인했다. [Linux v6.8 구현](https://raw.githubusercontent.com/torvalds/linux/v6.8/fs/sysfs/file.c)은 이 크기를 PAGE_SIZE로 게시한다. sysfs 안의 소유권·형식이 맞는 attribute만 별도 helper로 최대 65바이트 읽어 실제 64바이트 제한을 확인한다. 저장된 JSON·서명 metadata의 엄격한 일반 파일 크기 검사는 유지한다. page 크기를 재현하는 모델과 실제 sysfs 회귀를 함께 두며, 이는 Pi 부팅이나 block 쓰기 수용이 아니다.

OS journal은 공통 store의 기존 schema 1을 엄격하게 읽는다. 누락·중복 키·손상·예상 밖 필드나 넓은 권한을 idle로 초기화하지 않는다. 단일 link인 0600 state와 root 0700 디렉터리를 요구하고, 긴 OS transaction lock과 다른 짧은 비차단 state flock 안에서 fsync·replace·parent fsync로 게시한다. transaction/source boot/trial boot, 기존 카드 layout digest, 검증된 bundle·image metadata와 health digest를 유지한다. 단계는 PREPARED→INSTALLING→INSTALLED→VERIFIED→ARMED→TRIAL→HEALTHY→COMMIT_INTENT이며 역행·건너뛰기·다른 부팅의 health를 거절한다. 같은 상태 객체라도 lock context 종료 또는 게시 중 오류 뒤에는 다시 쓸 수 없다. parent fsync 오류가 성공한 rename 뒤에 생길 수 있으므로 메모리의 이전 상태로 계속 쓰지 않고 다시 열어 디스크를 확인한다. 이 시험은 실제 파일 IO와 오류 주입이며 전원 차단 수용이 아니다.

상태 helper는 firmware·motion·health의 관측 권한을 대신하지 않는다. commit owner가 같은 trial의 GOOD_ACK·실제 health·autoboot 게시/readback을 확인한 뒤에만 journal commit을 호출한다. source 복귀 관측 뒤 실패 버전을 기록해 자동 재시도를 막고, COMMIT_INTENT의 실패는 commit owner가 실제 old/new 설정을 읽어 해소해야 한다. 실패 이력은 최대 128개이며 넘치면 쓰기를 거절하고 사람의 점검을 요구한다. 관측 owner와 실제 daemon/boot controller 연결은 아직 남아 있다.

native activate·명시적 rollback은 native release.lock 안에서 영속 pending fence를 확인한다. OS owner도 같은 짧은 lock 안에서 pending을 게시해야 경합 사이로 native 변경이 들어오지 않는다. OS owner가 CORE를 재시작하는 동안 이 lock을 유지하지 않는다. claim TTL이 끝나도 pending은 유효하며 자동 updater의 resume·apply·최종 precheck도 journal 복구·SDK inverse/sync 전에 차단한다. ABI 2를 주장하는 서명된 SDK라도 pending fence의 필수 파일을 빼면 거절한다. boot recovery는 별도 경로로 남겨 maintenance 상태에서도 기존 CORE 복구가 가능하게 한다. legacy MBR·protocol 1과 최소 두 파일짜리 standalone verifier 경로는 유지한다.

firmware adapter는 [공식 autoboot 문서](https://www.raspberrypi.com/documentation/computers/config_txt.html#autoboot-txt)의 raw big-endian u32 `partition`·`tryboot`를 읽고 descriptor·kernel RAUC slot·boot ID와 대조한다. `/proc/device-tree` alias는 실제 kernel sysfs tree만 허용한다. factory assembler와 callback은 같은 두 canonical autoboot 표현을 쓰며 중복·추가 설정을 추측하여 수정하지 않는다. 설치·trial callback은 bootstrap을 쓰거나 reboot를 실행하지 않는다.

`set-primary`는 같은 source boot의 VERIFIED/ARMED journal, 현재 claim, 같은 transaction·manifest·layout에 결속된 root 전용 arm permit을 요구한다. permit은 monotonic 기준 15초 안의 유효기간으로 제한하며 실제 장치를 다시 capture한 뒤 RAUC 하위 디렉터리에 arm 기록만 남긴다. 실제 policy·inhibition·watchdog·60% battery를 검사해 이 permit을 만드는 controller는 별도다. source boot가 바뀌면 이전 arm으로 재시작하지 않는다. 현재 trial도 firmware flag·target·journal·arm 기록이 일치해야 primary로 보고한다. 정상 reset은 기존 autoboot default로 남는다.

`set-state good`은 현재 transaction·boot·manifest에 묶인 ACK만 기록한다. 설치 전 good과 trial good은 boot ID로 구분하며 어느 쪽도 기본 슬롯을 바꾸지 않는다. bad는 arm을 해제한다. commit owner는 동일 boot의 실제 health와 GOOD_ACK를 확인해야 한다. callback과 commit owner는 RAUC 하위 디렉터리의 짧은 boot lock을 공유하며 state lock을 잡은 채 callback을 부르지 않는다. 실행 파일은 `-I` Python과 frozen helper 경로를 쓰고, mutable SDK를 손상시킨 설치 경로에서 실제 CLI의 preboot good을 검증한다. 이 결과는 모델 DT/mount이며 Pi firmware 관측이나 commit/powercut 수용이 아니다.

media capture는 현재 namespace의 `/dev/block/<major>:<minor>`를 열고 기존 block 형식·rdev·GPT 검사를 유지한다. [Linux proc link lookup](https://raw.githubusercontent.com/torvalds/linux/v6.8/fs/proc/base.c)은 `/proc/1/root` 접근을 ptrace 검사로 보호하므로, 장치 검증을 위해 그 우회 경로를 따르거나 daemon에 ptrace 권한을 더하지 않는다. PID1 mountinfo 읽기는 유지한다([kernel 구현](https://raw.githubusercontent.com/torvalds/linux/v6.8/fs/proc_namespace.c)). 실제 제한된 service의 namespace/cgroup 검증은 SYSTEM 단계에 남는다.

commit 뒤 같은 boot의 DT `tryboot=1`이 남아도 현재 슬롯·영속 default·committed 슬롯이 모두 같으면 정상 조회를 허용한다. pending을 지운 뒤 이 상태를 미등록 trial로 오인해 다시 HOLD하지 않는다. 다른 슬롯의 미등록 trial은 계속 거절한다. 이는 별도 commit owner를 모델로 수행한 전이 회귀이며 실제 firmware commit 수용이 아니다.

`rosy-os-rauc.service`는 protocol 2 이미지에만 설치하는 static unit이며 enabled/자동 D-Bus activation을 만들지 않는다. 기본 DeviceAllow는 비어 있다. private mount namespace·ProtectSystem=strict와 RAUC runtime/common 하위 디렉터리 두 곳의 쓰기 허용을 사용하고 loop/verity용 권한과 제한된 capabilities만 지정한다. root만 RAUC bus name을 소유하거나 호출하도록 [D-Bus policy](https://dbus.freedesktop.org/doc/dbus-daemon.1.html)에서 default deny/user root allow를 지정한다. unit·policy·실행 helper는 frozen closure에 포함하고 앱 SDK sync/backup이 이 unit 및 drop-in namespace를 쓰지 못하게 한다.

installer는 같은 source boot의 INSTALLING 상태·claim·검증된 bundle/image/manifest·실제 media를 대조하고, frozen 원본과 live unit/policy가 같은지 확인한다. daemon 정지를 확인한 뒤 root-only runtime metadata·config·request와 장치 drop-in을 게시한다. ExecStartPre는 서명·실제 media·request를 다시 확인한다. manager의 FragmentPath/DropInPaths·ProtectSystem·DevicePolicy/DeviceAllow·ReadWritePaths를 대조하고 실제 raw SD 쓰기를 요청하기 직전에 caller의 필수 authorize 함수를 실행한 뒤 claim/pending/media를 다시 확인한다. 이 함수에 실제 enabled/Hold·withdrawal·fresh idle/battery·no-motion 검사를 공급하는 controller는 별도다.

큰 bundle 검증의 SD 읽기 시간을 고려해 startup 검증에는 최대 10분, 같은 transaction request에는 최대 15분을 허용한다. request 유효기간을 최종 policy의 freshness로 사용하지 않는다. 느린 검증 뒤 필수 authorize가 실행되어야 한다. 설치 후 전체 이미지 읽기와 fsck까지 포함해 client는 최대 45분, daemon은 최대 50분으로 제한하며 종료 시 control group을 함께 정지한다. 정지가 확인된 뒤에만 현재 호출이 만든 파일을 검증·삭제하고 권한을 회수한다. unknown 파일·mount·내용 변경이나 정지 실패는 HOLD로 남긴다. 동일 boot의 검증된 runtime 회수는 claim 만료 후에도 가능하며 새 설치를 시작하지 않는다. 아래 current-code post-handler가 metadata rebase를 수행하며 boot arm/commit은 별도다.

서명된 JSON은 staging에도 원본 bytes로 게시한다. verifier가 허용한 UTF-16 JSON을 실제 Ed25519/CMS로 검증한 반례에서 ASCII 재인코딩 실패를 확인한 뒤 atomic IO에 bytes 게시를 추가했다. 기존 UTF-8 문자열 writer의 fsync/권한/rename 순서는 유지한다. frozen preflight를 poisoned mutable SDK 없이 실행하는 실제 crypto와 systemd의 offline parser 시험은 SOURCE 증거이며 실제 daemon/PID1·cgroup deny·block 설치 수용은 아니다.

`os_update_policy.authorize`는 기존 native updater의 공통 enabled/Hold·seal·network·idle 판정을 읽기 전용으로 재사용한다. OS 배터리는 충전 여부와 관계없이 유한한 60~100%와 bool 충전 상태를 요구한다. 현재 transaction의 live claim, 같은 source boot의 pending을 확인하고 12초 간격의 서로 다른 fresh status 두 번을 읽은 뒤 공통 정책·claim·pending을 다시 확인한다. 정책·journal·history는 쓰지 않으며 CORE 부재를 면제하지 않는다. native의 기존 40%/충전 예외는 변경하지 않는다. 실제 배포 controller의 호출과 signed withdrawal 대조는 별도다.

protocol2의 frozen motion guard는 storage admission 뒤 CORE/I/O/navigation보다 먼저 pending과 firmware/default/committed 일치를 읽는다. pending이면 root 전용 `/run/rosy-os-update/motion.env`에 drive=false를 남긴다. I/O의 OS 소유 최종 EnvironmentFile은 operator runtime.env 뒤에 적용하며 매 I/O 재시작 전 privileged precondition으로 복원한다. navigation은 시작할 때마다 frozen ExecCondition으로 pending 부재를 요구한다. 읽기 실패는 false를 유지하고 guard 실패로 runtime 시작을 막는다. pending이 없는 일치한 committed boot에서만 자신이 만든 false 파일을 지우며 operator 설정은 쓰지 않는다. commit 후 같은 boot에 남은 tryboot flag만으로 주행을 계속 막지 않는다.

RAUC unit은 guard를 요구하고 I/O·navigation과 Conflicts/After를 지정해 둘의 정지 뒤 시작한다. ExecStartPre는 pending과 false 파일을 읽기 전용으로 확인한 다음 서명·media 검사를 실행한다. daemon은 두 RAUC 디렉터리 밖에 쓸 수 없으므로 false 파일 게시·복원은 controller와 early/I/O guard가 맡는다. 앱 SDK sync/backup은 guard unit과 CORE/I/O/navigation의 전체 drop-in namespace를 쓰지 못한다. 이 source 경로는 실제 PID1의 정지 순서·EnvironmentFile 효과·모터 torque 수용을 증명하지 않으며 controller의 상태 게시·재시작·health/commit 소유권을 대신하지 않는다.

protocol2의 sysinit drop-in은 `DefaultDependencies=no`인 deadline timer를 local-fs 완료 전에 시작한다. 부팅 기준 180초, 정확도 1초의 timer와 독립 oneshot은 storage/projection/CORE를 요구하지 않는다. 먼저 raw DT tryboot를 읽어 정상 부팅이면 공통 상태를 읽거나 재부팅하지 않는다. trial이면 별도 child에서 firmware/default/committed 상태를 최대 3초 확인한다. pending이 없고 현재 슬롯·default·committed가 일치하면 같은 boot의 tryboot=1도 유지한다. 미확정·손상·timeout이면 `systemctl --no-block reboot`로 정상 재부팅을 요청하며 강제 재부팅이나 새 tryboot를 요청하지 않는다. timeout child를 kill한 뒤 다시 wait하지 않아 공통 저장소 I/O가 parent를 붙잡지 않게 한다. flag 자체가 없거나 모호하면 추측하지 않고 HOLD한다.

deadline helper/timer/service/sysinit 연결은 frozen closure에 포함하고 protocol2에만 설치한다. 앱 sync/backup은 deadline unit과 sysinit drop-in namespace를 쓰지 못한다. 실제 3초 지연 child·poisoned mutable SDK의 frozen CLI·offline systemd parser는 SOURCE 증거다. 실제 PID1의 timer 활성화/재부팅, 커널의 uninterruptible I/O, watchdog handoff와 전원 차단 복귀를 대신하지 않는다. commit owner의 timer 취소와 kernel/PID1 watchdog 설정·실제 지원 확인은 남아 있다.

새 protocol2 boot A/B의 config.txt 끝에는 unconditional `[all]`의 `kernel_watchdog_timeout=180`을 추가한다. 기존 overlay는 유지하고 입력·출력 모두 64KiB 안에서 검증한다. [Raspberry Pi 공식 설명](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/config_txt/boot.adoc#kernel_watchdog_timeout)에 따라 kernel open_timeout handoff를 요청하며 EEPROM은 쓰지 않는다. OS 소유 manager config는 `/dev/watchdog0`, RuntimeWatchdogSec=10s, RebootWatchdogSec=10s를 지정한다. [systemd255 설정 parser](https://github.com/systemd/systemd/blob/v255/src/core/main.c)는 계획에 적힌 ShutdownWatchdogSec를 RebootWatchdogSec의 obsolete alias로 처리하므로 현대 이름으로 동일한 shutdown 단계 설정을 적용한다. kernel watchdog 설정만으로 실제 지원을 주장하지 않는다.

`os_update_watchdog.admit`는 normal source boot에 묶인 읽기 전용 관측이다. 저장된 boot cmdline에 없는 `watchdog.open_timeout=180`이 실제 proc cmdline에 하나만 나타나는지, kernel open_timeout과 Broadcom watchdog identity/state/10초 timeout이 맞는지 확인한다. 실제 PID1의 Version255·Runtime/Reboot watchdog 값·장치를 읽고 같은 boot의 trusted PID1 journal에서 hardware open과 10초 enable의 순서를 요구한다. [systemd255 watchdog 구현](https://github.com/systemd/systemd/blob/v255/src/shared/watchdog.c)은 장치를 enable한 뒤 running timeout 로그를 기록한다. 나중 실패/다른 timeout·손상·부족한 증거는 HOLD한다. 이 관측은 /dev/watchdog을 열지 않아 상태를 바꾸지 않는다. 실제 ARM 기체 관측과 controller의 최종 arm 연결은 별도이며 unknown은 stage-only로 처리해야 한다.

protocol2 root에는 apt-daily/apt-daily-upgrade timer와 service, unattended-upgrades.service가 os-slot descriptor 존재 시 시작하지 않는 OS 소유 조건을 둔다. 수동 apt 명령을 실행하거나 OS 밖의 package manager를 제어하지 않는다. 공통 frozen no-apt 정책을 다섯 대상에 설치하기 위해 asset registry는 source/target pair 목록으로 관리하며 configure와 daemon의 live/frozen 검사는 같은 목록을 사용한다. watchdog manager config·apt unit namespace는 앱 sync/backup에서 제외한다. actual systemd condition 평가와 poisoned mutable SDK의 frozen admission은 SOURCE이며 실제 부팅의 apt 비활성/하드웨어 reset 수용은 아니다.

설치 후 검증은 [RAUC1.11.3 system post-handler](https://github.com/rauc/rauc/blob/v1.11.3/src/install.c)가 실행하는 고정 frozen `rosy-os-finalize`에서 수행한다. incoming manifest의 hook은 계속 거절한다. 인증된 image size 범위의 inactive root/boot bytes 전체를 image hash와 대조하고 private namespace·현재 GPT·mount device/options를 확인한다. RO mount에서 native factory의 OS metadata baseline·현재 Ed authority·서명·inventory·Python runtime pin·AST boot ABI를 검증한다. 실행 중인 root 검증과 분리한 `verify_payload`를 재사용하며 enrollment·signature repair·candidate SDK 실행은 하지 않는다. pointer store를 별도 lazy helper로 옮겨 기존 두 파일만 사용하는 독립 verifier도 유지한다.

현재 코드가 읽은 factory-A metadata를 실제 카드의 반대 슬롯으로 변환하고, unmount/fresh capture 뒤 RW mount에서 fstab·os-slot·os-media·boot cmdline의 네 파일만 보정한다. sync/unmount·block flush·read-only fsck 뒤 다시 RO mount하여 정확한 metadata·native factory·원래 signature bytes를 확인한다. 정상 source의 default와 GPT/data는 바꾸지 않는다. readonly/noexec/nosuid/nodev와 device·namespace 검사는 생략하지 않는다. 기본 data-directory의 central RAUC status와 resize=false를 사용하므로 [고정 image handler](https://github.com/rauc/rauc/blob/v1.11.3/src/update_handler.c)의 원본 이미지 읽기 비교가 가능하다. frozen staging은 이 entrypoint에도 실행 모드755를 명시한다.

모든 target을 unmount하고 workspace를 회수한 뒤에만 common RAUC 하위에 transaction/source boot/manifest/layout/target/factory/metadata digest가 결속된 private receipt를 fsync 게시한다. 설치 client 성공만으로 installed를 반환하지 않으며 receipt가 없거나 기존 receipt를 재사용하려 하면 HOLD한다. 이 receipt와 실제 성공 결과를 받은 controller가 INSTALLED/VERIFIED를 게시해야 한다. interrupted INSTALLING의 receipt만으로 client 성공이나 arm 권한을 추측하지 않는다. metadata가 부분 보정된 경우에도 원본 hash가 일치한다고 가정해 재개하지 않는다.

daemon MainPID=0만으로 자식 writer가 끝났다고 판단하지 않는다. stop 전후와 canonical unit cgroup의 [cgroup2 populated](https://docs.kernel.org/admin-guide/cgroup-v2.html#un-populated-notification)가 모두 0이거나 사라진 경우에만 권한을 회수한다. live child·unknown hierarchy는 HOLD로 runtime을 보존한다. 같은 boot의 인증된 request와 전체 cgroup 종료를 확인한 복구는 known root/boot의 private·unmounted·빈 workspace만 지운다. unknown 파일과 mounted tree를 재귀 삭제하지 않는다. 실제 kernel namespace/cgroup/RAUC/fsck 수용은 SYSTEM 단계이며, signed-candidate 비실행·네 파일 I/O·양방향 전이·frozen 실행의 SOURCE 시험과 구분한다.

시범 부팅의 `os_update_health.check`는 TRIAL·target slot·새 boot ID·보존된 source default·motion fence를 먼저 확인한다. 공통 enabled/Hold/seal/network/claim 정책과 알려진 60–100% 배터리 조건은 source와 trial에서 공유하되 source admission은 trial에서 계속 거절한다. trial은 12초 간격의 서로 다른 fresh idle CORE 기록을 요구한다. source 전용 watchdog admission과 별도로 같은 boot의 firmware/kernel/PID1 관측을 재사용하며 두 health 관측 사이에 결과가 달라지면 거절한다.

시범 root의 signed factory·inventory·Python pin·AST 계약과 current pointer를 검증하고, source finalizer가 남긴 transaction/layout/manifest/factory receipt를 대조한다. source receipt reader의 실제 source-boot 조건은 유지하며 별도 bound decoder를 trial owner가 사용한다. 현재 projection/boot/slot을 확인한 뒤 navigation을 정지하고 cgroup2 전체 종료를 확인한다. I/O는 frozen OS guard와 signed factory unit bytes, effective drop-in 및 마지막 false EnvironmentFile을 확인한 뒤 재시작한다. CORE/I/O의 InvocationID·MainPID·상태가 두 관측 사이에 바뀌면 거절한다. `/api/v1`의 local HTTP/TLS readiness는 기존 wait-core-ready 계약(200–499)을 사용하며 redirect/proxy를 따르지 않는다. HTTP 응답만으로 health를 인정하지 않고 fresh idle CORE samples도 필요하다.

health는 bootstrap/state phase/ACK를 쓰지 않는다. 성공한 boot/transaction/services/projection/factory/watchdog/samples를 common RAUC 하위 private receipt로 fsync 게시하고 readback한다. CLOCK_BOOTTIME 기준 165초 이후에는 게시·소비하지 않으며 receipt 유효기간은 30초다. 잘못된 nested schema와 PID, 다른 boot 또는 만료된 receipt는 HOLD한다. commit owner는 receipt의 정확한 바이트 digest·HEALTHY·같은 trial의 GOOD_ACK·운영자 조건·실제 서비스 상태를 다시 결속한다. 장기 COMMIT_INTENT 복구는 일반 health의 same-boot expiry를 우회하는 flag로 구현하지 않고 별도 복구 역할로 처리한다. frozen controller와 부팅 서비스가 이 helper 및 일반 trial 실패 fallback을 호출하며 새 OS release 선택·staging feed와 실제 SYSTEM 수용은 남아 있다.

`os_update_commit.commit`은 callback과 같은 boot lock 안에서 실제 healthy trial·보존된 source default·현재 claim/정책을 확인한다. health의 live projection/factory/watchdog/서비스/API와 정확한 private receipt bytes SHA, HEALTHY에서 발행한 같은 trial의 GOOD_ACK를 대조한다. fresh GPT/boot identity를 확인하고 transaction/source/trial boot/target/OS release/manifest/layout/health SHA를 결속한 private `commit.json`을 먼저 fsync한다. 그 뒤 짧은 state lock으로 COMMIT_INTENT를 게시한다. 느린 intent fsync 동안 정책·claim·health TTL·media가 바뀔 수 있으므로 다시 확인한 뒤에만 canonical autoboot를 atomic replace/file fsync/parent fsync/readback하고 COMMITTED를 저장한다. state lock을 잡은 채 systemd/API/callback을 기다리지 않는다. 확정 뒤 OS 소유 false 파일을 제거하고 independent deadline timer/service를 멈추며 자신의 완료 transaction claim만 해제한다.

명시적 `recover`는 원래 exact-byte health proof·GOOD_ACK·durable intent·actual GPT/boot/default를 대조한다. 이미 새 default가 정확히 기록되고 현재 target이면 이전 trial의 의도를 완료할 수 있다. 이는 새 boot의 fresh health로 취급하는 경로가 아니다. 이전 default가 보존되고 새 정상 source boot이면 별도 `abandon_commit`으로 failed version을 기록하며 재시범 부팅하지 않는다. 같은 trial/이전 default는 일반 fresh admission을 통과해야 재시도한다. 알 수 없는 bootstrap·불일치 proof는 pending과 inhibition을 보존하고 offline repair가 필요하다. COMMITTED 뒤 cleanup 전에 중단된 경우에도 commit.json으로 같은 transaction의 claim만 회수할 수 있다. userspace가 실행되기 전 손상이나 실제 FAT 전원 차단 안전성을 이 source 시험이 증명하지 않는다.

부팅 파일을 교체할 때 기존의 안전한 mount-derived mode를 보존한다. Linux 6.8의 [FAT mode 검증](https://github.com/torvalds/linux/blob/v6.8/fs/fat/file.c)은 mount mask가 정하는 read/execute bits를 임의 chmod로 바꾸는 요청을 거절한다. 기본 VFAT의 0755 파일을 generic 0644로 바꾸려는 source 경로는 해당 kernel 계약 모델에서 실패했다. autoboot와 inactive boot cmdline의 두 경계만 기존 mode를 사용하고 special/group-write bits를 거절한다. ext4 root/data metadata의 0644/0600 규칙은 바꾸지 않는다. 실제 mounted FAT와 전원 차단 수용은 disposable SYSTEM·DEVICE 단계에서 확인해야 한다.

`os_update_controller.start`는 common OS transaction flock과 기존 native updater `.run.lock`을 잡고 정상 source boot에서만 새 transaction을 시작한다. same-transaction claim은 3시간으로 갱신하며 bundle/CMS·현재 signed native runtime·Python pin·projection·실제 CORE cwd·서비스·API·watchdog·두 idle samples를 확인한다. 다른 native release가 바뀌지 않았음을 short native release lock 안에서 확인한 뒤 pending을 게시하고 false guard와 navigation/I/O 전체 cgroup 정지를 적용한다. state/native release lock을 잡고 service/callback을 기다리지 않는다. RAUC client 성공과 source finalizer의 bound receipt가 모두 맞아야 INSTALLED/VERIFIED로 전진한다. false 환경의 observational I/O를 다시 시작하고 source health·짧은 arm permit·callback·ARMED를 거쳐 단 한 번의 firmware tryboot reboot를 요청한다. pending 동안 claim을 남겨 다른 유지보수와의 충돌을 막는다.

`resume`는 actual firmware/source/trial boot를 읽는다. 새 trial에서 TRIAL → health receipt exact-byte SHA의 HEALTHY → GOOD_ACK → commit을 실행한다. intent 이후의 실패는 복구에 필요한 GOOD_ACK를 bad로 덮지 않는다. 다른 정상 source boot로 돌아온 실패 후보는 writer 종료를 확인하고 failed version으로 기록하며 다시 arm하지 않는다. 같은 source boot의 interrupted INSTALLING도 RAUC runtime과 전체 writer 종료를 확인해 실패 처리하며 receipt만으로 client 성공을 추측하지 않는다. INSTALLED 이후 같은 source boot만 검증을 이어갈 수 있다. pending 게시·제거는 native release lock과 짧은 state lock을 공유한다. 기존 [CORE가 예전 release에 남는 교훈](../solutions/runtime-errors/payload-activation-left-core-on-the-old-release-2026-10-01.md)에 따라 source preflight는 실제 cwd를 검증하고 불일치를 조용히 재시작해 숨기지 않는다.

ABI2 root에만 frozen `rosy-os-update.service`와 timer/sysinit 연결을 설치한다. 부팅 10초 이후 및 inactive 60초 간격으로 pending 작업을 재개하며 storage/guard/projection/native recovery/CORE/I/O 뒤에서 실행한다. I/O·native recovery 실패가 trial fallback 자체를 막지 않도록 storage만 필수 dependency로 둔다. 독립 180초 deadline은 controller를 기다리지 않는다. unit은 검증된 runtime.env를 상속하고 strict filesystem 안에서 OS state·bootstrap·own runtime/lock만 쓴다. 실제 CORE cwd 확인을 위한 read/ptrace 권한과 MMC raw-read만 허용하며 raw 설치 쓰기는 별도 RAUC unit의 inactive 대상 권한으로 제한한다. mutable SDK sync는 새 controller service/timer 및 sysinit drop-in을 교체할 수 없다. observational I/O 재시작 뒤에는 native runtime의 기존 `IO_SETTLE_S=20`을 재사용한 다음 샘플을 검증한다. trial은 이 대기 직후에도 boot deadline margin을 재검사하며 TTL을 늘리지 않는다. 현재 timer는 pending 재개와 staged install caller를 연결하며 새 release 자동 선택·download/rollout feed는 별도 source 작업으로 남는다.

확정 뒤 controller는 자기 commit.json의 target/release/trial boot ID가 현재 committed 상태와 일치하는 경우에만 정상 reboot를 한 번 요청한다. 이는 같은 boot에 남은 tryboot 표식을 다음 source 업데이트 전에 정리하고, false 환경으로 시작한 I/O에 operator의 설정을 다시 적용하기 위한 단계다. 다른 boot ID에서는 같은 요청을 반복하지 않으며 intent 없이 committed tryboot 표식만 있는 경우도 재부팅하지 않는다. 독립 deadline의 committed-boot 판정과 일반 source의 정상 부팅 조건을 완화하지 않는다. 실제 firmware 표식 전환과 두 번의 부팅 수용은 DEVICE에서 확인해야 한다.

이 결정과 소스 시험은 native ARM64 이미지, SD 기록, 부팅·업데이트·복귀 수용을 대신하지 않는다.
새 이미지의 서명·전체 readback까지 끝낸 engineering SD로 첫 실물 시험을 진행한다.
production BUILD_GO는 실물 수용까지 계속 거절한다. EEPROM 자동 쓰기는 포함하지 않는다.

관련 결정: [D-387](D-387-robot-updates-operator-approved-rollout.md),
[D-879](D-879-signed-gpt-media-layout.md), [D-881](D-881-ab-device-state-admission.md).
