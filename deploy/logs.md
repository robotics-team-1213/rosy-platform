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

## 2026-09-23 · uncommitted · docs(deploy): CORE 개발 오버레이는 설계만 연결

- 변경: `deploy/progress.md`의 plans에 `docs/plans/2026-09-23-core-dev-overlay-design.md`를 넣고, 지금 상태에 미구현임을 한 줄 적었다. 설치기, compose 기동, readback, 네이티브 유닛은 수정하지 않았다.
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 21 warnings (2026-09-23 Windows). 설계 문서라 실행 시험은 없다.
- gate 변화: 없음. ARTIFACT/DEVICE HOLD 유지.
- 결정: 없음
- 교훈: 없음

## 2026-09-23 · uncommitted · docs(deploy): D-179를 배포 진행에 연결

- 변경: `deploy/progress.md` adrs에 D-179, plans에 실행 계획을 넣었다. 지금 상태는 정책이 Accepted이고 스크립트·readback은 아직 없다고 적는다. 설치기, compose 기동, 네이티브 유닛 본문은 수정하지 않았다.
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 21 warnings. ADR·하네스 계약 `70 passed` (2026-09-23 Windows). 오버레이 스크립트 시험은 계획 착지 전이라 없다.
- gate 변화: 없음. ARTIFACT/DEVICE HOLD 유지.
- 결정: D-179
- 교훈: 없음

## 2026-09-23 · uncommitted · docs(deploy): D-179 실행 계획에 반복 동작

- 변경: 실행 계획이 두 번째 수정, 재부팅 뒤 재적용, compose 프로젝트 `rosy-runtime` 유지를 시험 항목으로 가진다. `deploy/progress.md`의 gate와 설치기 본문은 그대로다.
- 증거: 계획 본문만. `python tools/harness/rosy_harness.py lint` 0 errors, 21 warnings (2026-09-23 Windows).
- gate 변화: 없음. ARTIFACT/DEVICE HOLD 유지.
- 결정: D-179
- 교훈: 없음

## 2026-09-23 · uncommitted · feat(deploy): host-tested D-179 bench overlay

- 변경: 허용 목록 스테이징, 바인드 명령, 해시 확인, readback HOLD, Windows 동기화 스크립트를 넣었다. 재부팅은 이미지 코드로 돌아가고 마커 HOLD가 남는다. compose 프로젝트는 `rosy-runtime`이다. 설치기와 `rosy-core.service` 본문은 수정하지 않았다.
- 증거: `python -m pytest test/test_core_dev_sync.py test/test_device_readback.py test/test_native_systemd_contract.py -q` 59 passed, 1 skipped (2026-09-23 Windows).
- gate 변화: 없음. ARTIFACT/DEVICE HOLD 유지.
- 결정: D-179
- 교훈: 없음

## 2026-09-23 · uncommitted · docs(adr): D-176 boot config file and per-card fallback AP

- 변경: D-176과 실행 계획 `docs/plans/2026-09-23-boot-config-and-fallback-ap.md`를 추가했다. 코드 변경 없음.
  운영자가 카드 boot 파티션의 `rosy-config.yaml`로 Wi-Fi·Fleet·AP 정책을 바꾸고, 비밀번호는 적용 직후 카드에서 지운다.
  업링크가 없으면 카드별 랜덤 비밀번호의 `rosy-pinky-xxxx` AP를 연다(D-154 결정 5·6 부분 대체, D-26 유지).
- 증거: `network.py` 상태 기계(D-26/D-124/D-154)가 네이티브 이미지에 연결되지 않았고, 첫 부팅은 `PROVISIONING_AP`를 기록만 한다.
- gate 변화: 없음
- 결정: D-176
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(sd): pass the operator key as an argument; keep the disk offline during readback

- 변경: `prepare-rosy-sd.ps1`이 운영자 공개키 지문을 계산할 때 파이프 대신 인자(`sys.argv[1]`)로 넘긴다. Windows PowerShell
  5.1이 콘솔을 거친 파이프에 BOM을 붙여 실제 키가 거부됐다(콘솔 없는 시험은 통과). 전체 readback 동안 대상 디스크를
  `Set-Disk -IsOffline $true`로 내리고 끝나면 다시 올린 뒤 번들을 복사한다. `-ReadbackDevice`(픽스처)일 때는 물리 디스크를
  건드리지 않는다.
- 증거: release 004 기록이 `MEDIA_READBACK_FAILED: media readback mismatch at byte offset 1049576`로 멈췄다. 1 MiB 파티션 시작
  + 1000 B는 FAT32 FSInfo 섹터이며, 쓰기 직후 Windows가 파티션을 마운트해 갱신한다. `test_sd_writer_contract.py` 63 passed
  (2026-09-23 Windows).
- gate 변화: 없음(MEDIA 재기록 필요)
- 결정: D-173
- 교훈: `docs/solutions/workflow-issues/guards-validated-only-against-synthetic-fixtures-2026-09-23.md` — 픽스처에는 콘솔도,
  자동 마운트하는 OS도 없다.

## 2026-09-23 · uncommitted · fix(sd): tolerate exactly the FAT32 fields Windows rewrites on mount; stop offlining removable media

- 변경: `verify-media-readback.py`가 이미지 자신의 MBR·BPB로 FAT32 boot 파티션을 찾아, Windows가 자동 마운트 때 갱신하는 필드만
  허용한다: FSInfo(원본·백업) 남은 클러스터 수·다음 빈 클러스터(488-495), 부트 섹터 `0x41`의 dirty 비트(0x03), 각 FAT 엔트리 1의
  clean-shutdown/hard-error 비트(0x0C). 그 밖의 바이트나 비트가 다르면 실패하고, 허용한 오프셋은 `tolerated_fat_mount_metadata`로
  receipt에 남는다. `Set-Disk -IsOffline`은 제거했다.
- 증거: release 004 재시도가 `Set-Disk : Not Supported … Removable media cannot be set to offline.`로 멈췄다(Imager 쓰기는 성공).
  첫 시도의 불일치 오프셋 1049576 = 파티션 시작 + 512 + 488 = FSInfo 남은 클러스터 수. `test_media_readback.py` 9 passed(허용 1, 거부 4 추가).
- gate 변화: 없음(MEDIA 재기록 필요)
- 결정: D-173
- 교훈: 없음(`guards-validated-only-against-synthetic-fixtures-2026-09-23.md`의 사례와 같다)

## 2026-09-23 · uncommitted · fix(sd): compare the FAT32 boot partition as files; everything else stays byte-exact

- 변경: `verify-media-readback.py`는 MBR·틈·루트 파일시스템을 바이트 단위로 대조하고, FAT32 boot 파티션은 이미지와 카드 양쪽을 같은
  읽기 전용 FAT32 파서(LFN 포함)로 읽어 파일·디렉터리 내용으로 비교한다. 카드에만 있는 항목은 `System Volume Information` 트리만
  허용하고 `boot_partition.windows_extras`로 남긴다. 직전 커밋의 필드 단위 허용은 이 방식으로 대체했다.
- 증거: 세 번째 기록이 `media readback mismatch at byte offset 1064967`(FAT1 엔트리 1 상위 바이트 0x0F→0xFF)로 멈췄다. 관리자 읽기
  전용 비교에서 차이 18곳 중 FSInfo 힌트 외에 FAT 클러스터 할당(`0xFFFFFFFF`)이 보였다 — Windows가 마운트하며 폴더를 만든다.
  `test_media_readback.py` 10 passed(파일 비교 통과, 바이트 동일 보고, 파일 변조·예상 밖 항목·루트fs·파티션 테이블 변조 실패).
- gate 변화: 없음(MEDIA 재기록 필요)
- 결정: D-173
- 교훈: 측정으로 원인을 확정하기 전에 허용 규칙을 넓히면 한 회차를 더 잃는다. 첫 불일치 오프셋 하나로 규칙을 만들지 않는다.

## 2026-09-23 · uncommitted · feat(sd): select the card by serial, not by Windows disk number

- 변경: `prepare-rosy-sd.ps1`에 `-DiskSerial`을 추가하고, WRITE에서 plan만 주면 plan의 `disk_serial`로 USB 디스크 번호를 다시 찾는다.
  시리얼은 정확히 하나의 USB 디스크여야 하며, `-DiskNumber`를 함께 주면 둘이 같아야 한다. plan 드리프트 비교에서 디스크 번호를
  빼고 시리얼·용량·모델로 비교한다. 확인 문구는 `ERASE SERIAL <serial> <device_name>`이다.
- 증거: release 004 다섯 번째 시도 직전, 다른 USB 장치가 빠지며 카드가 디스크 2 → 1로 바뀌어 `disk number does not resolve to exactly
  one disk`로 멈췄다(안전장치는 정상 동작). 새 시험 7건 포함 `test_sd_writer_contract.py` 69 passed (2026-09-23 Windows).
- gate 변화: 없음
- 결정: D-173(카드 기록 절차), D-154 결정 4의 확인 문구 형식을 시리얼로 바꾼다
- 교훈: 운영체제가 매번 다시 매기는 번호로 물리 대상을 고정하지 않는다. 사람이 확인하는 문구도 안정적인 식별자를 써야 한다.

## 2026-09-23 · uncommitted · feat(sd): operator entry point write-card.ps1 for writing a reviewed plan

- 변경: `deploy/sd/write-card.ps1`을 추가했다. 입력은 plan, 서명 릴리스 폴더, Wi-Fi 프로필이다. 이미지·서명·공개키·registry·receipt 경로를
  plan과 릴리스에서 계산하고, 카드는 plan의 시리얼로 찾으며, 스스로 UAC 승격하고, 시도마다 시각이 붙은 로그와 `.exit` 표지를 남긴다.
  receipt가 이미 있으면 멈춘다. ERASE 확인은 승격된 창에서 운영자가 입력한다(`-Confirmation`으로 생략 가능). `-PrintArguments`는 쓰지 않고
  계산된 호출만 보여 준다.
- 증거: `test/test_sd_write_card_entrypoint.py` 6 passed; 실제 `plan-2026.09.23-004-disk1.json`으로 `-PrintArguments` 확인 (2026-09-23 Windows).
- gate 변화: 없음
- 결정: D-173
- 교훈: 네 번의 004 재시도는 모두 손으로 만든 래퍼(고정 디스크 번호, 경로 조립, 로그 이름 바꾸기)를 거쳤다. 반복되는 운영 절차는 저장소 도구로 만든다.

## 2026-09-23 · uncommitted · feat(native,sd,image): boot settings file and per-card fallback AP (D-176 Task 1-6)

- 변경: `rosy_config.py`(스키마·계층·scrubbed view), `rosy-config-apply.py`(부팅 시 `rosy-config.yaml` 적용 후 카드의 비밀번호를
  `"<applied>"`로 교체), `rosy-network.py`(uplink 없음 120 s → AP 개방, 600 s 후 사이트 Wi-Fi 재시도), 카드별 랜덤 AP 비밀번호
  (DPAPI 보관, 1회 출력, plan/receipt에는 SSID만), 콘솔 배너·mDNS의 AP 표시를 추가했다. 이미지가 `rosy-config.service`,
  `rosy-network.service`, `/etc/rosy/defaults.yaml`을 싣고 활성화하며, 설치 위치에서 세 진입점을 `--help`로 실행해 본다.
  `deploy.sd` import는 `/opt/rosy` 고정 경로 대신 자기 위치 기준(`parents[1]`)으로 찾는다. 런북에 현장 Wi-Fi 변경과 AP 접속 절차를 넣었다.
- 증거: `test_rosy_config.py`, `test_rosy_config_apply.py`, `test_rosy_network_fallback.py`, `test_sd_ap_credentials.py`,
  `test_native_runtime_installed_layout.py`(설치 트리에서 `rosy-config-apply.py`/`rosy-network.py` import),
  `test_image_customization_contract.py`, `test_native_systemd_contract.py` 통과 (2026-09-23 Windows). 기기 수용은 아직 없음.
