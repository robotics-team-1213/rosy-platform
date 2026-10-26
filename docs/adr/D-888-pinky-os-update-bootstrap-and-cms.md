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

서명 검사에 사용하는 sealed slotless `bootloader=noop` 설정은 `info` 전용이다. 설치 설정은 fresh media capture로 현재 카드의 장치를 정하고 비활성 두 partition에 후보가 들어가는지 확인하여 별도로 생성한다. `bootloader=custom`, `activate-installed=false`, rootfs와 child boot의 A/B 묶음, 공통 RAUC data-directory를 사용한다. 동적으로 생성하는 DeviceAllow는 실제 daemon에 적용할 입력이며 비활성 root/boot rw와 parent r, loop/verity 장치만 포함한다. 설정 생성 자체는 설치 권한이 아니다. 실제 daemon의 root-only D-Bus·namespace·cgroup 적용과 transaction/boot controller 연결·SYSTEM 검증은 아직 남아 있다.

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

이 결정과 소스 시험은 native ARM64 이미지, SD 기록, 부팅·업데이트·복귀 수용을 대신하지 않는다.
새 이미지의 서명·전체 readback까지 끝낸 engineering SD로 첫 실물 시험을 진행한다.
production BUILD_GO는 실물 수용까지 계속 거절한다. EEPROM 자동 쓰기는 포함하지 않는다.

관련 결정: [D-387](D-387-robot-updates-operator-approved-rollout.md),
[D-879](D-879-signed-gpt-media-layout.md), [D-881](D-881-ab-device-state-admission.md).
