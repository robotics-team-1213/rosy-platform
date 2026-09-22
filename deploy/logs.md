# deploy logs

추가만 한다. 형식: [module harness 설계](../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [Device 검증 계획](../docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md)과 `git log -- deploy`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the deploy harness pilot
- 변경: `progress.md`, `logs.md`, 생성 `index.md` 추가. `AGENTS.md`에 기록 위치와 작업 순서 연결
- 증거: `python -m pytest test -q` 835 passed, 12 skipped (Windows + Git Bash/OpenSSL PATH, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. 기존 SOURCE/LOCAL GO, ARTIFACT/DEVICE HOLD를 스냅샷으로 옮김
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-15 · uncommitted · docs(harness): state excluded gates and rerunnable source evidence
- 변경: 리뷰 반영. ROS-SIM·FIELD를 N/A로 명시(물리 구동은 소비 모듈 gate), SOURCE에 재실행 명령 추가, `last_verified.commit`을 `uncommitted`로
- 증거: 미실행 — 기록 형식만 변경
- gate 변화: 없음 (누락 키를 N/A로 명시)
- 결정: 없음
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(host-agent): structured network status, set_mode, connect (D-124)

- 변경: network.status 를 D-26 필드로 파싱. network.set_mode, network.connect 허용. PSK는 감사/응답에서 제거
- 증거: `python -m pytest test/test_host_agent.py -q`
- gate 변화: 없음. DEVICE HOLD 유지
- 결정: D-124
- 교훈: 없음

## 2026-09-21 · 1acb41a · feat(deploy): fail-closed Pinky commissioning

- 변경: G0-G5 순차 세션, 실제 release/readback JSON 유도, 증거 SHA-256,
  lock/CAS 원자 저장, SSH/console 런북, 유선/무선 인터페이스 검증 추가
- 증거: `python -m pytest test -q` -> 1001 passed, 13 skipped; 집중 169개,
  Python/Bash/PowerShell 구문 및 `git diff --check` 통과
- gate 변화: SOURCE/LOCAL GO 갱신. ARTIFACT/DEVICE는 signed ARM64 bundle과
  실제 Pinky Pro readback 전까지 HOLD, FIELD는 N/A 유지
- 결정: 없음
- 교훈: G0-G2는 작업자 요약이 아니라 stage manifest/install/readback 원문에서
  유도하고, G3-G5 미측정 템플릿은 검증을 통과하지 못해야 한다

## 2026-09-21 · c2bb799 · feat(release): native ARM64 unsigned payload builder

- 변경: native Linux aarch64/ARM64 Docker daemon/clean revision/digest-pinned ROS base를 강제하고 `core`/`io`를
  Buildx로 빌드한 뒤 linux/arm64, OCI revision label, immutable image ID를 검사한다.
  검사한 image ID로 Docker-save archive, runtime config, provenance, manifest를 원자적으로 만들며 private
  signing key는 받지 않는다. 기존 offline packager와 publication JSON 검증으로 연결했다.
- 증거: builder/publication/image/release/runtime/commissioning 집중 `516 passed, 8 skipped`;
  전체 `1035 passed, 13 skipped`;
  py_compile, flake8, `git diff --check` 통과. Windows 실제 CLI는
  `BUILD_HOST_OS`로 종료하고 payload를 만들지 않았다.
- gate 변화: SOURCE만 갱신. ARTIFACT는 native aarch64 실행과 실제 offline signature,
  DEVICE는 Pinky 설치/readback 전까지 HOLD다.
- 교훈: full SD-image 파이프라인의 미구현 상태와 update bundle builder를 구분하되,
  어느 쪽도 x86/QEMU 산출물을 G0 증거로 승격하지 않는다.

## 2026-09-21 · 6f6c515 · feat(deploy): capture Pinky connection evidence

- 변경: Windows peer verifier에 bounded optional batch SSH, API port/timeout, atomic
  no-overwrite JSON evidence를 추가했다. 성공은 선택 interface의 SSH 주소와 API/dashboard,
  실패는 stable code와 HOLD만 기록하며 원격 stderr·credential은 evidence에 넣지 않는다.
- 증거: 실제 PowerShell+fake SSH+loopback HTTP 시험을 포함한 집중 `81 passed`;
  전체 `1041 passed, 13 skipped`; PowerShell parser, py_compile, flake8,
  `git diff --check` 통과. 미연결 `192.168.4.1`은 4초 내 `SSH_ROUTE/HOLD`를 기록했다.
- gate 변화: SOURCE/LOCAL만 갱신. 연결 GO도 G0 artifact, DEVICE, FIELD를 대신하지 않는다.
- 교훈: 장치 미연결을 콘솔 timeout으로만 남기지 말고 재실행 가능한 구조화 evidence로
  남기되, 자동 subnet scan이나 host-key 우회로 장치 identity 경계를 약화하지 않는다.

## 2026-09-21 · uncommitted · feat(deploy): make physical G5 mapping evidence-bound (D-144)

- 변경: added an orthogonal `ROSY_NAVIGATION_BACKEND=localization|slam` selector for hardware runtime. SLAM selects its own capability/readiness profile, writable maps mount, and image packages for SLAM Toolbox plus MCAP recording; localization remains read-only and AMCL-based.
- 증거: focused hardware-mapping, commissioning, runtime, navigation, and CORE tests pass on Windows; the development image was built and its packages and launch arguments inspected.
- gate 변화: SOURCE/LOCAL evidence is refreshed. ARTIFACT and DEVICE remain HOLD until a signed native ARM64 bundle is installed and the physical Pinky G0-G5 session produces the required files.
- 결정: D-144.
- 교훈: a mapping API and a SLAM package are insufficient unless the runtime backend, writable persistence, readiness, raw telemetry, generated map pair, and final safe state are all bound into one commissioning session.

## 2026-09-21 · uncommitted · feat(release): export native ARM64 unsigned payloads (D-145)

- 변경: added a manual `ubuntu-24.04-arm` workflow that invokes the existing fail-closed builder, frees ephemeral image layers, archives the unsigned payload and builder JSON, and uploads the archive with SHA-256 for seven days.
- 증거: ARM64 builder plus workflow contracts and the combined root+CORE suite pass locally (`2021 passed, 24 skipped`). Native rehearsal run 35539577735 built on arm64 and exposed 11 environment-sensitive test failures; the two fixtures were made overlay-independent and are rerun after integration.
- gate 변화: SOURCE only. ARTIFACT remains HOLD until the native artifact completes and is signed and verified offline.
- 결정: D-145.
- 교훈: upload the immutable build handoff, not a mutable tag, and make `unsigned` impossible to overlook in both artifact and archive names.

## 2026-09-21 · uncommitted · feat(release): verify unsigned ARM64 handoffs (D-146)

- 변경: D-145 archive의 canonical identity와 외부 SHA-256을 먼저 확인하고, archive path/type/count/size, builder/manifest/provenance, 모든 payload hash, CORE/IO Docker config의 `linux/arm64`를 검증한 뒤에만 handoff를 원자적으로 노출하는 importer를 추가했다. private-key 인터페이스는 없다.
- 증거: importer 단위/CLI/변조/cleanup 테스트 40개, 릴리스·커미셔닝 집중 `370 passed, 2 skipped`, 전체 `1093 passed, 13 skipped` 통과. 실제 `397bb25` artifact도 bounded streaming 경로에서 release/revision/key ID, 17개 payload hash, CORE/IO `linux/arm64`를 확인하고 `signed: false`로 import했다.
- gate 변화: SOURCE/LOCAL만 갱신. importer 결과는 계속 `signed: false`; ARTIFACT와 G0는 승인된 offline 서명 및 publication 검증 전까지 HOLD다.
- 결정: D-146.
- 교훈: 외부 archive checksum 하나는 내부 identity, 경로 안전성, OCI architecture를 증명하지 않는다.

## 2026-09-21 · uncommitted · test(deploy): keep control debug ports out of deploy configs (D-150)
- 변경: test/test_control_launch_boundary.py 에 신규 가드 — deploy/robot 의 모든 텍스트 설정(yaml/service/sh/ps1/py/compose)에서 web_node 실행자명 또는 디버그 포트 28161/28162 를 금지한다. compose 자체는 기존 D-77 검사가 지킨다.
- 증거: python -m pytest test/test_control_launch_boundary.py -q 통과. 변이 증명: compose.yaml 에 28161 주석 삽입 시 적색, 복원 후 초록 확인.
- gate 변화: 없음

## 2026-09-21 · uncommitted · test(deploy): core launches never reference the control stack (D-149)
- 변경: test/test_control_launch_boundary.py 에 코어 쪽 가드 추가 — src/core/core/launch 의 모든 launch 파일이 control 패키지 참조(package='control', apps/control)를 가지지 않는다. launch 파일 개명(rosy_core→core)에도 견디도록 디렉터리 glob 방식.
- 증거: 변이 증명 완료 — rosy_core.launch.py 말미에 package='control' 주석 삽입 시 적색, 복원 후 초록. python -m pytest test/test_control_launch_boundary.py -q 5 passed.
- gate 변화: 없음

## 2026-09-21 · 5dd076c · feat(robot): vendor stock image read-only baseline capture (pre-G0)

- 변경: deploy/robot/capture-vendor-baseline.sh 신규 — vendor 출하 이미지(카드 A)에서 배포판·부트 설정·udev·systemd 자동실행·장치노드·netplan/AP·pinkylib·wifi_setup.sh를 읽기 전용으로 캡처한다. 유일한 쓰기 대상은 증거 OUTDIR이고, i2cdetect 버스 프로브는 PROBE_I2C=1 옵트인이다. 캡처 무결성은 SHA256SUMS.txt로 남긴다.
- 증거: test/test_capture_vendor_baseline.py 5 passed — 변이 증명 완료(OUTDIR 밖 redirect 삽입 시 적색, 복원 후 초록), WSL bash -n 통과. docs/plans/2026-09-21-pinky-device-commissioning-design.md §7이 절차를 소유한다.
- gate 변화: 없음 — 캡처 결과는 pre-G0 참조 평가이며 어떤 gate도 GO로 만들지 않는다. ARTIFACT·DEVICE는 HOLD 유지.
- 결정: 카드 A(vendor 원본 보존) + 카드 B(Rosy OS) 2장 운용을 G0–G5 절차에 명시한다. 캡처 결과는 비밀정보 검토와 scanner 통과 후 필요한 증거만 docs/validation/vendor-baseline-<date>/에 착지한다.
- 교훈: 조사 문서의 UNKNOWN은 실물에서 읽을 수 있는 항목과 그렇지 않은 항목을 갈라 둬야 한다 — 읽기 가능 항목은 절차와 가드로 고정하면 실기 세션 비용이 줄어든다.

## 2026-09-21 · uncommitted · feat(deploy): add operator stationary validation bundle

- 변경: added a one-command Windows collector that binds peer reachability,
  device readback, expected robot identity, and exact release revision into
  no-overwrite GO/HOLD evidence with SHA-256 hashes.
- Safety: the result always carries `motion_authorized: false`; it never changes
  runtime mode or sends a motor command, and GO advances only to G3 sensor-only.
- 증거: focused Python and real PowerShell fake-SSH/loopback tests cover both
  GO and unreachable-device HOLD paths.
- gate 변화: none. DEVICE remains HOLD until the physical Pinky produces the
  same evidence from an installed signed ARM64 release.
## 2026-09-22 · uncommitted · feat(runtime): begin D-161 Ubuntu-native transition

- 변경: Canonical Ubuntu 24.04.5 Raspberry Pi arm64 base URL/SHA-256을 lock에
  고정하고 fail-closed fetch/cache 검증기를 추가했다. native ARM64-only ROSY
  colcon payload builder, 결정적 deb/ROS package inventory와 `ros2 pkg prefix`
  verifier를 추가했다. 제품 runtime은 별도 `rosy-core`/`rosy-io` systemd 사용자,
  closed device policy, CORE-only default target, provisioning/approval gate로 구성했다.
- 증거: fetch 변조/크기/HTTPS/offline cache 계약, payload inventory 계약,
  native systemd 계약과 Ubuntu 24.04 `systemd-analyze verify`를 실행한다. 실제
  ARM64 build와 Pi 실행은 아직 수행하지 않았다.
- gate 변화: SOURCE 계약만 갱신. ARTIFACT, DEVICE, FLEET은 계속 HOLD다.
- 결정: D-161. Docker/Compose는 개발·CI 전용이며 제품 runtime 의존성이 아니다.

## 2026-09-22 · uncommitted · feat(provisioning): connect native rollback and Ubuntu first boot

- 변경: 서명 manifest와 exact payload를 먼저 검사하는 native release activation,
  `current`/`previous` 원자 전환, health 실패 rollback, boot-time journal recovery를
  추가했다. Windows SD writer는 DPAPI Wi-Fi 자격을 명령행에 노출하지 않고 stdin으로
  one-shot bundle을 만들며, 기록한 카드의 FAT32 boot 파티션에만 원자 복사한다.
  Ubuntu first boot는 `rosy-pinky-xxxx`, UUID, DDS 번호, Pi serial, NetworkManager와
  Fleet bootstrap을 적용한 뒤 CORE gate를 연다.
- 증거: native activation/systemd/payload/image 계약 76 passed; SD writer,
  personalization, first-boot, activation/systemd/payload 집중 계약 62 passed.
- gate 변화: SOURCE 구현만 갱신. full Ubuntu image customizer, native ARM64 artifact,
  SBOM·서명·readback 전까지 ARTIFACT/MEDIA/BOOT/DEVICE/FLEET은 HOLD다.
- 결정: D-154와 D-161. 공통 서명 이미지는 device-neutral로 유지하고 장치별 비밀과
  신원은 카드별 bundle 및 첫 부팅 serial binding에서만 적용한다.

## 2026-09-22 · uncommitted · docs(image): plan the flashable `.img.xz` pipeline (D-164)

- 변경: Canonical Pi preinstalled image에서 native ARM64 loop/mount/chroot 방식으로
  ROSY를 설치하고 `.img.xz`를 생성하는 설계와 TDD 실행 계획을 추가했다. offline
  signature를 Windows disk discovery 전에 검증하고 전체 media readback 뒤에만
  MEDIA를 승격하도록 경계를 고정했다.
- 증거: 공식 Canonical/Raspberry Pi 문서 확인과 ADR/plan 계약. 실제 native build는
  아직 실행하지 않았다.
- gate 변화: 없음. ARTIFACT와 DEVICE는 HOLD 유지.
- 결정: D-164. ISO는 제품 artifact가 아니다.

## 2026-09-22 · uncommitted · test(image): freeze the Pinky flashable image contract

- 변경: `inputs.lock.yaml`에 exact `.img.xz` filename, raw disk/partition 계약,
  Raspberry Pi Imager 호환성, 11개 signed sidecar, device-neutral 제외 필드와 ISO 금지를
  추가하고 `test_pinky_flashable_image_contract.py`로 고정했다.
- 증거: D-164 계약과 기존 Ubuntu-native/image pipeline 집중 시험 63 passed;
  `git diff --check` 통과.
- gate 변화: SOURCE 계약만 갱신. 실제 image가 없으므로 ARTIFACT/MEDIA는 HOLD다.
- 결정: D-164 Task 1 완료.

## 2026-09-22 · uncommitted · feat(image): verify Canonical Pi image provenance

- 변경: Canonical `SHA256SUMS`, `SHA256SUMS.gpg`, Ubuntu CD Image Signing 키 지문과
  신뢰 키링을 고정했다. fetcher는 분리 서명과 signer를 먼저 검증하고 정확한 파일명과
  SHA-256 항목을 신뢰한 뒤 cache/download 이미지 바이트를 검증한다.
- 증거: image-pipeline, flashable-image, Ubuntu-native 집중 계약 `67 passed` 및
  `git diff --check` 통과.
- gate 변화: SOURCE만 갱신. 실제 native ARM64 host 검증 전이므로
  `base_image.verified: false`와 ARTIFACT HOLD를 유지한다.
- 결정: D-164 Task 2 source-complete.

## 2026-09-22 · uncommitted · feat(image): add fail-closed Pi image workspace

- 변경: native arm64/root/tool preflight 뒤 Canonical `.img.xz`를 고유한 임시
  workspace에만 풀고, root partition 확장, loop partition 탐색, root→boot mount,
  customizer 실행과 boot→root→loop 역순 정리를 수행한다. 성공할 때만 raw `.img`를
  원자적으로 내보내며 cache 원본은 수정하지 않는다.
- 증거: 가짜 block/mount 도구를 이용한 workspace 계약 `7 passed`; native-host가
  없어 실제 loop device에는 아직 실행하지 않았다.
- gate 변화: SOURCE만 갱신. Task 4 customizer가 없으면 `build-image.sh`가 계속
  fail-closed하므로 ARTIFACT는 HOLD다.
- 결정: D-164 Task 3 source-complete.

## 2026-09-22 · uncommitted · feat(sd): verify signed image before media selection

- 변경: Windows writer가 디스크 조회 전에 Ed25519 `SHA256SUMS` 서명, 전체 파일
  checksum, release/product/board/architecture, 정확한 `.img.xz` 이름과 hash를 검증한다.
- 증거: 실제 임시 Ed25519 key로 정상·변조·identity mismatch를 실행한 writer 계약
  `20 passed`.
- gate 변화: SOURCE만 갱신. 실제 signed image와 물리 write가 없으므로 MEDIA HOLD.
- 결정: D-164 Task 7 writer preflight source-complete.

## 2026-09-22 · uncommitted · feat(image): install native ROSY into Ubuntu Pi image

- 변경: SHA-pinned 공식 `ros2-apt-source` deb를 검증하고 native ARM64 chroot에서
  ROS 2 Jazzy, CycloneDDS, rosdep 의존성, ROSY payload, CORE-only systemd와 first-boot
  overlay를 설치하며 machine identity와 device credentials는 제거한다.
- 증거: customization, payload, systemd, first-boot 집중 계약 `27 passed`; shell syntax 통과.
- gate 변화: SOURCE만 갱신. 실제 ARM64 chroot 실행 전 ARTIFACT HOLD.
- 결정: D-164 Task 4 source-complete.

## 2026-09-22 · uncommitted · feat(image): emit verifiable Pinky image handoff

- 변경: raw image를 분리한 상태에서 ext filesystem 검사 후 bmap과 deterministic
  `.img.xz`를 만들고 raw intermediate를 제거한다. exact image manifest, SPDX SBOM,
  deb/ROS inventory, base/build provenance, report와 unsigned `SHA256SUMS`를 생성한다.
- 증거: finalization/handoff와 기존 image 계약 `64 passed`; shell syntax 통과.
- gate 변화: SOURCE만 갱신. ARM64 실물과 offline signature 전 ARTIFACT HOLD.
- 결정: D-164 Tasks 5-6 source-complete.

## 2026-09-22 · uncommitted · ci(image): build Pinky image on native ARM64

- 변경: manual `ubuntu-24.04-arm` workflow가 정확한 revision의 resolved lock을 만들고
  Canonical provenance 검증부터 native payload/chroot/finalization까지 실행한 뒤 unsigned
  `.img.xz` handoff만 3일 artifact로 업로드한다. private key와 publication은 포함하지 않는다.
- 증거: image/workspace/customization/handoff/writer 전체 집중 계약 `102 passed`, workflow
  YAML parse와 `git diff --check` 통과.
- gate 변화: SOURCE만 갱신. workflow 실실행 전 ARTIFACT HOLD.
- 결정: D-164 Task 8 실행 경로 준비 완료.

## 2026-09-22 · uncommitted · fix(image): pin Pinky Pro native hardware dependencies

- 변경: WiringPi 3.20 ARM64 deb와 Raspberry Pi 5 `rpi_ws281x` source commit을 URL과
  SHA-256으로 고정하고, native ARM64 빌드 전에 검증·설치한다. WiringPi runtime도 같은
  검증 입력으로 Ubuntu rootfs에 설치한다.
- 증거: dependency/customization/image-pipeline 집중 계약 `74 passed`.
- gate 변화: SOURCE만 갱신. ARM64 image workflow와 실제 장치 주변장치 검증 전
  ARTIFACT/DEVICE는 HOLD다.
- 결정: D-165.

## 2026-09-22 · uncommitted · fix(image): probe Pi image filesystems after udev settles

- 변경: loop partition 번호 탐색을 `lsblk`로, 실제 filesystem type 검증을 `blkid`로
  분리하고 partition scan 뒤 `udevadm settle`을 기다린다.
- 증거: 실제 ARM64 run 35648329385에서 Pinky ROS package 12개는 모두 빌드됐고,
  이후 `lsblk` FAT 감지 타이밍에서만 실패했다. workspace/image 집중 계약 `70 passed`.
- gate 변화: 없음. 새 ARM64 image run 전 ARTIFACT는 HOLD다.
- 결정: D-164 workspace 구현 보강.

## 2026-09-22 · uncommitted · fix(image): create the boot mountpoint inside rootfs

- 변경: Ubuntu root partition을 먼저 mount한 뒤 그 안에 `/boot/firmware`를 만들고 boot
  partition을 mount한다. root mount 이전의 host-side 디렉터리가 가려지지 않게 했다.
- 증거: ARM64 run 35649803996에서 partition 탐색·`growpart`·`resize2fs`까지 통과한 뒤
  boot mountpoint 부재를 재현했다. mount-order 회귀 계약을 추가했다.
- gate 변화: 없음. 새 ARM64 image run 전 ARTIFACT는 HOLD다.
- 결정: D-164 workspace mount 순서 보강.

## 2026-09-22 · uncommitted · fix(image): materialize locked Ubuntu apt suites

- 변경: `inputs.lock.yaml`의 Ubuntu `apt_sources` 전체를 target rootfs의
  `rosy-ubuntu.list`로 만든 뒤 apt update를 실행한다. `noble-updates`를 포함해 base image에
  이미 설치된 라이브러리와 개발 패키지 버전을 일치시킨다.
- 증거: ARM64 run 35650918492가 chroot/WiringPi 설치까지 통과한 뒤 누락된
  `noble-updates` 때문에 exact-version 의존성에서 실패했다. source materialization 계약을
  추가했다.
- gate 변화: 없음. 새 ARM64 image run 전 ARTIFACT는 HOLD다.
- 결정: D-161/D-164의 고정 apt 입력을 실행 경로에 연결.

## 2026-09-22 · uncommitted · fix(image): scope target rosdep to the product closure

- 변경: 필수 Pinky Pro ROS package 12개에서 시작해 in-tree 의존성 전이 폐쇄를 계산하고,
  target rootfs의 rosdep은 그 경로만 설치한다. `gz_sim`, games, Fleet처럼 제품 CORE
  이미지에 필요 없는 source package는 제외하고 설치 후 apt cache를 비운다.
- 증거: ARM64 run 35652400962는 `noble-updates` 문제를 통과했으나 전체 source tree
  rosdep이 Gazebo/GUI를 설치해 rootfs 공간을 소진했다. resolver 회귀 계약을 추가했다.
- gate 변화: 없음. 새 ARM64 image run 전 ARTIFACT는 HOLD다.
- 결정: D-161 native product payload와 D-164 image 용량 경계 보강.

## 2026-09-22 · uncommitted · deploy(udev): /dev/rosy-motor 별칭을 실제로 만드는 규칙
- 변경: `deploy/robot/udev/99-rosy-motor.rules` 신규(ttyAMA4 -> rosy-motor 심링크, dialout/0660). `configure-uart-pi5.sh` 가 멱등 경로(이미 구성됨 조기 종료)를 포함한 모든 실행에서 규칙을 /etc/udev/rules.d 에 설치(udevadm reload/trigger 최선 노력, 재부팅 문맥은 기존 유지). `build-native-payload.sh` 가 이미지 오버레이에 규칙을 굽는다(+소스 존재 가드). 계약 시험 `test/test_rosy_motor_udev.py`.
- 증거: `python -m pytest test/test_rosy_motor_udev.py test/test_pi_wifi_deployment.py test/test_native_systemd_contract.py test/test_native_ros_payload.py test/test_image_pipeline.py test/test_ubuntu_native_runtime_contract.py -q` 118 passed (2026-09-22 Windows). `bash -n` 두 스크립트 구문 0. 근거: communication-protocol-report.md §8-F — 네이티브 유닛은 DeviceAllow=/dev/rosy-motor 를 요구하나 그 이름을 만드는 주체가 컴테이너 디바이스 매핑(개발 전용, D-161)뿐이었다.
- gate 변화: 없음. 실기 심링크 확인은 DEVICE(device-readback 에 /dev/rosy-motor 노드 증거 추가 후보).
- 결정: 없음 — D-161/D-33 기존 결정의 누락된 실행 조각.
- 교훈: 컴포지이션 양쪽(유닛의 DeviceAllow ↔ 호스트 장치명 생성)이 서로 다른 파일에 있으면 한쪽만 갱신된다. 장치 별칭 계약은 '누가 만드는가'까지 시험으로 고정해야 한다.

## 2026-09-23 · uncommitted · deploy(image+native): T14 — wait-core-ready 포트 파라미터화 + chrony 이미지 계약
- 변경: ① native/wait-core-ready.py 의 URL 이 ROSY_API_PORT(기본 8080)를 따름(api_port 오버레이와 불일치하는 하드코딩 해소) ② customize-rootfs.sh 가 chrony 설치+enable(CORE SRS §25 타임스탬프 전제) ③ verify-mounted-image.py 가 chronyd 존재·chrony.service 활성을 검사. 픽스처 2종(valid root)에 chrony 경로 추가, 부재/비활성 거부 케이스 신규. 부수: 타 세션이 만든 test_line_follow_contract_docs.py 의 API Ref 버전 고정(v1.15)을 헤더 판독형(v1.16)으로 — T10 버전 상향이 깨뜨린 것.
- 증거: `python -m pytest test/test_image_customization_contract.py test/test_native_systemd_contract.py deploy/image/test/ -q` 23 passed · test_line_follow_contract_docs + test_pinky_user_validation 12 passed (2026-09-23 Windows). bash -n 0.
- gate 변화: 없음.
- 결정: 없음 — SRS §25 전제의 이미지 계약화.
- 교훈: 문서 버전을 리터럴로 고정한 시험은 버전이 오를 때마다 깨진다 — 헤더를 읽어 판정하도록 쓰는 편이 유지된다(단, 고정 의도라면 리터럴이 맞을 수도 있다. 이번엔 D-143 표기 존재 확인이 본래 목적이므로 헤더 판독형으로).

## 2026-09-23 · uncommitted · fix(native): rosy-core 가 entry script 를 직접 exec + 준비 프로브가 정지 신호를 깨끗이 끝냄
- 변경: ① `rosy-core.service` `ExecStart` 가 `ros2 run core core` 대신 `/opt/rosy/current/install/lib/core/core` 를 exec 한다 — `ros2 run` 은 자식의 신호 사망을 `sys.exit(-N)`(241/254)로 바꿔 systemd 가 실패로 보게 만들었다. 노드가 주 프로세스면 SIGINT/SIGTERM 사망이 systemd 기본으로 깨끗한 종료이므로 `SuccessExitStatus=241 254` 는 두지 않는다(둘 경우 이중 신호 격상까지 성공으로 덮는다). ② `wait-core-ready.py` 가 SIGINT/SIGTERM 에 exit 0 — 기동 중 `systemctl stop` 은 cgroup 의 `ExecStartPost` 도 때리고, 프로브가 신호로 죽으면 ExecStart 와 무관하게 유닛이 `Failed with result 'signal'` 로 남았다. ③ 계약 시험: ExecStart 에 `ros2 run` 없음·`SuccessExitStatus` 없음·하드코딩 경로가 `--merge-install`+`install_scripts=$base/lib/core` 와 일치, 프로브 신호 처리(POSIX 서브프로세스 시험 포함, Windows 는 skip).
- 증거: `docs/validation/core-shutdown-2026-09-23` D절 — WSL systemd(`is-system-running=degraded`, 유닛 사본 `/run/systemd/system/rosy-core-sdtest.service`, 개인 workspace `/opt/rosy_sdtest`, ROS_DOMAIN_ID=44). 신규 ExecStart: steady start/stop **12/12 `Result=success`, NRestarts=0**, 매회 감사 `system.boot`+`system.shutdown`·포트 해제; 기동 중 stop 1.3–3.0 s 12점 **12/12 success**(기존 ExecStart 는 같은 창에서 2건 실패, 0.1–8 s 창에서 `ExecMainStatus=254` 1건). 프로브 수정 전에는 기동 중 stop 12점 중 7건이 `Result=signal`. 시험 유닛·상태는 실행 뒤 제거(`LoadState=not-found`). 호스트 `test/test_native_systemd_contract.py` 12 passed·1 skipped(Windows), WSL 에서 프로브 시험 4 passed.
- gate 변화: 없음. 실기 `systemctl stop` 과 페이로드의 entry script 경로 확인은 DEVICE 몫으로 남는다.
- 결정: 정지 경로의 판정은 "주 프로세스 종료 코드"만이 아니다 — `ExecStartPost` 같은 control process 도 유닛을 failed 로 만들고, `SuccessExitStatus=` 는 거기에 적용되지 않는다.
- 교훈: 유닛의 정지 의미를 바꾸고 싶을 때 성공 코드 목록을 덧대는 것보다 래퍼를 걷어 신호가 systemd 에 그대로 보이게 하는 쪽이 덮는 범위가 좁고 정확하다.

## 2026-09-23 · uncommitted · docs(native): 래퍼 제거의 근거를 실측에 맞게 정정 + 멈춘 종료 계약을 유닛 쪽에서 고정
- 변경: `rosy-core.service` 주석과 `native/AGENTS.md` 를 다시 썼다 — 래퍼를 걷어낸 이유는 "systemd 가 노드를 직접 감독한다"(신호 재인코딩 241/254 제거, ros2 CLI 기동 창 제거, 파이썬 프로세스 하나 감소)이고, 그 대가로 **주 프로세스의 신호 사망이 깨끗한 종료**가 되므로 core 는 멈춘 종료를 `os._exit(2)` 로 끊는다는 것을 유닛 옆에 적었다. `test/test_native_systemd_contract.py` 는 ExecStart 에 `ros2 run` 없음·`SuccessExitStatus` 없음에 더해 `core/main.py` 의 `STUCK_SHUTDOWN_EXIT_CODE = 2`·`os._exit(...)`·`os.kill(os.getpid()` 부재를 함께 고정하고, 하드코딩 경로가 죽지 않도록 `INSTALL_ROOT="$RELEASE_ROOT/install"`(build-native-payload.sh)과 `'core=core.main:main'`(setup.py) 도 핀으로 잡는다.
- 증거: `docs/validation/core-shutdown-2026-09-23` D절 "멈춘 종료" 표 — 같은 유닛·같은 상황에서 `os._exit(2)` 는 `Result=exit-code`/`ExecMainStatus=2`/`failed`, 이전 `os.kill` 격상은 `Result=success`. 평범한 `systemctl stop` 은 steady 12/12 + 기동 중 5/5 success. 저널 `evidence/logs/sd-stuck-*-journal.txt`. 호스트 `test/test_native_systemd_contract.py` 12 passed·1 skipped.
- gate 변화: 없음. 실기 `systemctl stop` 과 페이로드의 `test -x /opt/rosy/current/install/lib/core/core` 는 DEVICE 몫. "ExecStartPost 중 core 사망" 사례도 DEVICE/후속.
- 결정: 위쪽 2026-09-23 항목이 적은 "성공 코드 목록을 두면 이중 신호 격상까지 덮는다"는 근거는 무효다 — 래퍼가 없으면 격상의 신호 사망도 systemd 가 성공으로 친다. 래퍼를 걷어낸 근거는 systemd 가 노드를 직접 감독한다는 것이고, 격상은 `os._exit(2)` 가 맡는다. 유닛의 정지 의미는 유닛 파일만으로 정해지지 않는다 — 주 프로세스가 무엇으로 죽는지까지가 계약이라, 두 파일을 한 시험이 함께 붙든다.
- 교훈: `SuccessExitStatus` 를 쓰지 않기로 한 판단의 근거가 "격상을 덮는다"였는데, 래퍼를 뺀 순간 그 근거가 무효가 됐다. 선택의 이유가 다른 변경에 의해 사라질 수 있다면 근거를 시험으로 고정해 두는 편이 낫다.

## 2026-09-23 · uncommitted · feat(sd): allocate robot number and Fleet defaults, pin writes to the reviewed plan

- 변경: `prepare-rosy-sd.ps1`에서 `-RobotNumber`, `-FleetEndpoint`, `-FleetTrustProfile`을
  선택 입력으로 바꿨다. 로봇 번호는 registry의 빈 번호(1-61) 중 무작위로 배정하고, Fleet 값은
  콘솔 호스트(`https://<host>.local`, `rosy-pilot-lan`)로 채운다. plan에 출처
  (`robot_number_source`, `fleet_source`)를 남긴다. `-PlanPath`는 PlanOnly 결과를 한 번만 저장하고,
  WRITE는 그 plan의 신원·preset·model·country·Fleet 값을 그대로 쓰고, 디스크·release·image
  hash·SSID·DDS 신원·registry 경로가 바뀌었거나 명시 인자가 plan과 (대소문자까지) 다르면 writer
  호출 전에 실패한다. 자동 번호는 WRITE 안에서 뽑지 않는다 — plan 없이 쓰려면 `-RobotNumber` 필수.
  code-reviewer 지적(대소문자 무시 비교, 조작된 plan의 범위 검사 우회, 미표시 자동 번호,
  preset 미고정)을 반영했다.
- 증거: `python -m pytest test/test_sd_writer_contract.py -q` 46 passed; `python -m pytest
  test/test_sd_personalization.py test/test_media_readback.py test/test_offline_image_signer.py
  deploy/sd/test -q` 27 passed (2026-09-22 Windows)
- gate 변화: 없음. MEDIA/DEVICE HOLD 유지
- 결정: D-33 유지 — 고정 기본값이 아니라 registry 기준 할당이므로 신규 카드마다 다른 번호가 나온다.
  무작위 배정은 registry가 분리된 운영 PC 사이의 DDS domain 충돌 확률을 낮춘다.
- 교훈: PlanOnly와 WRITE가 각자 신원을 새로 뽑으면 검토한 계획과 기록한 카드가 달라진다.
  자동 배정을 도입하면 검토 결과를 고정하는 경로가 같이 필요하다.

## 2026-09-23 · uncommitted · chore(sd): write the first Pinky Pro card from release 2026.09.22-002 (D-173)

- 변경: 없음(실행과 기록). `9aee918` 기준 ARM64 run 35717277503의 unsigned handoff를 받아
  기존 파일럿 키로 서명하고 `-PlanOnly -PlanPath`로 검토한 plan에 고정해 관리자 권한으로 기록했다.
- 증거: SHA256SUMS 12/12 OK; `sign_image_release.py` files_verified 12; `verify-image-release.py`
  ok (image sha256 `eaf843c4…`); disk 1 `Generic STORAGE DEVICE` serial `000000000207` 32,044,482,560 B;
  Imager exit 0; 전체 readback 8,574,867,968 B device=raw sha256 `a82a4652…` verified;
  boot `rosy-provision/provision.json` 726 B; registry 18/`rosy-pinky-e4us`. plan·receipt·log는
  운영 PC `F:\tmp\rosy-release\cards\`에 보관(비밀번호·PSK 없음).
- gate 변화: 없음. MEDIA 증거일 뿐 BOOT/DEVICE는 HOLD — 부팅과 runbook G0-G2가 다음이다.
- 결정: D-173
- 교훈: 릴리스 폴더를 셸 작업 디렉터리로 두면 도구 hook이 `.omc/`를 만들어 서명기가 미등재 파일로
  거부한다. 서명·검증은 릴리스 폴더 밖에서 실행한다. PowerShell PATH에는 openssl이 없으니
  Git의 `usr\bin`을 앞에 둔다.

## 2026-09-23 · uncommitted · docs(adr): D-174 first-boot defects and boot indicator plan

- 변경: 첫 실기 부팅 결과를 D-174과 실행 계획(`docs/plans/2026-09-22-pinky-first-boot-fixes.md`)으로 기록했다.
  코드 변경 없음.
- 증거: 회수한 카드의 ext4 루트를 읽기 전용으로 추출해 journal 확인. `rosy-release-recover.service`가
  `ModuleNotFoundError: No module named 'signing'`(+7.96s)로 실패해 `rosy-core`/`rosy-runtime.target`이
  dependency 실패. `rosy-first-boot`은 +26.3s에 `PROVISIONED`, Wi-Fi `192.168.1.201`, avahi 이름은 `ubuntu.local`.
- gate 변화: DEVICE HOLD 유지(부팅은 했으나 CORE 미기동).
- 결정: D-174
- 교훈: 저장소 경로로 통과하는 import는 설치 배치에서 깨질 수 있다. 이미지 검증은 파일 존재가 아니라
  설치 위치에서 진입점을 실행해야 한다. 사람이 볼 수 있는 부팅 신호가 없으면 매 실패마다 카드를 회수해야 한다.

## 2026-09-23 · uncommitted · docs(adr): D-175 debug log system and first-boot lesson

- 변경: D-175(CORE 밖 4층 디버그 로그)와 실행 계획 `docs/plans/2026-09-22-rosy-debug-log-system.md`,
  교훈 `docs/solutions/workflow-issues/installed-layout-import-passes-repo-tests-2026-09-22.md` 추가. 코드 변경 없음.
- 증거: 기존 관측(`/api/v1/logs/audit`, events, diagnostics collector)은 모두 CORE 프로세스 안이라 D-174 F1
  상황에서 쓸 수 없었다. 원인 확인에 카드 회수·관리자 권한 ext4 추출·WSL journalctl이 필요했다.
- gate 변화: 없음
- 결정: D-175
- 교훈: 관측 수단은 그것이 진단해야 할 실패와 같은 전제(CORE 기동, 네트워크)에 기대면 안 된다.

## 2026-09-23 · uncommitted · fix(native): run release recovery from the installed layout (D-174 F1, F5)

- 변경: `deploy/robot/native/install-native-runtime.sh`가 런타임을 설치하면서 `signing.py`를 함께 넣는다.
  `build-native-payload.sh`는 두 사본(`/opt/rosy/native-runtime`, release `deploy/robot/native`)을 모두 이
  설치기로 만든다. `native_release.py`는 저장소 경로를 fallback으로만 붙여 설치 사본을 가리지 않는다.
  `customize-rootfs.sh`는 ARM64 chroot에서 두 복구 진입점과 first-boot `--help`를 실제로 실행하고,
  `verify-mounted-image.py`는 각 사본 옆 `signing.py`를 확인한다.
- 증거: 기존 `cp -a` 배치로 `native_release.py recover`를 돌리면 `ModuleNotFoundError: No module named 'signing'`
  (카드 journal과 동일) 재현. 새 `test/test_native_runtime_installed_layout.py` 4 passed, native/image 스위트 105 passed,
  이미지 계약·마운트 검증 13 passed (2026-09-22 Windows)
- gate 변화: 없음. ARTIFACT/DEVICE는 release 003 빌드·실기 부팅 전까지 HOLD
- 결정: D-174
- 교훈: `docs/solutions/workflow-issues/installed-layout-import-passes-repo-tests-2026-09-22.md`

## 2026-09-23 · uncommitted · fix(first-boot): apply the device hostname to the running system (D-174 F2)

- 변경: 첫 부팅이 `/etc/hostname`을 쓴 직후, 네트워크 활성화 전에 `hostnamectl set-hostname`(실패 시 `hostname`)으로
  실행 중 이름을 바꾸고 `avahi-daemon`을 try-restart한다. 실패해도 개인화는 계속한다(파일은 이미 맞다).
  `--root`가 `/`가 아니면 호스트 명령을 실행하지 않는다.
- 증거: `python -m pytest test/test_first_boot_provisioning.py -q` 11 passed(신규 4: 순서, 실패 허용, 비-/ root 보호,
  기본 명령) (2026-09-23 Windows). 실기 증거는 release 003 부팅 전까지 없음.
- gate 변화: 없음
- 결정: D-174
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(native): keep bytecode out of signed releases; require the installed runtime (D-174 review)

- 변경: code-reviewer 지적 반영. `native_release.py`는 `sys.dont_write_bytecode`를 켜고 release 래퍼 3개와 이미지 chroot
  probe는 `python3 -B`로 돈다(서명 release 안 `__pycache__`는 unlisted 파일이라 `verify(old_current)`가 복구를 HOLD시킨다).
  `verify-mounted-image.py`는 두 런타임 사본의 `native_release.py`·`signing.py`·`recover-release.sh`를 필수로 요구하고
  release 안 `__pycache__`를 거부한다. 설치기는 자기 자신을 배포하지 않는다. `device_readback.py`는
  `/opt/rosy/native-runtime/signing.py`를 먼저 찾는다. probe 주석을 "import smoke test"로 정정하고 실패 시 정리한다.
- 증거: native/image/first-boot/readback 스위트 61 passed (2026-09-23 Windows)
- gate 변화: 없음
- 결정: D-174
- 교훈: 설치 배치에서 import가 되게 만들면, 그 import가 남기는 부산물(bytecode)도 서명 경계를 넘는다.

## 2026-09-23 · uncommitted · feat(native): boot status indicator outside CORE (D-174 T0)

- 변경: `rosy_boot_state.py`(단계 모델: BOOTING·PROVISIONED·CORE_READY·FAILED:<가장 이른 실패 unit>)와
  `rosy-boot-status.py`(root oneshot)를 추가했다. 출력은 서로 독립인 네 곳이다: `/run/rosy/boot-status.json`,
  보드 ACT LED(준비 heartbeat, 실패 100ms 점멸, 그 외 SD 활동), 콘솔 배너(`/run/rosy/issue` ← `/etc/issue.d/rosy.issue`),
  avahi `_rosy._tcp`(TXT `stage`, `release`, `name`). 30초 timer와 네 부팅 unit의 `OnFailure=`로 갱신하며
  runtime target·CORE를 막지 않는다. 한 출력의 실패가 다른 출력을 멈추지 않고, 도구는 부팅을 실패시키지 않는다.
- 증거: `test/test_boot_state.py` 10 passed, `test/test_boot_status_indicator.py` 12 passed — 첫 카드와 같은
  unit 상태를 넣으면 네 출력 모두 `FAILED:rosy-release-recover`를 보인다. native/image/first-boot 스위트 55 passed
  (2026-09-23 Windows). 실기(LED 이름 `ACT`, agetty `--reload`, avahi 서비스 재적재)는 release 003 부팅 전까지 미검증.
- gate 변화: 없음
- 결정: D-174
- 교훈: 없음

## 2026-09-23 · uncommitted · feat(native): boot black box on the FAT32 boot partition (D-175 L1)

- 변경: `rosy_diag_redact.py`(비밀 제거·금지 경로)와 `rosy_blackbox.py`를 추가하고 `rosy-boot-status.py`의 독립 출력으로
  연결했다. `/boot/firmware/rosy-diag/`에 부팅당 한 개의 `boot-NNNN-<boot_id8>.json`과 사람이 읽는 `latest.txt`를 쓴다.
  단계가 바뀔 때만 쓰고(30초 timer에도 재기록 없음), 최근 5회 부팅·총 2 MiB로 제한하며, 실패 unit의 journal 마지막
  60줄을 비밀 제거 후 담는다. 치환 문자열 `<redacted>`는 저장소 secret scanner가 자리표시자로 인정한다.
- 증거: `test_diag_redaction.py` 25, `test_boot_blackbox.py` 7(첫 카드 상태로 `latest.txt`에 `FAILED:rosy-release-recover`와
  `No module named 'signing'`, 토큰 제거·scanner 통과, 같은 단계 재기록 없음, 5회 회전, 용량 상한), installed-layout 7 passed
  (2026-09-23 Windows). 실기 FAT32 쓰기는 release 003 부팅 전까지 미검증.
- gate 변화: 없음
- 결정: D-175
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(native): writable ROS home for service users; bounded persistent journal (D-174 F6, D-175 L0)

- 변경: `rosy-core`·`rosy-io`·`rosy-navigation`에 `LogsDirectory=`와 `ROS_HOME`/`ROS_LOG_DIR`=`/var/log/<unit>`을 준다(홈 없는
  서비스 사용자 + `ProtectHome=true`에서 rclpy가 `$HOME/.ros/log`를 쓰려다 실패하는 것을 선제 차단). journald drop-in
  `60-rosy.conf`(`Storage=persistent`, `SystemMaxUse=200M`, `RuntimeMaxUse=32M`)을 이미지 overlay에 넣는다.
- 증거: `test_native_systemd_contract.py` 등 44 passed (2026-09-23 Windows). F6는 F1에 가려져 실기에서 재현된 적이 없다 —
  release 003 부팅에서 CORE 기동으로 확인한다.
- gate 변화: 없음
- 결정: D-174, D-175
- 교훈: 없음

## 2026-09-23 · uncommitted · feat(sd): per-card operator SSH key and key-only `rosy` login (D-174 F3)

- 변경: 번들에 선택 섹션 `operator.ssh_authorized_keys`(ed25519/ecdsa 공개키 1-8개, 단일 줄·타입·blob 일치 검증, 개인키 거부)를
  추가하고 스키마·receipt(지문만)에 반영했다. 첫 부팅은 키가 있을 때만 `rosy` 계정(비밀번호 없음, `systemd-journal`/`adm`,
  NOPASSWD sudo)을 만들고 `authorized_keys`(0600)를 설치하며 `complete.json`에 지문을 남긴다. `prepare-rosy-sd.ps1
  -OperatorPublicKey`는 지문을 plan에 고정하고 다른 키로 기록하려 하면 writer 전에 멈춘다. receipt는 `ConvertTo-Json -Depth 10`으로
  쓴다(기본 깊이 2가 중첩 목록을 문자열로 뭉개던 잠재 결함).
- 증거: `test_sd_operator_access.py` 13, `test_sd_writer_contract.py` 49, first-boot/personalization 포함 45 passed; 전체 1394 passed
  (남은 2건은 main `10ceb53`의 `system.py` BOM, 이 브랜치와 무관) (2026-09-23 Windows)
- gate 변화: 없음
- 결정: D-174
- 교훈: 없음

## 2026-09-23 · uncommitted · feat(sd): rewrite a card for an existing device identity (D-174 F7)

- 변경: `prepare-rosy-sd.ps1 -ReprovisionReceipt`가 이전 receipt(Imager exit 0, readback verified)의 번호·이름·UID로만 registry
  재사용을 허용한다. 명시 인자가 receipt와 다르면 거부하고, plan은 `robot_number_source: reprovision`, 새 receipt는 `supersedes`
  (이전 release_id·image_sha256·created_at)를 남긴다.
- 증거: `test_sd_writer_contract.py` 55 passed (2026-09-23 Windows). 실제 `receipt-2026.09.22-002.json`(18번 `rosy-pinky-e4us`)이
  필요한 필드를 모두 가진다.
- gate 변화: 없음
- 결정: D-174
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(native,sd): review of the boot indicator, black box and operator access (D-174, D-175)

- 변경: code-reviewer 17건(HIGH 2, MEDIUM 9 중 적용 가능 전부, LOW 다수) 반영.
  H1 root 표시 도구가 CORE 소유 `/run/rosy`에 예측 가능한 임시 이름으로 쓰던 것을 root 소유 `/run/rosy-boot`
  (`RuntimeDirectory=rosy-boot`, preserve)과 `mkstemp`+`fchmod`로 바꿨다. H2 계정 생성 실패·기존 계정 불일치 시
  운영자 접근만 건너뛰고 개인화는 계속한다. M1 `-ReprovisionReceipt`는 plan 신원이 receipt와 같고 registry에
  이미 있을 때만 통과한다. M2 receipt 증거는 타입 검사(`[int]`/`[bool]`)한다. M3·M4 redaction 정규식을 경계·상한이
  있는 형태로 바꾸고 Python repr, 따옴표 값, URL userinfo, nmcli 인자, Cookie, 숫자 값을 지운다. M6 CORE는
  `RestartMode=direct`, 표시 unit은 `StartLimitIntervalSec=0`, 블랙박스는 같은 부팅에서 새 실패·CORE_READY 복구가
  아니면 5분에 한 번만 다시 쓴다. M7 내용이 같으면 avahi·issue를 다시 쓰지 않는다. M8 D-174에 NOPASSWD sudo
  범위와 실제 로그 위치를 적었다. M9 ROS 로그 디렉터리는 tmpfiles.d로 7일 후 정리한다. L1 출력 하나의 어떤 예외도
  다른 출력을 멈추지 않는다. L2 표시 unit은 runtime target 뒤에 줄 서지 않는다. L3 보고서 번호는 6자리·숫자 정렬.
  L4 잘못된 operator 섹션은 `ValueError`. L5 기존 계정의 홈·셸 확인. L7 avahi 포트는 `ROSY_API_PORT`. L8 FAT32
  rename 뒤 디렉터리 fsync.
- 증거: 표시·블랙박스·redaction·systemd 75 passed(심볼릭 링크 공격 시험은 Windows 권한 문제로 skip, Linux CI에서 실행),
  first-boot·personalization 50 passed, SD writer reprovision 12 passed (2026-09-23 Windows). 실기(ACT LED, agetty,
  avahi, systemd 255 `RestartMode`) 확인은 release 003 부팅 때.
- gate 변화: 없음
- 결정: D-174, D-175
- 교훈: root가 도는 관측 도구는 관측 대상(CORE)이 쓰는 디렉터리를 절대 쓰지 않는다. 관측이 공격 경로가 된다.

## 2026-09-23 · uncommitted · fix(image): check bytecode only in the native runtime, not colcon's install tree

- 변경: `verify-mounted-image.py`의 `__pycache__` 거부를 release 전체에서 네이티브 런타임 두 사본
  (`/opt/rosy/native-runtime`, release `deploy/robot/native`)으로 좁혔다. colcon은 `install/.../site-packages/*/__pycache__`를
  payload 일부로 설치하며, 런타임은 `ProtectSystem=strict`로 `/opt`에 쓰지 못한다.
- 증거: ARM64 run 35756347921(release 003, `a2095a0`)이 이 검사로 customizer 단계에서 실패했다. colcon `__pycache__`
  회귀 시험 추가, `deploy/image/test`·이미지 계약 17 passed (2026-09-23 Windows).
- gate 변화: 없음(ARTIFACT HOLD)
- 결정: D-174
- 교훈: 거부 규칙은 위험이 생기는 경로에 정확히 맞춘다. 넓은 규칙은 정상 산출물을 막고, 그 실패는 비싼 ARM64 빌드 끝에서야 보인다.


## 2026-09-23 · uncommitted · merge(deploy): origin/main 병합 — RestartMode=direct와 정지 계약의 관계

- 변경: origin/main(PR #20·#21, D-174·D-175)을 로컬 main에 병합했다. `rosy-core.service`는 양쪽 변경이 모두 남는다 — 이쪽의 직접 exec ExecStart·정지 계약 주석과, 저쪽의 `LogsDirectory`/`ROS_HOME`/`RestartMode=direct`/`TimeoutStartSec=60`.
- 증거: `pytest test/test_native_systemd_contract.py src/core/core/test/test_core_main_shutdown.py src/core/core/test/test_core_node_teardown.py -q` 49 passed 1 skipped. `rosy_harness.py lint` 0 error.
- gate 변화: 없음.
- 결정: `RestartMode=direct`는 그대로 둔다. 다만 `docs/validation/core-shutdown-2026-09-23`의 `ActiveState=failed` 측정은 그 지시어가 없던 유닛에서 나온 값이다. 지시어가 있으면 격상 종료(exit 2)는 여전히 `Restart=on-failure`로 재시작되지만 재시작 동안 unit이 failed 상태를 거치지 않으므로 `systemctl is-failed`로는 보이지 않는다. 실기 게이트에서 `Result=exit-code`/`ExecMainStatus=2`와 저널 격상 줄로 확인한다.
- 교훈: 정지 계약은 유닛 파일 한 줄이 아니라 여러 지시어의 조합이다. 다른 트랙이 재시작 정책을 바꾸면 종료 판정 근거도 다시 읽어야 한다.