- gate 변화: 없음 (D-176 Validation의 기기 확인은 다음 카드에서)
- 결정: D-176
- 교훈: 새 진입점은 저장소 테스트만으로 부족하다. 이미지가 설치하는 트리에서 import해 보는 테스트와 이미지 빌드 probe를 같은 변경에 넣는다.

## 2026-09-23 · uncommitted · feat(sd): read-only card diagnostics without wsl --mount

- 변경: `deploy/sd/read-card-diagnostics.py`를 추가했다. 세션 추출기를 저장소 도구로 올렸다. 물리 디스크(또는 원본 이미지 파일)를
  읽기 전용으로 열고 MBR에서 Linux 루트(0x83)를 찾아 순수 Python `ext4`로 `/var/lib/rosy`, `/etc/rosy`, `/etc/hostname`,
  `/etc/passwd`, `/etc/systemd/system`, `/var/log/journal`, `/var/log/cloud-init*.log`만 복사하고, FAT32의 `rosy-diag/`(D-175 L1)도
  함께 복사한다. `rosy_diag_redact.is_denied_path`가 거부하는 경로(Wi-Fi 연결 파일, `rosy-provision/`, 토큰·키)는 열지 않는다.
  `extract-report.json`에 크기·sha256·저장 이름·거부·누락·오류를 남긴다. Windows가 못 쓰는 이름(`\x2d`)은 `%`로 이스케이프한다.
  CI pip에 `ext4`를 추가했다.
- 증거: `test/test_card_diagnostics.py` 15 passed(실제 `mkfs.ext4 -d` 이미지를 WSL로 만들어 추출, `ext4` 설치 venv, 2026-09-23 Windows);
  `ext4`가 없는 기본 Python에서는 14 passed, 1 skipped.
- gate 변화: 없음. 실제 카드에서 이 도구로 다시 읽은 증거는 아직 없다(세션 프로토타입만 실제 카드에서 동작)
- 결정: D-174 F8, D-175
- 교훈: 카드 진단 경로는 장애가 난 뒤에 만들면 늦다. 한 번 동작한 수작업은 그 자리에서 거부 목록과 시험을 붙여 도구로 올린다.

## 2026-09-23 · uncommitted · feat(robot): rosy-diag collect, the L2 on-device diagnostics bundle

- 변경: `deploy/robot/native/rosy_diag_collect.py`(표준 라이브러리만)와 `rosy-diag` 래퍼를 추가했다. `rosy-diag collect --out DIR`가
  이번 부팅 `rosy-*` journal, `systemctl` 상태·목록·실패, `/var/lib/rosy/provisioning/*.json`, release 활성화 journal, dmesg 끝 400줄,
  네트워크 요약(`ip -brief`, `nmcli` 장치·SSID, 키 없음), boot 파티션 `rosy-diag/`를 모아 tar.gz 하나로 만든다. 모든 멤버는
  `rosy_diag_redact.redact`를 거치고 거부 경로는 읽지 않는다. `manifest.json`에 멤버 sha256·반환 코드·잘림 여부와 boot_id·release_id·
  device_name·uptime을 넣는다. 내용 합계 50 MiB 상한(멤버 16 MiB, journal은 최신 줄 유지), 기존 파일은 덮어쓰지 않는다.
  네이티브 디렉터리 전체가 설치되므로 설치기 변경은 없다.
- 증거: `test/test_diag_collect.py` Windows 13 passed, 1 skipped(심볼릭 링크 래퍼 시험); WSL Ubuntu 14 passed. 설치 배치
  (`install-native-runtime.sh` → `<tmp>/opt/rosy/native-runtime`)에서 실행, 모든 멤버가 `secret_scan.scan_text` 통과. WSL에서 실제
  `journalctl`·`systemctl`·`dmesg`로 한 번 돌려 번들 생성과 scan 0건 확인(2026-09-23).
- gate 변화: 없음. 실제 Pinky에서의 권한(journal 그룹, dmesg_restrict, sudo)과 크기는 미검증
- 결정: D-175
- 교훈: `/proc/sys/kernel/random/boot_id`는 대시가 있는 UUID이고 journald boot id는 32자 hex다. 층 사이 상관 키는 비교 전에 정규화한다.

## 2026-09-23 · uncommitted · feat(robot): collect-rosy-diagnostics.ps1, the L2 Windows puller with a card fallback

- 변경: `deploy/robot/collect-rosy-diagnostics.ps1`를 추가했다. `-Host -User rosy -IdentityFile`로 키 전용 BatchMode SSH(비밀번호·키보드
  인증 끔, `IdentitiesOnly`)를 `%LOCALAPPDATA%\Rosy\known_hosts`에 고정(첫 접속 `accept-new`)해 장치에서 `rosy-diag collect`를 돌리고
  번들을 `evidence\<device>\<boot_id>\`로 `scp`한다(`.partial` 후 이동, 기존 파일이면 멈춤, 원격 임시 폴더는 항상 삭제). boot_id는 대시를
  뺀 32자 hex로 정규화한다. SSH가 255로 끝나고 `-CardDisk <serial>`이 있으면 카드의 FAT32 `rosy-diag\`만 승격 없이 복사하고 journal용
  관리자 명령(`read-card-diagnostics.py`)을 출력한다. `-PrintPlan`은 아무것도 실행하지 않고 계산된 호출을 보여 준다.
- 증거: `test/test_collect_diagnostics_contract.py` 7 passed(가짜 ssh/scp로 실제 PowerShell 5.1 실행, 2026-09-23 Windows). 실제
  Windows OpenSSH 9.5로 도달 불가 주소(192.0.2.1)에 실행해 exit 255 → `-CardDisk` 안내를 확인.
- gate 변화: 없음. 실제 장치 SSH·scp와 카드 드라이브 문자 탐색(`Get-Disk`/`Get-Volume`)은 미검증
- 결정: D-175
- 교훈: Windows PowerShell 5.1은 네이티브 인자 안의 큰따옴표를 망가뜨린다. 원격 명령은 큰따옴표 없이 쓰고 값은 인자로 넘긴다.

## 2026-09-23 · uncommitted · feat(image): put rosy-diag on PATH (D-175 L2)

- 변경: 이미지가 `/usr/local/bin/rosy-diag` → `/opt/rosy/native-runtime/rosy-diag` 링크를 만든다. 콘솔에서 `rosy-diag collect --out DIR`로 바로 쓴다.
  wrapper는 링크를 따라가 자기 위치를 찾는다(WSL symlink 테스트로 확인됨). Windows 수집기는 계속 전체 경로를 쓴다.
- 증거: `test_image_customization_contract.py` 통과 (2026-09-23 Windows). 기기 확인 없음.
- gate 변화: 없음
- 결정: D-175
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(native,image): D-176 review — no password on vfat, in YAML errors or in world-readable files; AP needs dnsmasq

- 변경: 독립 리뷰(HIGH 4, MEDIUM 5, LOW 2)를 반영했다. (1) vfat 부트 파티션은 chmod가 EPERM이라 스크럽이 실패하고 평문이 남았다 → 카드 쓰기는 mode를
  건드리지 않는다. (2) PyYAML 오류 문구가 비밀번호 줄을 인용해 0644 상태 파일과 journal에 들어갔다 → 줄·열 위치만 남기고 상태 파일은 0600.
  (3) AP 비밀번호가 든 `/run/rosy-boot/issue`를 0600으로. (4) NM shared 모드에 필요한 `dnsmasq-base`를 이미지에 넣고 마운트 검증기가 확인한다.
  그 밖에: 게이트웨이 없는 현장 LAN도 NM `connected`면 uplink로 본다, AP 활성화를 `GENERAL.STATE`로 확인하고 실패하면 광고하지 않고 다시 시도,
  AP를 닫으면 `nmcli device connect wlan0`로 현장 Wi-Fi를 바로 재시도, 재시작 시 AP를 내리고 시작, 숫자만 있는 비밀번호·SSID 허용,
  NM keyfile이 망가뜨리는 값(백슬래시·양끝 공백·비ASCII 비밀번호) 거부, 건너뛴 항목이 있으면 기존 Wi-Fi 프로필을 지우지 않음, vfat에 진단 묶음 저장 허용.
  `relay`는 Pi 5 단일 무선이라 현장 Wi-Fi를 끈다는 점을 템플릿에 적었다.
- 증거: 관련 스위트 110 passed (2026-09-23 Windows). vfat EPERM은 fchmod 거부를 흉내 낸 테스트로만 확인, 기기 확인 없음.
- gate 변화: 없음
- 결정: D-176
- 교훈: 호스트 파일시스템 테스트는 vfat의 고정 mode를 재현하지 못한다. 부트 파티션에 쓰는 코드는 chmod 거부를 가정한 테스트를 같이 둔다.

## 2026-09-23 · uncommitted · merge(deploy): origin/main 병합 — D-176 부트 설정·폴백 AP, rosy-diag 2단계, SD 라이터

- 변경: `ebf2516d`(PR #23 19건)을 `1d2129af`로 병합했다. 들어온 것: 카드 `rosy-config.yaml` 부트 설정 스택(`rosy_config.py`·`rosy-config-apply.py`·`rosy-network.py`·`rosy-config.service`·`rosy-network.service`, D-176), 업링크 없을 때 카드별 비밀번호 fallback AP, `rosy_diag_collect.py`·`rosy_diag_redact.py`·`collect-rosy-diagnostics.ps1`·`read-card-diagnostics.py`(diag 2단계), SD 라이터 `write-card` 진입점·단일 readback 검증, `verify-mounted-image.py`/__pycache__ 정련, `.gitattributes`·`ci.yml`. 충돌 3건은 ADR Log(D-176 복권·장치 편입 D-181 이명), `deploy/logs.md`(양쪽 블록 모두 보존), `deploy/index.md`(generate 재생성)으로 해소했다.
- 증거: 병합 신규 시험 15종(`test_rosy_config`·`test_rosy_network_fallback`·`test_sd_write_card_entrypoint`·`test_card_diagnostics`·`test_boot_status_indicator` 등) 포함 `python -m pytest test/ -q` 전체 회귀 + `rosy_harness.py lint` — 아래 게이트 줄에 실측 수치.
- gate 변화: 없음 — ARTIFACT/DEVICE HOLD 유지(D-176 Validation의 실기 확인은 다음 카드에서).
- 결정: `deploy/logs.md` 충돌은 합치지 않고 **origin 블록 → HEAD 블록 순으로 두 벌 모두 보존**(append-only 저널). D-176 번호는 origin 쪽 부팅 설정이 유지, 기존 로컬 D-176(장치 편입)은 D-181로 이명했다.
- 교훈: append-only 저널의 병합 충돌은 어느 쪽도 버리지 않는다 — `deploy/index.md`는 편집하지 말고 generate로 재생성한다(생성 파일 편집은 다음 생성에서 지워진다).

## 2026-09-23 · uncommitted · fix(deploy): second overlay apply restarts, and refuses a live motor slice

- 변경: 바인드가 이미 있으면 `rosy-core`만 재시작한다. 모터·hardware 상태를 확인하지 못하면 풀기 전에 거절한다. 적용은 `sudo -n`이고 마커에 HEAD와 dirty를 남긴다. 네이티브는 서비스 마운트 안에서 해시를 확인한다.
- 증거: `python -m pytest test/test_core_dev_sync.py test/test_device_readback.py -q` 45 passed (2026-09-23 Windows).
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-179
- 교훈: 없음

## 2026-09-23 · uncommitted · fix(sd): fall back to the USB instance serial when Get-Disk reports none

- 변경: 같은 리더기가 다시 꽂힌 뒤 `Get-Disk`의 `SerialNumber`를 빈 값으로 보고해(관리자 `Update-HostStorageCache` 뒤에도) 시리얼로 카드를
  찾지 못했다. `UniqueId`의 USBSTOR instance ID(`USBSTOR\DISK&...\<serial>&<n>`)에 같은 시리얼이 남아 있어, SerialNumber가 비었고 USB일 때만
  그 값을 쓴다. Windows가 지어낸 ID(`<digit>&<hash>&<n>`, 4자 미만)와 USBSTOR가 아닌 ID는 쓰지 않는다. 기존 USB·크기·boot/system 검사는 그대로다.
- 증거: `test_sd_writer_contract.py`, `test_sd_write_card_entrypoint.py` 85 passed; 실제 카드로 `-PlanOnly -DiskSerial 000000000207`이
  디스크 1을 찾음 (2026-09-23 Windows).
- gate 변화: 없음
- 결정: D-173
- 교훈: 하드웨어 식별자 하나에만 기대면 드라이버가 그 칸을 비우는 순간 도구가 멈춘다. 같은 사실을 담은 두 번째 출처와 그 출처를 믿을 조건을 함께 둔다.

## 2026-09-23 · uncommitted · perf(sd): one authoritative verify — drop the raw-hash pre-pass and Imager read-back (D-180)

- 변경: `prepare-rosy-sd.ps1`이 쓰기 전에 `.img.xz` 전체를 풀어 raw SHA-256을 구하던 `--image-only` 패스를 없애고, Imager를
  `--cli --disable-verify "<image>" "<device>"`로 부른다(`--sha256` 없음). 전체 readback(`--image --device`)은 그대로이며 증거에 64자리
  `image_raw_sha256`·`device_sha256`와 양수 `bytes_verified`가 없으면 bundle 전에 멈춘다. 서명 검증·ERASE 확인·시리얼 선택·쓰기 직전
  fingerprint 재확인은 바뀌지 않았다. 2026-09-21 설계 단계 6("write verification을 끄지 않는다")을 대체한다.
- 증거: 실측 50분(005)·48분(004) = 사전 패스 약 12분 + 쓰기 약 20분 + Imager verify 약 10분 + readback. 설치된 Imager v2.0.8
  실행 파일의 옵션 테이블에서 `disable-verify` 확인. `test_sd_writer_contract.py` 등 관련 스위트 통과(2026-09-23 Windows).
  실제 카드 기록 시간은 아직 재지 않았다.
- gate 변화: 없음
- 결정: D-180
- 교훈: 나중에 더 엄격한 검사를 넣으면 먼저 있던 약한 검사를 다시 본다. 같은 사실을 여러 번 확인하는 패스는 시간만 쓴다.

## 2026-09-23 · uncommitted · fix(sd): the card writer detects its own failures, says what is on the card and resumes without rewriting (D-187)

- 변경: `prepare-rosy-sd.ps1`이 단계마다 `<log>.progress.jsonl`에 JSON 한 줄(`ts`, `stage`, `card_state`, `detail`)을 바로 flush하고,
  쓰기·readback 중에는 약 60초마다 처리 바이트를 남긴다. `Start-Process -Wait` 대신 poll loop로 Imager의 CPU·I/O 카운터를 보고,
  `-WriterStallMinutes`(기본 5) 동안 변화가 없으면 프로세스 트리를 끝낸다. xz index의 raw 크기에 닿았으면 `written-unverified`,
  아니면 `writing`이다. 서명 검증 이후 모든 실패에 `stage=… card_state=…`와 `next:` 한 줄을 붙인다(`trap` 포함).
  `-ResumeAfterWrite`(두 스크립트)는 Imager만 건너뛰고 readback·bundle·registry·receipt를 그대로 돌며, 모든 쓰기 전 검사와 receipt
  중복 거부를 유지하고 `resumed_after_write: true`를 남긴다. `verify-media-readback.py`는 압축 파일 전체(xz stream 뒤 포함)의
  `image_sha256`을 같은 패스에서 내고 서명 해시와 다르면 실패한다(리뷰 MEDIUM-1). 장치를 못 읽으면 exit 3. bundle 직전에 디스크를
  시리얼로 다시 고르고 fingerprint를 비교한다. `write-card.ps1`은 진행 파일 경로를 알리고, UAC 거부와 `.exit` 없는 종료에
  마지막 단계·카드 상태를 보고한다. runbook에 "카드 쓰기 중 문제가 생겼을 때"(진행 파일, resume 명령, 분리 실행) 추가.
  readback은 압축 해제 스레드와 순차 장치 읽기 스레드(각 queue 4, 4 MiB)를 겹치고 주 스레드가 비교·해시한다. 판정은 예전 순차 루프와 같다.
- 증거: 가짜 writer(`cmd` + `ping`)로 쓰기 중·마지막 byte 뒤 멈춤, Imager 비0, readback 불일치·장치 없음, 서명 뒤 바뀐 이미지,
  bundle 직전 디스크 변경, resume 성공·불일치·receipt 중복을 재현(2026-09-23 Windows). 실제 카드·실제 Imager 멈춤은 확인하지 않았다.
  pipeline readback은 순차 참조 구현과 9개 fixture × 장치 읽기 크기 3종에서 같은 판정. 256 MiB fixture 3.10s → 2.34s(page cache), 11.55s → 6.81s(60 MB/s 장치 흉내).
- gate 변화: 없음
- 결정: D-187
- 교훈: 오래 도는 외부 도구를 기다릴 때는 "끝났나"만이 아니라 "움직이나"를 본다. 실패 문구는 원인만이 아니라 카드에 무엇이 남았는지와 다음 명령을 말해야 복구가 싸진다.

## 2026-09-24 · uncommitted · fix(deploy): 오버레이 마커 탐지 패턴을 개명해 비밀 스캐너 오탐 제거

- 변경: `deploy/robot/core_dev_overlay.py`의 마커 민감 필드 거부 패턴 변수를 `_SECRET_KEY` → `_SENSITIVE_FIELD`로 개명(정의·사용 각 1곳, 값과 거부 로직 불변). 이름에 민감 키워드가 들어간 변수에 리터럴을 담은 call 값이 붙는 형태라 스캐너의 대입 휴리스틱에 정확히 걸렸고, `test_no_secrets_in_tracked_files`는 병합 전 `0d0e2a73`부터 초록이 아니었다 — 병합 회귀가 아니라 latent 오탐이었다.
- 증거: `python -m pytest test/test_release_boundary_guards.py -q` 63 passed. 스캐너 격리 프로브 7건 — 개명으로 오탐 해소, 심어둔 평범한 대입·call 인자 리터럴·`re.compile` 내부 리터럴은 여전히 보고(예외 추가 없음). 전체 `test/` **1620 passed·0 failed·43 skipped** (2026-09-24 Windows).
- gate 변화: 없음 — 스캐너 예외·파일명 제외 추가하지 않음. DEVICE HOLD.
- 결정: **출처만 고치고 스캐너는 무장 유지**. `re.compile`의 리터럴을 예외로 인정하면 call에 긴 리터럴을 넘기는 진짜 유출까지 가려서(`_call_holds_no_literal`이 존재하는 이유와 정면 충돌), 파일명 제외는 "제외 파일이 비밀을 숨기기 좋은 곳"이 되기에 버렸다. 값은 그대로 두고 이름만 바꿨다.
- 교훈: "이름에 민감 키워드 + 리터럴 값" 휴리스틱은 **탐지 패턴을 정의하는 코드**와 본질적으로 충돌한다 — 패턴 변수명에서 민감 키워드를 빼는 것이 스캐너를 무장 유지한 채로 해결하는 길이었다. 그리고 latent 오탐은 병합 회귀로 오인하기 쉽다: 병행 세션은 관련 시험만 돌렸기 때문에 전체 게이트가 이 건을 처음으로 빨강으로 떴다.

## 2026-09-24 · uncommitted · docs(deploy): 병합(deploy) 항목의 게이트 실측 수치 기록

- 변경: 병합(deploy) 항목의 "아래 게이트 줄에 실측 수치" 약속을 본문 고치지 않고 새 항목으로 옮겨 적는다 — HEAD에 들어간 본문은 lint가 append-only 위반으로 거부한다.
- 증거: `python -m pytest test/ -q` 전체 회귀 **1620 passed·0 failed·43 skipped** + `rosy_harness.py lint` **0 error·21 warning**(기존 baseline) — 2026-09-24 Windows. 병합 신규 15종 전부 초록. image_pipeline bash 3건 전이 실패는 격리 3 passed·파일 단위 58 passed·전량 재검 초록으로 병합 회귀 아님(병합 후 해당 경로 코드 무변경).
- gate 변화: 없음. DEVICE HOLD.
- 결정: 실측 수치는 본문 정정이 아니라 별도 append 항목으로 기록한다.
- 교훈: docs 쪽 항목과 같다 — 커밋 전에 약속을 채운다.

## 2026-09-24 · uncommitted · chore(deploy): split robot dev and verify scripts

- 변경: 벤치 오버레이는 `deploy/robot/dev/`로, 설치 확인과 readback은 `deploy/robot/verify/`로 나눴다. `install-pi.sh`, Windows 배포 스크립트, 현재 운영 문서와 시험의 경로를 같은 변경에서 고쳤다. 제품 유닛은 `native/`에 남겼다.
- 증거: `python -m pytest test/test_core_dev_sync.py test/test_device_readback.py test/test_rosy_motor_udev.py test/test_windows_connection_evidence.py test/test_pinky_user_validation.py test/test_folder_layout.py -q` 73 passed (2026-09-24 Windows).
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-186
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(sd): readback failures keep the verifier's reason and tell I/O from bad data (D-187)

- 변경: 005 재기록 실패 로그에는 `WRITE FAILED: full media readback verification failed`만 남았다. PowerShell 5.1 transcript는 native
  프로그램의 stderr를 담지 않는다. `verify-media-readback.py --error-json`이 `error`·`kind`(`io`, `mismatch`, `image`)·`bytes_verified`를
  쓰고, `prepare-rosy-sd.ps1`이 그 이유와 검증된 바이트 수를 실패 문구·진행 파일 `detail`·로그에 옮긴다. 장치 OSError와 짧은 읽기는
  I/O(다시 꽂거나 다른 리더기로 `-ResumeAfterWrite`), 불일치는 나쁜 데이터(재기록, 반복되면 카드 교체), xz 압축 해제 실패는 릴리스 재다운로드.
- 증거: 불일치·짧은 카드·없는 장치·잘린 xz의 error 파일과, 불일치·짧은 카드 이유가 Fail 문구와 진행 파일에 남는 writer 테스트(2026-09-24 Windows).
  실제 카드의 중간 분리는 재현하지 않았다.
- gate 변화: 없음
- 결정: D-187
- 교훈: 실패 이유가 로그까지 오는 경로를 테스트로 고정한다. 하위 도구가 이유를 말해도 상위 로그가 그 스트림을 버리면 없는 것과 같다.

## 2026-09-24 · uncommitted · feat(sd): the card writer runs without an expert watching it (D-188)

- 변경: `write-card.ps1 -Detach`가 관리자 창을 따로 띄우고(UAC 한 번, `-NoExit`) 바로 돌아오며 로그·진행 파일·`.exit`·상태 명령을
  출력한다. launcher가 진행 파일을 운영자 소유로 먼저 만들고 `launch` 줄을 쓰며, UAC 거부는 `failed`/`untouched`와 `next`로 남는다.
  새 `card-write-status.ps1 -LogPath <log> [-Json]`은 승격 없이 단계·카드 상태·바이트·실측 속도·단계/전체 ETA·마지막 줄 나이·
  `STALLED`·결과와 `next`를 보인다. readback은 감시되는 프로세스로 돌고, heartbeat 바이트가 `-ReadbackStallMinutes`(기본 5) 동안
  그대로면 verifier를 끝내고 `written-unverified`·`kind io`·resume으로 실패한다. verifier도 `--stall-seconds`로 exit 3.
  ERASE 확인 전 `preflight` 단계가 카드 앞 128 MiB를 읽기 전용으로 읽어 속도를 재고 쓰기·readback 시간을 예측하며, 10 MB/s 미만이면
  경고하고 비대화형 실행은 `-AcceptSlowMedia`를 요구한다. plan에 카드 `disk_signature`·`disk_guid`를 남겨 같은 리더기의 다른 카드를
  ERASE 전에 멈추고, resume은 장치 MBR signature가 이미지의 것과 같아야 한다. boot 파티션 파일 비교로 넘어가도 reserved 영역
  (FSInfo 힌트 제외), FAT copy 2 대 1(FAT[1] 상태 비트 제외), backup boot sector 대 primary를 byte 단위로 비교한다.
  D-187 리뷰: `-ReadbackDevice`는 fixture 전용·receipt `readback_target`, Imager 감시는 프로세스 트리 합산·실제 디스크는 `.exe`만,
  `taskkill` 5.1 throw 제거, 끝내지 못한 Imager는 재부팅 안내, verifier queue/join 시간 제한, heartbeat OSError는 advisory,
  `bundle-writing`/`bundle-partial` 단계와 bundle이 있는 카드의 resume 거부.
- 증거: named pipe 가짜 카드(`test/sd_pipe_card.py`)로 매달린 readback 정지와 느린 readback 완주, 자식이 I/O를 하는 가짜 writer,
  사전 측정·느린 매체·카드 신원·resume 거부, detach·UAC 거부 기록, 상태 명령 8가지 상황(텍스트·JSON), boot 비파일 영역 1 byte 반전
  5종(2026-09-24 Windows). 실제 카드·실제 UAC·실제 Imager 트리는 확인하지 않았다.
- gate 변화: 없음
- 결정: D-188
- 교훈: 오래 도는 작업의 "언제 끝나나"는 짐작이 아니라 같은 장치에서 잰 속도와 실제로 늘어나는 바이트로 답한다. 감시는 도구 안과 밖
  두 겹으로 두고, 느리지만 움직이는 작업을 죽이지 않는 것이 멈춤 감지만큼 중요하다.

## 2026-09-24 · uncommitted · fix(sd): D-188 review

- 변경: 이 릴리스의 MBR signature를 가진 카드는 두 조건을 모두 만족할 때만 받아들인다. `rosy-provision/`이 없어야 하고,
  같은 plan으로 Imager 쓰기를 시작한 진행 파일이 있어야 한다(첫 진행 줄에 `plan`을 기록). 그렇지 않으면 `untouched`로 멈춘다.
  fixture 모드: `.exe` writer 거부, `\\.\`·`\\?\` readback 장치 거부, receipt `fixture: true`.
  `write-card.ps1`은 `-LogPath`·`-RpiImager`(와 구분자가 있는 `-PythonExe`)를 콘솔 위치 기준 절대 경로로 바꾼다.
  readback 감시는 heartbeat가 없을 때 verifier의 `ReadTransferCount`도 진행으로 본다.
  probe는 `device_mbr_read`와 `"00000000"`을 보고하고, ERASE 뒤 재확인도 카드 첫 섹터를 다시 읽는다.
  verifier worker `close()`는 항상 시간 제한이 있다. 시간 안에 끝나지 않은 probe는 읽은 양으로 속도를 내 느린 매체 관문을 탄다(`-ProbeSeconds`).
- 증거: 끝난 카드·이전 쓰기 없는 카드 거부, 이전 쓰기가 있으면 재기록, fixture 경계 3종, heartbeat가 늦어도 읽기가 이어지는 readback,
  probe 시간 초과의 느린 매체 처리, 0 signature·원시 섹터 우선, 상대 경로, bounded close(2026-09-24 Windows).
- gate 변화: 없음
- 결정: D-188
- 교훈: "이 카드가 맞나"의 예외 경로(이미 우리 이미지가 있음)는 가장 흔한 사고 경로이기도 하다. 예외를 열 때는 그 예외가
  무엇으로만 생기는지(이 plan의 이전 쓰기)를 증거로 좁힌다.

## 2026-09-24 · uncommitted · fix(native,image): D-189 first real boot of 005 — unit sandboxes, CORE HOME, pinned CORE Python runtime

- 변경: 005 첫 실기 부팅에서 CORE를 막은 결함 네 개를 제품에 반영했다. (D1) `rosy-release-recover`에 `StateDirectory=rosy/releases`,
  `ReadWritePaths=/opt/rosy`. (D2) CORE Python 런타임 14개(pydantic 2.13.5·pydantic-core 2.46.5·fastapi 0.141.1·starlette 1.6.0·
  uvicorn 0.52.4·websockets 17.1 + 폐포 8개)를 `deploy/image/device-python-requirements.txt`에 휠 해시로 고정하고, 이미지는 rosdep 뒤
  `/usr/local`에, CI·arm64 리허설은 같은 파일로 깐다. `inputs.lock.yaml` `python_runtime`이 파일 해시를 고정. (D3) `rosy-core`
  `HOME=/var/lib/rosy/core`, `rosy-io`·`rosy-navigation`도 자기 state 디렉터리를 HOME으로. (D4) `rosy-core`의 `StateDirectory=rosy`와
  `ReadWritePaths=/var/lib/rosy`를 `rosy/core`와 `/run/rosy`로 좁히고, `tmpfiles-rosy-state.conf`가 `/var/lib/rosy` root 0755, 지도 디렉터리
  `rosy-io:rosy-core 2750`, 005 카드의 root 전용 디렉터리 소유 복구를 맡는다. 가드: 정적 샌드박스 계약(A), 이미지 안 CORE import probe(B).
- 증거: 새 계약 시험은 005 unit 파일에서 9건 적색, 수정본에서 녹색. 관련 스위트 통과(2026-09-24 Windows, 수치는 커밋 메시지). 복구 쓰기 범위
  시험 2건은 WSL Linux에서도 통과(저널 재생은 symlink가 되는 host만). 요구 파일은 aarch64·x86_64 각각 `pip download --require-hashes`로
  14개 전부 확인. probe는 WSL(Jazzy, 비빌드 소스 트리)에서 CORE 진입점·늦은 import·상위 고정 6개를 통과했고(미빌드 `interfaces`와 WSL 폐포 3개 불일치만 보고), 이미지 chroot 실행은 다음 빌드가 처음이다.
- gate 변화: 없음. 재빌드 이미지의 실기 부팅(응급 조치 없이 `CORE_READY`)이 D1-D4를 닫는다
- 결정: D-189 (작성 시 D-183이었으나 main의 D-183과 겹쳐 재번호)
- 교훈: [unit의 샌드박스·HOME·Python 의존성은 제품의 일부다](../docs/solutions/workflow-issues/units-never-run-under-their-sandbox-2026-09-24.md)

## 2026-09-24 · uncommitted · fix(native,image,ci): D-189 review — no startup hooks in a writable HOME, release/image Python runtime match, probe as the unit

- 변경: 독립 리뷰(CRITICAL·HIGH 없음, MEDIUM 2, LOW 5) 반영. (M1) HOME이 쓰기 가능한 `rosy-core`·`rosy-io`·`rosy-navigation`은
  `bash --noprofile --norc -c`로 시작하고 `PYTHONNOUSERSITE=1` — `~/.profile`·`~/.local`·`usercustomize`가 서명 릴리스 앞에서
  돌 수 없다. (M2) 이미지가 `/usr/local/share/rosy/python-runtime.sha256`, 릴리스가 서명된 `python-runtime.sha256`을 갖고
  `native_release.py` activate·rollback이 불일치·미선언을 `NATIVE_PYTHON_RUNTIME ... reflash with a matching image`로 거부한다
  (매니페스트 스키마는 그대로, recover는 검사 안 함). (L) customizer pip `umask 022`, probe를 `setpriv`로 rosy-core·그 HOME·
  runtime.env 조건에서 실행, CI는 lock 먼저·시험 도구는 lock 제약으로, 복구 저널 `StateDirectoryMode=0700`,
  `z /var/lib/rosy/maps/*`, 계약 시험의 DynamicUser·early-unit tmpfiles·control import 처리, ADR에 005 제자리 갱신 카드 재기록과
  알려진 한계.
- 증거: 새 hook·저널 계약 시험은 이전 unit에서 5건 적색, 런타임 동일성 시험은 이전 `native_release.py`에서 4건 적색, 수정본에서 녹색.
  관련 스위트 통과(2026-09-24 Windows, 수치는 보고서). 시험 도구 설치가 lock 제약으로 해석되는지 `pip --dry-run`으로 확인.
- gate 변화: 없음
- 결정: D-189
- 교훈: 쓸 수 있는 HOME은 시작 훅이다 — 로그인 셸과 user site를 같이 끈다 (교훈 문서에 추가)

## 2026-09-24 · uncommitted · docs(adr): D-190 vendor-parity boot display plan (LCD, buzzer, battery)

- 변경: D-190과 실행 계획 `docs/plans/2026-09-24-vendor-parity-boot-display.md`를 추가했다. 기준을 공식 Pinky Pro 동작으로 두고,
  S0 공식 이미지 증거(LCD 주체·GPIO 라이브러리·백라이트·부저 핀·배터리 계산) → S1 D-181 장치 편입 → S2 표시 unit·이미지·가드 →
  S3 손 설치 없는 실기 검증 순서를 고정했다. 장치 즉석 수정은 증거 수집용일 때만 하고 ADR에 기록한다. 코드 변경 없음.
- 증거: 2026-09-24 장치 관찰 — 재부팅 23.5 s, 부팅 표시 30 s 지연(런타임 뒤 판정 unit으로 t+67→t+45 s), ADC 배터리 8.67 V,
  LCD 드라이버는 공식과 동일, 장치에서 한 번 그린 LCD는 보이지 않음(원인 미확정).
- gate 변화: 없음
- 결정: D-190
- 교훈: 장치에서 즉석으로 고치면 공식 동작과 같은지 판단할 근거가 남지 않고 다시 구우면 사라진다. 증거를 먼저 모은다.

## 2026-09-24 · uncommitted · docs(adr): D-191 device readiness matrix and first real-device evaluation

- 변경: D-191과 평가표 `docs/validation/pinky-pro-evaluation-2026-09-24.md`(20행)를 추가했다. 코드 변경 없음.
- 증거: rosy-pinky-e4us 읽기 전용 검사 — `/dev/ttyAMA4`·`/dev/rosy-motor` 없음(config.txt에 uart4 overlay 없음), `sllidar_ros2`·
  `dynamixel_sdk`·`rosylib` 없음, `rosy-io` unit 미설치, 이미지 경로에 API 초기 토큰 발급 없음, ADC 배터리 8.67 V, 카메라 센서 미열거.
- gate 변화: 없음
- 결정: D-191
- 교훈: Docker 설치 경로에서 서명 이미지 경로로 옮길 때, 이전 경로가 암묵적으로 설치하던 것(overlay·SDK·외부 패키지·토큰)의 목록을 먼저 만든다.

## 2026-09-24 · uncommitted · feat(sd,first-boot): per-card CORE API administrator credential (D-191, US-009)

- 변경: 실기 평가(2026-09-24, `docs/validation/pinky-pro-evaluation-2026-09-24.md` 매트릭스 6행)에서 서명 이미지 경로 카드가 API 자격을 하나도 갖지 않아 CORE가 모든 인증 경로에 401을 돌려줬다. `prepare-rosy-sd.ps1`이 카드마다 CORE `generate_token` 형식(32바이트 URL-safe) 값과 `new_token_id` 형식 id를 발급해 DPAPI 저장소 `%LOCALAPPDATA%\Rosy\api\<device>.credential.xml`(UserName=id)에 두고 끝에 stderr로 한 번 보여준다. 번들 `core_api.record`는 CORE 저장 레코드(`id`, `role: administrator`, `sha256`, `label`, `created_at`)만 싣고, 영수증은 `personalization.core_api`에 id와 16-hex 다이제스트 지문만 남긴다. 스키마·`personalization.py`·`create-provision-bundle.py`는 선택 필드 패턴을 따른다. first boot는 레코드를 `/var/lib/rosy/core/.rosy/rosy.yaml`(D-189 unit의 `HOME`, `ROSY_CONFIG` 없음 → `core_common.config`가 읽고 대시보드가 쓰는 파일)에 mkstemp 원자 쓰기로 병합한다: 다른 키·다른 레코드 유지, 같은 id·digest는 교체, 소유 `rosy-core`, 파일 0600, 디렉터리 0750, 재실행 동일 바이트. 역할 이름은 CORE의 `administrator`(`admin`은 CORE가 viewer로 떨어뜨린다). 재기록(`-ReprovisionReceipt` 포함)은 저장소 값을 재사용한다. overlay의 `auth.tokens` 목록이 기본값 목록을 통째로 대체하므로 이 카드에서는 공용 `rosy-dev-*` 자격이 막힌다.
- 증거: `python -m pytest test/test_sd_api_token.py` (스키마·영수증·스캐너·병합·멱등·CORE TestClient 200/401·대시보드 쓰기 후 유지), writer 계약 3건 추가(발급·DPAPI·번들 digest만·plan/영수증/progress 평문 없음·재기록 재사용). POSIX 소유·모드·unit HOME 시험은 Windows에서 skip — Linux 호스트 실행 필요.
- gate 변화: 없음. DEVICE HOLD 유지 — 실제 카드 first boot에서 파일 소유·모드와 대시보드 로그인 확인이 남음
- 결정: D-191
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(sd,first-boot): US-009 security review (D-191)

- 변경: 보안 리뷰(CRITICAL·HIGH 없음, MEDIUM 1, LOW 3) 반영. (M1) first boot는 `rosy-core` 소유 HOME 경로를 루트에서 `O_DIRECTORY|O_NOFOLLOW` fd로 한 칸씩 열고 `fstat`·`fchmod`·`fchown`, `rosy.yaml`은 `O_NOFOLLOW|O_NONBLOCK`로 읽어 `S_ISREG` 요구, 임시 파일은 `O_CREAT|O_EXCL|O_NOFOLLOW`로 만들고 `os.replace(src_dir_fd=, dst_dir_fd=)` 뒤 디렉터리 fsync. 경로 어디든 symlink·비정규 파일이면 HOLD, 대상은 그대로. (L2) overlay에 이 카드 id가 아닌 자격(다른 id, 레거시 평문 맵 포함)이 있으면 HOLD — 병합하지 않는다. (L3) `core_api`는 번들 필수(스키마 `required`, `validate_provision_bundle`, `create-provision-bundle.py` EXPECTED); 없으면 first boot HOLD. (L4) DPAPI 저장소 user name을 `<id>|<device_uid>`(AP는 `<device>|<device_uid>`)로 묶고 다른 uid면 카드에 손대기 전 실패, uid 없는 옛 저장소는 한 번 받아 uid로 다시 쓴다; 두 자격은 이제 pre-flight 전에 읽는다. 사용성: 비분리 elevated 창은 닫히고 stderr 한 줄은 transcript에 없으므로 `write-card.ps1`이 성공 시 로그 끝에 `Import-Clixml` 읽기 명령을 남기고, progress `done`의 next도 저장소 경로를 가리킨다(값은 어디에도 안 씀).
- 증거: WSL(Ubuntu, Python 3.12)에서 symlink `core`·`.rosy`·`rosy.yaml`, FIFO overlay, 소유·모드, unit HOME 시험 포함 녹색; Windows 스위트 수치는 보고서.
- gate 변화: 없음. DEVICE HOLD 유지
- 결정: D-191
- 교훈: 없음
- 미결(다른 스토리): `rosy-dev-*` 차단은 overlay 목록 대체에만 기대므로 overlay가 비거나 `auth.tokens`를 잃으면 되살아난다. 기기 기본값에서 `rosy-dev-*` 제거 또는 native runtime에서 CORE가 거부하는 심층 방어가 남음 (runbook에도 기록)

## 2026-09-24 · uncommitted · feat(image,bringup): D-192 hardware runtime in the image (US-003/004/005)

- 변경: (US-003) `rosy-boot-status-ready.service`를 `After=rosy-runtime.target rosy-core.service`(의존 없음)로 추가해 이미지가
  설치·활성화한다. (US-004) customizer가 `configure-uart-pi5.sh --image-root`로 `config.txt` `[all]`에 `dtoverlay=uart4-pi5`를 넣는다.
  같은 스크립트의 vfat 쓰기는 chmod 대신 rename으로 바꿨다. 검사기가 overlay와 udev 규칙을 본다. (US-005) `sllidar_ros2`를 lock
  (`34300099…`, 아카이브 SHA-256)으로 고정해 hardware-deps 단계가 받고 오프라인 payload 빌더가 빌드한다. `dynamixel-sdk 3.8.4`·
  `pyserial 3.5`를 `device-python-requirements.txt`에 해시로 더해 D-189 런타임 검사가 덮는다. `rosylib.Battery`(공개 ADC 프로토콜,
  CORE 곡선 복사), ADC `flock` 소유 규칙, bringup `drive_enabled`(무동작: torque off, `cmd_vel` 미구독, `motor/ready` false)를
  넣고 `rosy-io`의 기본으로 했다. `rosy-io`·`rosy-navigation`을 overlay에 설치(미활성)하고 io probe가 chroot에서 확인한다.
- 증거: 관련 host 스위트 통과(2026-09-24 Windows, 수치는 보고서). `configure-uart-pi5.sh` 이미지 모드는 Git Bash로 실제 실행.
  휠 해시는 cp312 aarch64·x86_64 `--require-hashes` 다운로드 16개, sllidar 아카이브 해시는 독립 다운로드 2회 일치.
- gate 변화: 없음. 이미지 빌드와 실기 확인(D-192 "실기 수용 확인" 1-9)이 남았다
- 결정: D-192 Proposed
- 교훈: 이미지가 굽지 않는 retrofit 스크립트는 장치에만 있는 설정을 만든다 — 이미지와 장치가 같은 스크립트를 부르게 한다

## 2026-09-24 · uncommitted · fix(image,bringup): D-192 review

- 변경: (MEDIUM) 벤더 해시 고정: hardware-deps 단계는 `sllidar_ros2` 아카이브를 그대로 두고, payload 빌더가
  `prepare-vendor-source.sh`로 lock 해시를 다시 확인해 새 임시 디렉터리에 풀고 루트의 `sllidar_ros2` 하나만(여분·다른 이름 거부)
  rosdep·colcon에 넘긴다. (LOW) `drive_enabled` read-only, `ROSY_IO_DRIVE_ENABLED`는 `ExecStartPre`로 `true`/`false`만(그 밖은 78로
  기동 실패), `battery_publisher` 버스 재시도(fail-closed), `sensor_adc` C++ flock, ready unit `TimeoutStartSec=10`과
  `rosy-boot-status.py` 실행 잠금(`/run/rosy-boot/.run.lock`), 검사기가 기반 `config.txt`의 `enable_uart=1`·`dtparam=i2c_arm=on`
  확인, chroot rosdep `--skip-keys sllidar_ros2`, 장치 `config.txt.rosy-backup` 복구 절차를 D-192에 기록. source-grep 시험을
  동작 시험(stub rclpy 노드, fake fd IR 독자, settle 순서)으로 바꿨다. `origin/main 7a55ee1b`(D-190·D-191)로 rebase.
- 증거: 관련 host 스위트 통과(2026-09-24 Windows, 수치는 보고서), 실행 잠금 동시성 시험은 WSL에서 통과, 하네스 lint 0 error.
- gate 변화: 없음
- 결정: D-192 Proposed
- 교훈: 풀어 둔 트리 옆의 해시 표시는 내용을 증명하지 않는다 — 해시는 빌드가 실제로 읽는 바이트에 건다

## 2026-09-24 · uncommitted · ci: gate the hardware safety tests that CI never ran (D-192)

- 변경: CI는 `src/core/core`·`fleet`·`gz_sim`·루트 `test/`만 돌려 `src/hardware/*/test`·`src/apps/*/test`가 한 번도 게이트되지 않았다.
  무동작 모드(토크 꺼짐·cmd_vel 미구독)·ADC 버스 잠금·배터리 곡선 시험을 새 스텝 "Test (hardware safety …)"로 올렸다.
- 증거: WSL Linux에서 같은 명령 454 passed. 나머지 패키지 시험의 기존 적색(Linux): bringup/led/emotion ament flake8·pep257,
  control `test_localization_gate`·`test_os_camera_graph`·`test_os_watch_graph`, games `test_games_cli` 4건 — 이 변경 밖, D-191 후속 과제.
- gate 변화: CI에 하드웨어 안전 스텝 추가
- 결정: D-192
- 교훈: 시험을 추가할 때 CI가 그 폴더를 실제로 돌리는지 확인한다. 이 저장소에서는 루트 `test/`로 옮기면 D-184가, 패키지로 옮기면 CI가 막는다.

## 2026-09-24 · uncommitted · feat(native,image): boot display on the LCD and buzzer (US-006, D-190 S1-S2)

- 변경: `rosy-boot-display.service`(사용자 `rosy-display` 962, `DevicePolicy=closed` + `spidev0.0`·`gpiochip4`·`i2c-1`,
  `ProtectSystem=strict`, `PrivateNetwork`, HOME·`LG_WD`는 `StateDirectory=rosy/display`)와 상주 루프
  `rosy-boot-display.py`(1 s 폴링, 바뀔 때만 다시 그림, 배터리 15 s, `rosylib.Battery` 직접, gpiochip4 label 확인, 장치 없으면
  한 번 기록). 부저 BCM 22 기본 꺼짐(`/etc/rosy/boot-display.env`로 켬), `CORE_READY` 1회·`FAILED` 3회. `rosy-network.py`가
  AP를 연 동안만 `/run/rosy-boot/ap-display.txt`(SSID·비밀번호 두 줄, root:rosy-display 0640)를 쓰고 지운다. 이미지: apt
  `python3-spidev`·`python3-rpi-lgpio`·`python3-numpy`·`python3-pil`·`fonts-dejavu-core`, 사용자·그룹, `99-rosy-display.rules`,
  unit enable, chroot `probe-display-runtime.py`(rosy-display로), 검사기(enable·udev·dpkg·`dtparam=spi=on`). D-181 편입:
  `board.yaml` `boot_display`, 장치 표면 변이 시험, 샌드박스 계약 선언. emotion은 벤치 전용이라 `Conflicts=` 없음(가드 시험).
- 증거: 관련 host 스위트 936 passed, 11 skipped(2026-09-24 Windows). AP 파일 0640·그룹 확인은 WSL POSIX에서 통과.
  장치 표면 변이: `rosy-io.service`에 `spidev0.0` 추가·표시 unit의 `i2c-1`을 `i2c-0`으로 바꾸면 적색, 되돌리면 녹색.
- gate 변화: 없음. 이미지 빌드(probe 첫 실행)와 D-190 S3 실기 확인이 남았다
- 결정: D-190 Proposed(S1·S2 완료), D-181 편입 기록 추가
- 교훈: 백라이트가 소프트웨어 PWM이면 "그리고 끝나는" 표시는 없다 — 표시 장치는 상주 프로세스와 한 쌍으로 설계한다

## 2026-09-24 · uncommitted · fix(native,image): US-006 security review

- 변경: (M1) 부저 핀은 허용 목록 {4,5,6,16,17,20,21,22,23,24,26}만, `board.yaml`에 목록과 헤더 선 주인(0-3, 7-15, 18, 19, 25, 27).
  (M2) `battery_adc`를 실제 허용(`rw-any-address`, `advisory-flock`)으로, D-181·D-190에 남은 위험과 커널 패널 드라이버 후속.
  (L1) gpiochip label을 매 시도 읽고, 못 읽으면 패널을 건드리지 않고 재시도. (L2) 패널 노드가 있는데 못 그리면 1로 끝남,
  `/dev/spidev0.0`이 없으면 0. probe는 "Raspberry Pi" `RuntimeError`만 허용하고 rpi-lgpio의 `RPI_LGPIO_CHIP` 읽기를 확인
  (noble 0.5-0ubuntu1 소스로 확인, shim 없음). (L3) 장치 표면 가드: `char-spi`·`char-i2c`·`char-gpio`, drop-in, `[Service]`만
  파싱, 표시 unit의 마지막 `DevicePolicy=closed`, gpio/spi 그룹 비 root unit은 closed 또는 `PrivateDevices`, 변이를 `[Service]`에.
  (L4) POSIX 시험 `skipif`, fchown·fchmod가 빈 파일 위치 0에서 불리는지, 오래된 AP 파일을 `main --once`가 지우는지 동작 시험.
- 증거: 보고서 수치(Windows host 스위트, WSL POSIX)
- gate 변화: 없음
- 결정: D-190·D-181 갱신
- 교훈: 노드 단위 장치 허용은 프로그램이 쓰는 선보다 넓다 — 허용과 사용을 따로 적고, 좁히는 길을 열린 항목으로 남긴다

## 2026-09-24 · uncommitted · fix(image): run the display probe where the unit runs (LG_WD, working directory)

- 변경: release `2026.09.24-007` 빌드가 `DISPLAY_PROBE_FAIL import lgpio: FileNotFoundError`로 멈췄다. lgpio는 import 때
  `LG_WD` 또는 작업 디렉터리에 `.lgd-nfy*` 파일을 만든다. unit은 StateDirectory(`/var/lib/rosy/display`)를 HOME·LG_WD·
  WorkingDirectory로 쓰지만, probe는 chroot의 `/`(rosy-display가 쓸 수 없음)에서 LG_WD 없이 돌았다. 이미지가 그 상태 디렉터리를
  unit과 같은 소유·모드(962:962 0750)로 만들고, probe에 unit과 같은 LG_WD·RPI_LGPIO_CHIP·작업 디렉터리를 준다.
- 증거: noble `python3-lgpio 0.2.0.0-0ubuntu3`·`python3-rpi-lgpio 0.5-0ubuntu1`를 풀어 WSL에서 재현 — cwd `/`·LG_WD 없음 → 같은
  `FileNotFoundError: '.lgd-nfy-3'`, LG_WD가 없는 디렉터리 → 같은 오류, 쓰기 가능한 상태 디렉터리 → `import ok`(`.lgd-nfy0` 생성).
  `test_boot_display.py` 등 215 passed.
- gate 변화: 없음(007 빌드 실패, 다음 릴리스에서 probe 통과 확인)
- 결정: D-190
- 교훈: 서명 전 probe가 제 역할을 했다. probe의 환경은 unit에서 그대로 복사하고, 그 대응을 시험으로 고정한다.

## 2026-09-24 · uncommitted · docs(adr): D-193 login code on the robot screen and credential lifecycle

- 변경: D-193을 추가했다. LCD에는 장기 토큰이 아니라 root가 만드는 8자 일회용 코드(10분, scrypt 검증자, 기본 operator)를 띄우고,
  `POST /api/v1/auth/pair`로 브라우저 전용 만료 토큰을 받는다. 장치 기본값의 `rosy-dev-*` 토큰을 없애 fail closed로 한다. 코드 변경 없음.
- 증거: 2026-09-24 대시보드 점검 — 카드 005에서 `rosy-dev-*`가 LAN에서 통함, 대시보드는 역할을 감사 로그 403으로 추측함.
- gate 변화: 없음
- 결정: D-193
- 교훈: 로그인 편의를 위해 장기 비밀을 화면에 띄우는 대신, 물리 접근의 증표를 짧고 일회용인 값으로 만든다.

## 2026-09-24 · uncommitted · fix(dev): native CORE overlay reloads units and proves every bind is mounted (D-179)

- 변경: 실기(`rosy-pinky-e4us`, release 005)에서 `sync-core-dev.ps1 -Backend native`가 성공으로 끝났지만 오버레이는 적용되지 않았다.
  (1) drop-in을 쓴 뒤 `daemon-reload` 없이 재시작해 `NeedDaemonReload=yes`인 채로 bind가 없었다. (2) 확인이 `core/__init__.py` 해시 하나였고,
  그 파일은 이미지와 main에서 같아 거짓 통과했다. 이제 reload 후 재시작하고, 실행 중 CORE의 `/proc/<pid>/mountinfo`에 모든 bind 대상이
  있어야 통과한다(`/opt/rosy/current` 심볼릭 링크는 커널이 풀어 기록하므로 resolve해 비교).
- 증거: 고친 도구로 main(05bd4a0)의 CORE를 실기에 올림 — mountinfo에 7개 bind, `rosy-core` active, API 200. `test_core_dev_sync.py` 34 passed.
- gate 변화: 없음(장치는 dev 마커 HOLD 상태)
- 결정: D-179
- 교훈: "적용됐다"는 확인은 바뀐 것만 볼 수 있는 증거로 한다. 바뀌지 않았을 수도 있는 파일의 해시는 증거가 아니다.
## 2026-09-24 · uncommitted · feat(auth,native,image): D-193 S1·S2 login code issuer and token lifecycle

- 변경: (S1 CORE) 토큰 레코드에 `expires_at`·`source`(`card`|`manual`|`pair-physical`|`pair-admin`|`legacy`)·`paired_via`.
  만료 토큰 401, 저장 때 정리. 마지막 관리자 규칙은 만료 없는 administrator만 센다. 새 `api/v1/auth.py`: `POST auth/pair`
  (인증 없음, 1 KiB, RFC 1918·루프백만, IP 60 s 5회·전체 30회 → 429 `Retry-After`, 코드별 틀린 시도 5회 폐기,
  scrypt N=2^14 스레드풀, `boot_id`+monotonic 만료, `/run/rosy-boot/login-code.json`을 O_NOFOLLOW·정규 파일로 매번 읽음,
  `no-store`), `whoami`, `logout`(pair-*만, 그 밖 409), `enrollment-codes`(관리자, 5분, 메모리). `PATCH system/tokens/{id}`.
  CORE는 `/run/rosy/login-code-state.json`에 `{code_id, state}`만 쓴다. `rosy_default.yaml`의 `auth.tokens: []`,
  개발 토큰은 `rosy_dev_auth.yaml`(`ROSY_DEV_AUTH=1`, 장치 모드 제외). 장치 모드(`ROSY_DEPLOYMENT=device`: runtime.env
  템플릿·first boot·`rosy-core.service`)는 개발 다이제스트·평문을 거부하고 `auth.credentials_refused`를 낸다. first boot는 카드
  레코드를 `source: card`로 설치. WebSocket 첫 메시지 인증(`?token=`은 한 릴리스 유지). API Ref v1.19 (US-010의 v1.18 위).
  (S2 root) `rosy-login-code.py`(데몬+CLI, `.login.lock` flock): 첫 CORE_READY에 한 번 발급(`login.boot_code`),
  검증자 root:rosy-core 0640, LCD 줄 root:rosy-display 0640(D-190 `_write`), 콘솔 `login.issue` 0600 + `agetty --reload`,
  CORE 신호를 엄격히 읽어 자기 `code_id`만 지움, 만료 때도 지움, 폐기면 LCD에 1분간 "Login code burned".
  `rosy-login-code.service`(root, PrivateNetwork, AF_UNIX, ProtectSystem=strict, `/run/rosy-boot`만 쓰기). `rosy_config`의
  `login.boot_code`, `defaults.yaml` `login`, `rosy-config-apply`가 `login-policy.json`을 씀. LCD·`render_boot`에 CORE_READY
  전용 로그인 줄. 이미지: unit enable, `/usr/local/sbin/rosy-login-code`, `/etc/issue.d/60-rosy-login.issue`, 진입점 probe,
  `verify-mounted-image.py`가 페이로드 `rosy_default.yaml`의 토큰·unit·링크 누락을 막는다.
- 증거: host pytest(Windows)·WSL POSIX 시험 — 보고서 수치. 장치 미검증(평가표 6a-6g).
- gate 변화: 없음(S4 실기 전)
- 결정: D-193
- 교훈: 템플릿 `rosy-runtime.env`는 first boot가 쓰지 않는다 — 장치 환경 변수는 first boot `_runtime_env`와 unit 양쪽에 넣어야 실제 카드에 닿는다.

## 2026-09-24 · uncommitted · fix(core,native): D-193 security review

- 변경: (M1) CORE가 자기 `login-code-state.json`을 엄격히 다시 읽어 재시작 뒤에도 쓴·폐기한 코드를 거부하고, 틀린 시도를
  `failing`/`attempts`로 남긴다. `rosy-core.service` `RuntimeDirectoryPreserve=restart`. scrypt 동시 2개. (M2) 만료가 있는
  호출자는 `POST system/tokens`·만료 없는 administrator `DELETE`가 403, 등록 토큰 만료는 발급자 만료 이하. (L1-L7) 토큰 쓰기 락,
  WebSocket 30 s 재확인(4401), 첫 메시지 대기 소켓 16개 상한(1013), 등록 코드가 살아 있으면 실패를 그 코드에 셈, 토큰 생성
  응답 `no-store`, uvicorn `proxy_headers=False`, 발급자 토큰이 사라진 등록 코드 무효. D-193에 날짜 붙은 보완 노트.
- 증거: host pytest(Windows)·WSL POSIX — 보고서 수치.
- gate 변화: 없음
- 결정: D-193 보완(2026-09-24 보안 리뷰)
- 교훈: 일회용 값의 "소비됨"은 그 값을 검증하는 프로세스의 수명보다 오래 가야 한다 — 메모리만으로는 재시작이 곧 재무장이다.

## 2026-09-24 · uncommitted · docs(adr): D-197 Docker exits the product artifact chain

- 변경: `docs/adr/D-197-docker-exits-the-product-chain.md` 추가, ADR Log 표 D-197 행. 제품 경로의 신규
  Docker/OCI 의존 금지, OCI·Compose 체인의 폐기 트리거(native payload ARTIFACT 통과 시 한 변경 정리),
  계약 테스트 고정 대상 이동 뒤 Dockerfile/compose 삭제라는 순서 계약, D-179 벤치 compose의 잔류 조건을
  기록했다. 코드·워크플로·계약 테스트 본문은 바꾸지 않았다.
- 증거: `python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q`;
  `python tools/harness/rosy_harness.py lint`
- gate 변화: 없음
- 결정: D-197 (D-196은 2026-09-24 멀티로봇 구조 개편 계획이 먼저 선점했다 — 커밋 4c496c24)
- 교훈: 없음

## 2026-09-24 · uncommitted · feat(dashboard,deploy): D-193 S3 code login, whoami badge, first-message WebSocket, credential rotation

- 변경: 대시보드 로그인 서랍에 "로봇 화면 코드"(기본)·"API 토큰" 두 탭. 코드는 브라우저에서 정규화·알파벳·길이 확인 뒤
  `POST auth/pair`, 실패 문구는 401(틀림·사용·만료·발급 없음 한 문장)·폐기(`error.detail.burned`, 서버 추가)·429(`Retry-After`
  동안 버튼 끔)·403(LAN 밖)을 구분. 저장소 규칙(D-193 6): 만료 없는 토큰은 `sessionStorage`, 페어링 토큰은 "로그인 유지"일 때만
  `localStorage`(만료 지나면 삭제). 머리글 whoami 배지(역할·이름표·출처·만료)와 로그아웃(페어링만 `auth/logout`, 그 밖은
  "이 브라우저에서 잊기"). 역할은 `whoami`에서. WebSocket은 `?token=` 없이 첫 메시지 인증, 4401→whoami 확인, 4403 재시도 없음,
  그 밖 1→30 s 백오프(상태 수신 뒤에만 복귀), REST 401이면 로그아웃. 토큰 목록에 출처·만료·"이 기기".
  `deploy/sd/rotate-core-api-credential.ps1`: whoami → 추가 → DPAPI 저장 → 저장값 whoami → 옛 id 삭제, 실패 시 저장소·새 id 되돌림,
  값 미출력, HttpClient 프록시·리다이렉트 끔. API Ref v1.19 행·첫 메시지 2 s 정정, 런북, D-193 S3 노트.
- 증거: host pytest(Windows) `src/core/core/test`, `test/test_dashboard_browser.py`(ROSY_RUN_BROWSER_TESTS=1, Chromium),
  `test/test_rotate_core_api_credential.py`(Windows PowerShell 5.1 + 가짜 CORE) — 보고서 수치. 장치 미검증(평가표 6c·6g는 S4).
- gate 변화: 없음(S4 실기 전)
- 결정: D-193 S3
- 교훈: 세션을 끝내는 신호(4401)는 토큰 문제 말고도 첫 메시지 지연에서도 온다 — 소켓 닫힘 코드만 보고 로그아웃하지 말고 REST로 한 번 확인한다.

## 2026-09-24 · uncommitted · fix(dashboard,deploy): D-193 S3 security review (PR #35)

- 변경: 시험의 Bearer 파싱 줄이 비밀 스캐너에 걸리지 않게 바꿈(허용 목록 그대로). "로그인 유지"는 만료 7일 이내만
  `localStorage`, CORE 페어링 수명 상한 168 h. 로그아웃은 항상 `auth/logout`(409면 로컬만). 폐기 문구 두 경우. WebSocket
  백오프는 10 s 안정 뒤에만 복귀. 회전 스크립트: 새 토큰 `expires_at` 거부·되돌림, 교체·다시 읽기 실패 시 `.previous` 복원,
  DELETE 전 id 형식 확인, `http://` 경고와 신원 증명 경로 부재의 위협 기술.
- 증거: host pytest(Windows) `src/core/core/test`, 브라우저 시험(Chromium, ROSY_RUN_BROWSER_TESTS=1), 회전 계약 시험,
  `test_release_boundary_guards.py` — 보고서 수치. 장치 미검증.
- gate 변화: 없음
- 결정: D-193 S3 보완
- 교훈: "최대 N일" 같은 약속은 클라이언트와 서버 양쪽에서 강제한다 — 한쪽 설정만 바뀌어도 약속이 깨진다.

## 2026-09-24 · uncommitted · docs(adr): D-198 Docker operational surface retirement

- 변경: `docs/adr/D-198-docker-operational-surface-retirement.md` 추가, ADR Log 표 D-198 행. D-197이 닫은
  빌드·릴리스 체인 밖에 남은 장치 운영면(install-pi.sh의 docker.com 설치, runtime-mode.sh, 레거시 유닛,
  verify-motors/verify-pi/measure-dds-baseline/device_readback의 compose 판정, dev overlay docker backend,
  Dockerfile 부속품)의 처분을 기록했다. 안전 게이트의 native 대체는 ARTIFACT와 무관하게 지금 구현하고,
  install-pi.sh·runtime-mode.sh은 대체 없이 폐기하며, 삭제 순서는 D-197의 계약 테스트 재고정 계약을 따른다.
  코드 본문은 바꾸지 않았다.
- 증거: `python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q`;
  `python tools/harness/rosy_harness.py lint`
- gate 변화: 없음
- 결정: D-198 (D-197 후속)
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(sd,release): card writer survives what release 010's write hit on the operator PC

- 변경: (1) `deploy/release/signing.py`가 PATH에 openssl이 없을 때 Git for Windows(`usr\bin`, `mingw64\bin`)를 찾는다 —
  비관리자 PowerShell의 `prepare-rosy-sd.ps1 -PlanOnly`가 "openssl not found"로 멈췄고, 시험은 `test/conftest.py`만 그 경로를 알아 통과했다.
  (2) 첫 섹터가 전부 0인 카드를 Get-Disk는 MBR 서명 1로 보고한다(중단된 Imager 쓰기 뒤 실측, 섹터 덤프로 확인). 계획이 `00000001`을
  기록하고 pre-flight 원시 읽기가 "없음"이면 공장 공백 카드 경로(시리얼·크기, 경고)로 본다. 실제 서명을 기록한 계획은 여전히 공백 카드를 거부한다.
  (3) 관리자 쓰기 창이 QuickEdit을 끈다 — 창을 클릭하면 "Select" 상태가 되어 콘솔에 쓰는 Imager `--cli`가 0 CPU·0 I/O로 멈추고,
  stall watchdog이 8 MB 남기고 죽였다. 005의 23분 멈춤도 같은 원인으로 보인다.
- 증거: `python -m pytest test/test_sd_writer_contract.py test/test_media_readback.py test/test_release_signing.py test/test_offline_image_signer.py -q`
  243 passed. 실기: 이 브랜치의 writer로 010을 카드에 기록, `receipt-2026.09.24-010-rosy-pinky-e4us.json` `media_readback.verified: true`
  (쓰기 8분·readback 7분, 멈춤 없음).
- gate 변화: 없음
- 결정: D-187/D-188 보완
- 교훈: 시험 conftest가 환경을 고쳐 주면 실제 운영 경로의 같은 결함을 가린다 — 보정은 제품 코드에 두고 시험은 그 보정을 검증한다.
  카드 신원은 Windows 캐시와 원시 섹터가 다를 수 있으니, 실패 시 섹터를 먼저 덤프해 추측을 끝낸다.

## 2026-09-24 · uncommitted · fix(first-boot): retry the site Wi-Fi and self-heal a held first boot

- 변경: `deploy/image/first-boot/rosy-first-boot.py`의 현장 Wi-Fi 활성화가 한 번 실패하면 곧바로 `PROVISIONING_AP`로 끝나고
  `rosy-site-sta.nmconnection`을 지우던 것을 고쳤다. (1) `activate_site_wifi`: 최대 3회, 회당 `--wait 30`, 사이 15초, 합계 120초
  (단조 시계 기준) 안에서 재시도하고, 매 시도 전에 `GENERAL.STATE`로 NM autoconnect가 이미 붙였는지 확인한다. 유닛
  `TimeoutStartSec`는 90→180. (2) 예산을 다 써도 프로필은 남긴다. (3) 새 `rosy-first-boot-retry.timer`/`.service`가 부팅 150초 뒤부터
  30초마다 `--network check`(연결을 올리지 않고 상태만 확인)로 재실행하고, 성공하면 `rosy-runtime.target`을 시작하고 타이머를 멈춘다.
  이미지 payload·enable 목록에 두 유닛을 추가했다.
- 증거: 실기 저널(release `2026.09.24-010`, `rosy-pinky-e4us`): 18.7 s 활성화 시작, 44.0 s 실패 → 첫 부팅 즉시
  `site_wifi_unreachable`, LCD `FAILED:rosy-first-boot`; 77.6 s NM 재시도, 84.9 s 연결. Wi-Fi가 붙은 뒤 수동
  `systemctl start rosy-first-boot`가 PROVISIONED, 재부팅 후 CORE_READY — `apply()`는 재진입 가능. 시험:
  `python -m pytest test/test_first_boot_provisioning.py test/test_sd_api_token.py test/test_sd_ap_credentials.py test/test_sd_operator_access.py test/test_boot_state.py test/test_boot_status_indicator.py test/test_boot_blackbox.py test/test_image_customization_contract.py test/test_native_systemd_contract.py test/test_rosy_network_fallback.py test/test_network_topology_contracts.py deploy/image/test -q`
  307 passed, 10 skipped, 1 failed(`test_verify_mounted_image.py::test_inspect_passes_with_valid_image` — origin/main에서도 같은 실패, 이번 변경과 무관).
  실기 재현은 아직 없음.
- gate 변화: 없음 (SOURCE만. DEVICE 재검증 필요: 느린 핫스팟으로 첫 부팅, 잘못된 SSID로 AP 개방 후 핫스팟 복구 시 자동 PROVISIONED)
- 결정: D-176 보완 노트(2026-09-24), D-154 결정 6의 "후보 폐기"를 이 범위에서 대체
- 교훈: 한 번의 연결 실패를 영구 실패로 다루고 복구 수단(프로필)까지 지우면, 하위 계층(NM autoconnect)이 스스로 회복해도 상위가
  따라오지 못한다. oneshot의 `Restart=`는 시작 job을 붙잡아 뒤 유닛을 막으므로, 재시도는 별도 타이머로 한다.

## 2026-09-24 · uncommitted · fix(first-boot): PR #38 review — held retry changes nothing, one run at a time

- 변경: (1) `--network check`는 `complete.json`이 없고 사이트 프로필이 활성이 아니면 `apply()`에 들어가기 전에 held JSON만
  출력하고 1로 끝난다 — 30초마다 state.json·hostname·avahi 재시작·runtime.env/프로필/authorized_keys/sudoers/CORE overlay를
  다시 쓰던 것을 없앴다. 확인 전에 남겨 둔 프로필을 `nmcli connection load <path>`로 다시 읽힌다(라디오는 건드리지 않음).
  (2) `rosy-first-boot.sh`를 `flock -w 200 /run/rosy-first-boot.lock`으로 감싸고, `_write_atomic`은 같은 디렉터리의
  `tempfile.mkstemp`를 쓴다(고정 `.tmp` 이름 충돌 제거). 재시도 유닛 `TimeoutStartSec` 240.
  (3) `rosy-first-boot.service`가 성공하면(`ExecStartPost`) 재시도 타이머를 멈춘다. (4) 재시도 성공 시
  `rosy-boot-status-ready.service`도 시작해 CORE_READY를 바로 표시한다. (5) `GENERAL.STATE`가 `activating`이면 `up`을 내지
  않고 5초씩 기다린다(예산 안에서) — 2026-09-24에는 첫 부팅 1.7초 만에 NM이 이미 연결 중이었다. (6) D-154 결정 6에 D-176 노트 포인터.
- 증거: `python -m pytest test/test_first_boot_provisioning.py test/test_sd_api_token.py test/test_sd_ap_credentials.py test/test_sd_operator_access.py test/test_boot_state.py test/test_boot_status_indicator.py test/test_boot_blackbox.py test/test_image_customization_contract.py test/test_native_systemd_contract.py test/test_rosy_network_fallback.py test/test_network_topology_contracts.py -q`
  306 passed, 10 skipped (first-boot 23). held 확인은 state.json·프로필·runtime.env·hostname·CORE overlay의 mtime·내용과 파일 목록이
  그대로이고 hostnamectl/systemctl 호출이 없음을 확인한다. 실기 재현은 아직 없음.
- gate 변화: 없음
- 결정: 없음 (D-176 보완 노트 유지)
- 교훈: 주기 재시도는 "아무것도 안 바뀌었으면 아무것도 쓰지 않는다"가 기본이어야 한다 — 전체 적용 경로를 그대로 돌리면 부작용이 주기가 된다.
- 후속(미처리): fallback AP의 "업링크 있음" 규칙이 사이트 프로필 대신 아무 연결이나 인정하는 점, 재시도 동안
  `rosy-first-boot.service`가 failed로 남아 부팅 표시가 FAILED를 보이는 잡음, 재시도 유닛 샌드박스 강화.

## 2026-09-24 · uncommitted · fix(image,uart): keep the kernel console and getty off the LiDAR UART

- 변경: `configure-uart-pi5.sh`(이미지·장치 공통)가 `cmdline.txt`에서 `console=serial0|ttyAMA0|ttyAMA4[,baud]`만 지우고
  (`console=tty1`, 디버그 UART `ttyAMA10`은 유지) `serial-getty@ttyAMA0`·`@ttyAMA4`를 `/dev/null`로 mask한다. 멱등.
  `verify-mounted-image.py`는 `cmdline.txt` 누락·버스 UART 콘솔·mask 누락이면 빌드를 멈추고, `verify-pi.sh`에 `UART` 검사
  (`/proc/cmdline`, 활성 `serial-getty@ttyAMA0`)를 더했다.
- 증거: 실기 `rosy-pinky-e4us`, release 2026.09.24-010. Ubuntu `cmdline.txt`의 `console=serial0,115200`이 `enable_uart=1`에서
  `/proc/cmdline`의 `console=ttyAMA0,115200`이 되어 agetty가 RPLIDAR C1 포트를 잡았다. `sllidar_node`는
  `SL_RESULT_OPERATION_TIMEOUT`, getty 정지 뒤 `0x80008004`(커널 콘솔). 항목을 지우고 재부팅하자 getty 없음,
  `health status : OK`, DenseBoost 10 Hz. host: `python -m pytest test/test_rosy_motor_udev.py test/test_image_customization_contract.py
  test/test_pi_wifi_deployment.py test/test_device_readback.py test/test_pinky_flashable_image_contract.py test/test_pinky_user_validation.py -q`
- gate 변화: 평가표 11행 FAIL → 소스 수정. DEVICE는 현장 cmdline 수정으로 LiDAR PASS, 새 이미지로는 미확인(ARTIFACT HOLD)
- 결정: D-192 보완(2026-09-24)
- 교훈: 기반 이미지가 "이미 준다"고 본 장치 노드도 그 노드를 누가 잡고 있는지까지 확인한다. `enable_uart=1`은 포트를 만들지만
  `console=serial0`과 짝지어지면 그 포트를 콘솔에 넘긴다.

## 2026-09-24 · uncommitted · fix(image,uart): recovery console on the debug UART, strict getty masks (PR #39 review)

- 변경: 바로 위 항목의 보완. `configure-uart-pi5.sh`가 버스 UART 콘솔을 지운 뒤 복구용 시리얼 콘솔
  `console=ttyAMA10,115200`(Pi 5 디버그 3핀 UART, 로봇 버스 없음)이 없으면 앞에 넣는다(`console=tty1`은 마지막에 유지) —
  위 항목대로면 시리얼 콘솔이 하나도 남지 않았다. `verify-mounted-image.py`는 `ttyAMA10` 콘솔이 없어도 빌드를 멈추고,
  getty mask는 `/dev/null` symlink만 인정한다(일반 파일 거부). 두 임시 파일을 지우는 EXIT trap을 편집 전에 두고,
  `cmdline.txt`를 사전 검사하고, `REBOOT_REQUIRED`는 한 번만 출력한다. `verify-pi.sh`는 `serial-getty@ttyAMA0`·`@ttyAMA4`의
  활성과 masked 상태를 함께 본다. `pi5-acceptance-checklist.md`의 UART 콘솔은 디버그 UART로 명시했다.
- 증거: `python -m pytest test/test_rosy_motor_udev.py test/test_image_customization_contract.py deploy/image/test -q`
- gate 변화: 없음(평가표 11행 그대로, 이미지 미확인)
- 결정: D-192 보완(2026-09-24) 문구 갱신
- 교훈: 콘솔을 치울 때는 복구 경로가 남는지 먼저 본다. 검사기가 Windows 시험 편의를 위해 느슨해지면 실제 이미지에서도 느슨하다 —
  시험 쪽을 skip한다.

## 2026-09-24 · uncommitted · fix(harness): 과거 로그 항목 원문 복원(append-only)

- 변경: a93d5188 경로 재편이 2026-09-21 test(deploy) 항목(D-149)의 `apps/control`을 `core/control`로 고쳐 쓴 것을 원문으로 복원했다. 로그는 append-only고 역사 항목은 당시 경로를 말해야 한다. 현재 경로는 이 시점 기준 `src/core/control`이다.
- 증거: `python tools/harness/rosy_harness.py lint` — 3a17a0aa 기준 append-only 오류 소멸(커밋 뒤 HEAD 기준도 통과).
- gate 변화: 없음
- 결정: 없음
- 교훈: 경로 재편 커밋이 로그 원문을 같이 고쳐 쓰지 않는다. 하네스 lint가 잡는다.

## 2026-09-25 · 4512c897 · feat(sd): 99.9% 이상에서 멈춘 기록은 재개부터, 느린 리더 안내 (D-225)

- 변경: `prepare-rosy-sd.ps1`이 Imager 정지 시 기록량이 원본의 99.9% 이상이면 전체 재기록 대신 `-ResumeAfterWrite`를 먼저 안내한다(readback이 모든 바이트를 다시 비교하고, 덜 쓰인 카드는 bundle·receipt 전에 실패한다는 문구 포함). preflight `read_mbps < 30`이면 `reader_hint`를 progress JSON과 경고로 남긴다(실패 아님, 하한 10 MB/s 유지). `card-write-status.ps1`도 같은 안내를 낸다.
- 증거: `python -m pytest test/test_sd_writer_contract.py -q` 142 passed(99.95%에서 자른 카드로 재개 → readback 실패·기록 없음 포함); 이전 커밋 기준 SD 묶음 184 passed(2026-09-25 Windows). 독립 리뷰 MERGE.
- 실기: 같은 날 release 2026.09.25-011을 `rosy-pinky-e4us`(18)에 재기록 — Imager exit 0, readback 8,574,867,968 B verified(부트 파티션은 Windows `System Volume Information` 때문에 파일 단위 비교 371개). readback 18분은 동시 실행 작업의 CPU 경합 탓(010은 7분).
- gate 변화: 없음(MEDIA 증거만, BOOT/DEVICE HOLD)
- 결정: D-225
- 교훈: 010은 99.9%에서 멈춘 기록을 전체 재기록으로 되돌려 37분을 잃었다. 판정은 readback이 하므로 안내는 재개부터 한다. 카드 readback은 xz 압축 해제가 CPU를 써서, 기록 중에는 무거운 병렬 작업을 피한다.

## 2026-09-25 · f9e52192 · feat(robot): 서명 payload를 SSH로 보내 전환하는 `rosy-release-push.ps1` (D-225)

- 변경: `deploy/robot/rosy-release-push.ps1`이 Linux에서 만든 서명 payload tarball을 운영 PC에서 먼저 검증(`signing.py` verify, 저장소 공개키)하고 scp로 보낸 뒤, `rosy-release-unpack.sh`로 `/opt/rosy/releases/<id>`에 풀고(임시 폴더 → `mv -T`, `sync`), `activate-release.sh`와 CORE 준비 확인을 실행한다. `-Rollback`, `-PrintCommands`(원격 명령 전체를 실행 없이 출력) 지원. 풀기 전 python `tarfile`로 전 항목을 읽어 일반 파일·폴더만 허용하고(심볼릭·하드링크·FIFO·장치, 절대경로, `..`, 제어문자 거부), `--no-same-owner --no-same-permissions` 뒤 root 소유·`go-w,u-s,g-s`로 고정한다. 같은 id가 있으면 `sha256sum -c`로 다시 검증해 손상 시 `RELEASE_DAMAGED`. `-ReleaseDir` 실전송은 거부(Windows tar가 실행 비트를 잃음).
- 증거: `test_release_push_entrypoint.py` + `test_release_unpack_helper.py`(bash로 helper 실행) + `test_native_release_activation.py` + `test_robot_runtime.py` 78 passed, 1 skipped(NTFS에서 setuid 비트 확인 불가 — Linux에서 실행). 독립 리뷰 → 수정 2회 → 재검증 MERGE. 로봇 접속 없음.
- gate 변화: 없음(`UPDATE_GO` HOLD 유지 — e4us에서 activate·rollback·recover 실증 전)
- 결정: D-225
- 교훈: root로 tar를 풀면 서명이 보장하지 않는 소유자·권한·항목 종류가 그대로 들어온다. 서명 검증과 별개로 풀기 전 항목 허용 목록과 풀고 난 뒤 권한 고정이 필요하다. 첫 부팅이 운영자 계정에 `NOPASSWD:ALL`을 준다 — 좁히는 일은 후속 과제.

## 2026-09-25 · uncommitted · fix(sd): writer 멈춤은 두 단계로, 콘솔 없으면 묻지 않고 실패 (D-230)

- 변경: `prepare-rosy-sd.ps1` 쓰기 감시가 Imager `--cli` stdout를 캡처해 `%`·바이트 진행률을 파싱하고, 진행이 있으면 WMI CPU/I/O가 idle이어도 stall 시계를 리셋한다(파서 출력이 없으면 기존 `Get-WriterSample` 폴백). stall은 soft(`-WriterSoftStallMinutes` 기본 2, hard 절반으로 clamp — 경고 heartbeat `warning` 필드만, stage 집계 불변)와 hard(`-WriterStallMinutes` 기본 5 — 기존 kill·card_state·99.9% resume 안내 그대로)로 분리했다. `-NonInteractive`는 저속 미디어·ERASE 확인의 `Read-Host`를 묻지 않고 fail-closed로 바꾼다. `write-card.ps1`이 두 파라미터를 전달하고, `card-write-status.ps1`이 soft 경고를 `WARNING:` 줄·JSON `warning`으로 보인다.
- 증거: `python -m pytest test/test_sd_writer_contract.py test/test_sd_write_card_entrypoint.py test/test_sd_personalization.py test/test_media_readback.py -q` **245 passed** (2026-09-25 Windows). 도중 계약 테스트가 작은 hard 값(`-WriterStallMinutes 0.05`)에서 기본 soft와 충돌하는 것을 잡아 clamp로 고쳤다 — 기본값 검증을 `Fail`이 아니라 clamp로 해야 기존 호출이 깨지지 않는다.
- gate 변화: 없음(MEDIA 절차 개선, BOOT/DEVICE HOLD)
- 결정: D-230
- 교훈: stall 한도는 "죽이는 값" 하나가 아니라 "알리는 값 + 죽이는 값" 두 개다. 알리는 값을 실패로 만들면(기본 soft > 작은 hard) 기존 호출자가 먼저 깨진다 — 경고 한도는 clamp한다.

## 2026-09-25 · 4107311c · feat(release): payload만 빌드·서명·묶는 경로와 리뷰 수정 (D-225)

- 변경: `deploy/release/build_payload_release.py`(`build` → `native_release.py verify()`가 받는 manifest·SHA256SUMS 릴리스 폴더, `pack` → 정렬·고정 mtime·root 소유·일반 파일/폴더만 담은 재현 가능한 tarball, `--modes-from`으로 Linux 실행 비트 유지), `.github/workflows/build-native-payload.yml`(ubuntu-24.04-arm, 서명 안 된 payload artifact). 오프라인 서명은 기존 `sign_image_release.py` 그대로. 리뷰 수정: colcon 뒤 `compileall --invalidation-mode checked-hash`로 고정 mtime에서도 `.pyc` 유효, 네 unit에 `PYTHONDONTWRITEBYTECODE=1`(서명 릴리스에 목록 밖 `.pyc`가 생기지 않게, `verify()`는 약화하지 않음), Windows에서 서명된 재묶음은 `--modes-from` 필수, `ros-packages.txt` 기록(활성화 게이트 없음 — 운영자가 이미지 `deb-packages.txt`와 비교), 메타데이터 이름은 모든 깊이에서 거부.
- 증거: 재검증 244 passed, 6 skipped(`test_payload_release_build`, `test_native_payload_workflow`, `test_native_release_activation`, `test_release_unpack_helper`, `test_native_systemd_contract`, `test_robot_runtime`, `test_image_customization_contract`, `test_flashable_image_layout`). 묶은 tarball이 실제 `rosy-release-unpack.sh`를 지나 `verify()` 통과. 독립 리뷰 → 수정 → 재검증 PASS.
- 미증명: workflow를 ARM64에서 실행한 적 없음, 실제 colcon 설치 트리로 `build` 미실행, e4us activate·rollback·recover 미실증.
- gate 변화: 없음(`UPDATE_GO` HOLD)
- 결정: D-225
- 교훈: 묶을 때 mtime을 고정하면 timestamp `.pyc`가 전부 낡은 것으로 보인다. 재현성과 `.pyc` 유효성을 같이 얻으려면 checked-hash로 컴파일한다. 첫 시도는 8시간 커밋 0건으로 멈췄다 — 단계별 커밋·제한 시간·커밋 감시로 다시 돌려 23분에 끝났다.
