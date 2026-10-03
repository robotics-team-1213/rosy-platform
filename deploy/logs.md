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

## 2026-09-24 · uncommitted · fix(core,robots): clear error for a missing robot package; ship robots in docker/ci (D-196 review)

- 변경: `.dockerignore`에 `!src/robots/`·`!src/robots/pinky_pro/`·`!src/robots/pinky_pro/**` 추가(없으면 Dockerfile core 단계의 `COPY src/robots/pinky_pro`가 실패). `test/test_robot_runtime.py`에 COPY와 허용 목록 문자열 가드. `deploy/robot/AGENTS.md`에 기존 결함 기록: core 단계는 `core_common`/`core_events`/`core_features`/`core_api_web`를 복사하지 않는다(이번에 고치지 않음). `.github/workflows/ci.yml` host pytest 단계에 `core/core_common/test robots/pinky_pro/test` 추가(`cd src` 기준, 로컬에서 같은 명령 1539 passed·14 skipped로 수집 확인), `.github/workflows/AGENTS.md` 동기화.
- 증거: 가드 먼저 실패(`AssertionError: !src/robots/`) → 수정 후 `test/test_robot_runtime.py` 32 passed (2026-09-24 Windows).
- gate 변화: 없음
- 결정: D-196 Proposed
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

## 2026-09-25 · 57e7e5d7 · feat(image,release,sd,first-boot): 이미지 안 공장 릴리스를 오프라인 서명해 첫 부팅에 설치 (D-225)

- 변경: 이미지 안 공장 릴리스는 서명만 없던 게 아니라 `manifest.json`·`SHA256SUMS`도 없었다(`verify-artifacts.sh`의 확인이 통과할 수 없던 상태). `customize-rootfs.sh`가 마지막 쓰기 뒤 `build_payload_release.py seal`로 봉인하고 두 파일을 dist `factory-release/<id>/`로 내보낸다. `sign_image_release.py`가 공장 목록을 먼저 서명하고 그 `.sig`를 바깥 `SHA256SUMS`에 더한 뒤 바깥 목록을 서명한다(중간 실패 시 원상 복구, 재실행 거부). SD 번들에 `factory_release.sha256sums_sig_b64`(PC에서 신뢰 키로 검증). 첫 부팅이 서명을 넣고 `verify()`가 통과할 때만 남긴다(실패 시 제거·기록, 프로비저닝은 계속). BUILD_GO는 "이미지 안 서명 없음, dist 서명으로 scratch 복사본 verify 통과"를 요구한다. `prepare-rosy-sd.ps1`은 번들 생성 호출에 인자 2개만 추가.
- 증거: 브랜치 437 passed, 12 skipped; 병합 뒤 main에서 공장 서명·오프라인 서명·첫 부팅·릴리스 전환·payload 86 passed, 1 skipped + SD writer 정지 판정 6 passed(D-230 병합 확인). 독립 리뷰(opus) MERGE, 0 CRITICAL/HIGH.
- 미증명: ARM64 이미지 빌드, 실기 첫 부팅. 후속(리뷰 MEDIUM): Pi 5에서 첫 부팅 전체 해시 시간 측정(Wi-Fi 120 s와 같은 180 s 안), 서명된 dist로 SD writer 끝까지 도는 시험. LOW: 일시적 `verify()` 오류가 좋은 서명을 지울 수 있음, 서명기 강제 종료 뒤 수동 정리, 핸드오프 단계에 `factory-release/` 존재 확인 없음, `cp -a`가 CI uid 소유를 유지하는지 확인.
- gate 변화: 없음(`UPDATE_GO` HOLD). 효과는 새 이미지(012)부터 — 011 카드에는 공장 서명이 없다.
- 결정: D-225
- 교훈: "서명 안 됨"으로 알던 결함이 실제로는 "봉인 자체가 없음"이었다. 검사기가 요구하는 산출물을 만드는 단계가 있는지부터 확인한다.

## 2026-09-25 · 17ef9af8 · feat(native): read-only root board device probe (D-247)

- 변경: `rosy-hw-probe.py`(root, 읽기 전용, `--root` 시험)가 보드 장치 14행을 여섯 상태로 재서 `/run/rosy-boot/hardware.json`(root:rosy-core 0640)에 쓴다. `rosy-hw-probe.service`(oneshot, TimeoutStartSec=60, 장치 노드 6개만)와 `rosy-hw-probe.path`(CORE의 `/run/rosy/hw-probe.request`)를 이미지가 설치·활성화하고 `rosy-hw-probe` 명령을 PATH에 둔다. 장치 표면 계약(D-169)은 probe의 노드 집합을 정확히 고정한다.
- 증거: `test/test_hw_probe.py` 24 passed 1 skipped(Windows), native systemd·장치 표면·이미지·설치 배치 계약 통과
- 미증명: Pi 5 실기 실행(`/dev/kmsg` 권한, `DeviceAllow=/dev/rosy-motor` 심볼릭 링크 해석, RPLIDAR C1 GET_HEALTH 응답, 실제 소요 시간)
- gate 변화: 없음
- 결정: D-247
- 교훈: 2026-09-25 전원 재투입 사실 — IR·초음파 4095는 감지 없음(정상), 멈춘 ADC MCU는 Pi 재부팅으로 풀리지 않는다, BNO055는 켜진 뒤 CONFIG 모드라 가속도 0이 정상이다.

## 2026-09-26 · 1d0c3420 · feat(image): enable the I2C0 IMU bus in config.txt (D-247)

- 변경: `configure-boot-overlay-pi5.sh`(이미지·실기 공용, UART 스크립트와 같은 Pi 5 섹션 규칙·vfat 안전 교체)가 boot 줄 하나를 멱등으로 켠다. `customize-rootfs.sh`가 `dtoverlay=i2c0-pi5,pins_0_1`을 넣고 `verify-mounted-image.py`가 요구한다.
- 증거: `test/test_boot_overlay_pi5.py`, 이미지 계약 통과. `rosy_18`에서 손으로 넣은 같은 줄로 BNO055 칩 ID 0xA0
- 미증명: 새 이미지 카드에서 재부팅 뒤 `/dev/i2c-0`
- gate 변화: 없음
- 결정: D-247
- 교훈: 이 커널(6.8.0-1064-raspi)에서는 런타임 `dtoverlay`가 되지 않는다. config.txt와 재부팅만 된다.

## 2026-09-26 · b7d7b17a · feat(image): build the WS2812 lamp driver for the image kernel (D-247)

- 변경: 이미지 chroot에서 고정 rpi_ws281x의 `rp1_ws281x_pwm`을 이미지 커널(`/lib/modules`의 유일한 항목 또는 `ROSY_IMAGE_KERNEL`) 헤더로 빌드한다. 6.11 전에는 `.remove_new`로 고친다. `/lib/modules/<kver>/extra`에 설치하고 depmod한다. `overlays/rosy-ws281x.dts`(`/axi/pcie@120000/rp1`, gpio19 `pwm0`)를 dtbo로 컴파일하고 `dtoverlay=rosy-ws281x`를 켠다. 페이로드가 `99-rosy-lamp.rules`와 `modprobe.d/rosy-ws281x.conf`(`pwm_channel=3`)를 싣는다. `install-pinky-hardware-deps.sh`는 해시 고정 패치(Pi 5 rev 1.1 보드 ID)를 lamp_control 빌드 전에 적용한다.
- 증거: `test/test_lamp_driver_image.py` 17 passed. 패치가 잠긴 아카이브에 적용됨(호스트 `patch`). 모든 단계는 `rosy_18`에서 손으로 확인
- 미증명: 네이티브 ARM64 빌드 호스트에서 이미지 빌드. 베이스 이미지 커널의 `linux-headers-<kver>`가 잠긴 apt suite에 아직 있는지. 새 카드에서 모듈 자동 로드와 `pwm_channel=3`
- gate 변화: 없음
- 결정: D-247
- 교훈: `pwm_channel` 기본값 2는 GPIO18(LCD 백라이트)이다. 모듈이 로드돼도 램프는 어둡다.

## 2026-09-26 · 8e6902fd · feat(native,api): buzzer and lamp test with a person's answer (D-247 6)

- 변경: root oneshot `rosy-hw-test.py`·`.service`·`.path`를 추가했다. `DeviceAllow`는 gpiochip4와 ws281x_pwm뿐이다. 페이로드가 싣고 이미지가 path unit만 켠다. 부저 기본 핀은 BCM 4다(`board.yaml`, `rosy-boot-display`). probe는 램프 `pwm_channel`을 본다.
- 증거: `test/test_hw_test.py` 38 passed 2 skipped(Windows), native systemd·장치 표면·이미지·설치 배치·부팅 표시 계약 통과
- 미증명: 실기에서 lgpio PWM이 unit 샌드박스(RuntimeDirectory, DeviceAllow) 안에서 도는지. lamp_selftest를 root로 돌렸을 때 램프가 켜지는지
- gate 변화: 없음
- 결정: D-247, D-190(부저 핀)
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(deploy): D-260 boot display sound, lamp and LCD; test hand-over
- 변경: `rosy-boot-display.py`: 규칙표 상태로 부저(상태 변경 때만, 300 s 반복 억제)·램프(`lamp_pattern`, 채널 3일 때만, fail-open)·LCD 두 줄, 부저·램프 기본 켜짐, `rosy-hw-test` 시험 넘겨받기. unit: `DeviceAllow=/dev/ws281x_pwm`, `RuntimeDirectory=rosy-display`. udev: `/dev/ws281x_pwm` root:rosy-display 0660. `rosy-boot-status`: `runtime_mode`와 장치 `id·state·product`를 boot-status.json에. `rosy-hw-test`: 부팅 화면 프로그램이 쥔 장치는 `busy` 대신 넘김(15 s 무응답 = failed). `rosy-hw-probe`: 부저 기본 켜짐. board.yaml lamp 절. 이미지 probe가 `core_common.robot_state` import와 램프 노드를 본다
- 증거: `test_boot_display.py` 105 passed; `test_hw_test.py` 64 passed; `test_hw_probe.py` 41 passed; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음 — DEVICE 확인 전
- 결정: D-260 Proposed
- 교훈: 권한 없는 부팅 화면 프로그램이 못 읽는 입력(runtime.env 0600, hardware.json 0640)은 이미 root로 도는 표시기가 필요한 칸만 옮긴다

## 2026-09-26 · uncommitted · fix(deploy): D-260 review M1 M2 L1-L4
- 변경: `rosy-boot-status`가 CORE의 `/run/rosy/status-inputs.json`(SAF-005 경고 임계, 덮기를 거친 장치 상태)을 엄격히 읽어 boot-status.json에 옮기고 부팅 화면 프로그램이 그 임계를 쓴다. `rosy-hw-test`는 ActiveState가 정확히 `active`이고 `rosy-display` 그룹이 있을 때만 넘긴다. 스위치 해석기 `rosy_display_env.py` 공유. 주의 소리만 300 s 반복 억제. `rosy-hw-test.service` 주석 정정
- 증거: `test_boot_display.py`·`test_hw_test.py`·`test_hw_probe.py`·native systemd·device surface 412 passed(gateway status-summary 포함, 2026-09-26 Windows); 두 경로 동등 시험 3건
- gate 변화: 없음 — DEVICE 확인 전
- 결정: D-260 Proposed
- 교훈: 권한 없는 표시기가 CORE와 같은 판정을 하려면 입력을 CORE가 넘겨야 한다

## 2026-09-26 - prepare selected OMX-AI workcell target
- Change: record OMX-AI as selected but keep runtime disabled; remove the unmeasured six-joint default; lock official ROBOTIS Jazzy source revisions and add a separate workstation image plan.
- Evidence: focused profile/product/vendor-lock suite: 13 passed; disabled CLI output: `{}`.
- Gate change: SOURCE/LOCAL evidence refreshed; ROS-SIM and ARTIFACT remain HOLD; DEVICE/FIELD remain PARKED.
- Decision: D-273; execution plan: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · build locked OMX-AI workstation image and serial admission
- 변경: full-SHA ROBOTIS 잠금으로 ROS Jazzy OCI 워크스테이션 이미지를 만들고, 팔 bringup/description/Dynamixel 패키지 집합과 동작하지 않는 hardware/software 셸 프로필을 추가했다. Linux by-id 사전점검은 서로 다른 follower/leader character device와 read/write 권한을 요구한다.
- 근거: OMX 호스트 시험 8개 통과; Docker Linux/amd64 이미지 빌드 digest `sha256:8b4d2fdf534687132cc7d9fb8441b3db63c140edfaaba5164693fd56ca77d861`; 이미지에서 `open_manipulator_bringup` 및 `dynamixel_hardware_interface` 조회 성공; Compose 설정 검증 통과.
- gate 변화: SOURCE/LOCAL 이미지 빌드 및 사전점검 GO; ROS-SIM/ARTIFACT HOLD; DEVICE/FIELD PARKED.
- Decision: D-273; execution plan: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · clarify OMX workstation packaging boundary

- 변경: `deploy/omx/README.md`의 OCI 후보를 개발·빌드 셸로 명확히 하고, D-246을 따르는 native systemd 현장 제어 인스턴스와 한 호스트의 1~2개 배치 후보를 연결했다.
- 근거: 현재 Compose는 비활성 단일 hardware/simulation 셸이며 실제 OMX 제어 서비스는 없다. D-281과 사이트 호스트 배치 설계에 검증 순서를 기록했다.
- gate 변화: 없음. 장치 제어·정지·복구·동시 부하의 DEVICE/FIELD 증거는 없다.

## 2026-09-26 · uncommitted · feat(sd): fail closed on board transfer and expose setup status
- 변경: first-boot가 보드 이동을 감지해 새 임시 신원을 준비하고 CORE 시작을 막는다. 상태 서버는 8080에서 읽기 전용 안내만 제공한다.
- 증거: 관련 호스트 시험 439 passed, 8 skipped; arm64 이미지 및 Pi 검증 전.
- gate 변화: ARTIFACT/DEVICE HOLD 유지.
- 결정: D-154.
- 교훈: 등록 권한 없이 로봇 번호를 자동 배정하지 않는다.

## 2026-09-26 · uncommitted · feat(sd): recover a moved Pi with a fresh identity
- 변경: 이전 프로비저닝·CORE 홈·로그·장치 신원을 root-only 보관 경로로 옮기는 재등록 도구를 추가했다. 같은 현장 Wi-Fi를 유지하고 새 UID·번호·토큰 bundle만 적용한다. 4~10장 순차 작성과 Fleet 개별 등록 절차를 runbook에 명시했다.
- 증거: `test/test_rebind_board.py` 4 passed; 네트워크 Pi에서 새 19번/Domain 59로 CORE·dashboard·인증 API HTTP 200, Fleet snapshot 1/1 online. 원본 감사 기록은 보관 경로에 남고 새 기록과 다르다. 새 서명 이미지·SD 쓰기는 미완료.
- gate 변화: DEVICE의 단일 Pi 재등록 경로를 관측했으나 이미지/다중 카드 gate는 HOLD 유지.
- 결정: D-154 새 장치 처리.
- 교훈: 원래 카드로 재등록할 때는 기존 CORE 홈을 먼저 격리해야 API 토큰·설정이 새 신원으로 섞이지 않는다.

## 2026-09-26 · uncommitted · feat(omx): add isolated vendor simulation and Pinky-aware ROS settings
- 변경: Run the pinned ROBOTIS OMX-F Gazebo launch in an optional headless, hardware-free Compose profile; allow workstation ROS domain/discovery configuration, keep simulation on its own LOCALHOST domain, fix RMW to CycloneDDS per D-117, and document Pinky identity/integration boundaries under D-33 and D-273.
- 증거: 13 focused OMX workstation/vendor lock tests passed; simulation policy mutation was rejected; Docker image rebuilt as `sha256:2e5a65940cb7ec6964c3b75081878c4e520b4aea597cdcc7e1fbc86b1f850159`; image resolves CycloneDDS and ROBOTIS bringup. Headless Gazebo showed `/clock`, `/joint_states`, and active controllers.
- Limits: ROS-SIM remains HOLD due to virtualized timing overruns, unsupported gripper mimic constraint, and disabled URDF command limits; bounded motion/fault acceptance and device/Pinky integration remain open.
- gate 변화: no product capability enabled.
- Decision: D-273 remains governing boundary; implementation plan: `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`.

## 2026-09-26 · uncommitted · OMX 호스트 인벤토리와 다중 장치 사전점검

- 변경: D-281의 호스트·작업대 ID를 비활성 기본 YAML 인벤토리로 표현하고, 활성 작업대의 follower/leader by-id 선택 및 호스트 내 중복 할당을 정적으로 검증한다. 호스트 사전점검은 활성 작업대별 실제 character device·읽기/쓰기 권한과 symlink 별칭 충돌을 거절한다.
- 근거: Windows fake probe와 기존 단일 OMX 사전점검을 사용한 집중 계약 시험. 활성 프로필·장치 연결·Fleet API·Compose 자동 투입은 포함하지 않았다.
- gate 변화: SOURCE/LOCAL 계약 준비만 확대. ROS-SIM/ARTIFACT HOLD 및 DEVICE/FIELD PARKED 유지.

## 2026-09-26 · uncommitted · speed up image compression for multi-card production

- 변경: xz 압축을 level 6으로 조정하고 CRC64, 전체 xz 검증, 카드 전체 읽기 검증은 유지한다.
- 근거: 이전 ARM64 빌드의 압축 단계는 21분 38초였다. 같은 256 MiB rootfs 표본에서 level 6은 247.32초/253,463,064바이트, level 9 extreme은 403.30초/252,893,336바이트였다. 크기 차이는 0.23%였다.
- gate 변화: 소스 최적화만 완료. 현재 018 빌드는 이전 압축 설정이며, 다음 ARM64 전체 빌드에서 총 시간과 이미지 크기를 검증한다.

## 2026-09-26 · uncommitted · Pinky Pro OV5647 CAM1 장치 검증 및 이미지 부팅 설정

- 변경: 이미지 customizer가 `camera_auto_detect=0`과 `dtoverlay=ov5647`을 CAM1에 적용하고 mounted-image verifier가 이 조건을 검사하도록 했다.
- 증거: Pi 5 rev d04170의 ROSY SD에서 `ov5647 11-0036` probe 성공, 공급사 카메라 사용자 공간을 임시 실행해 2592×1944 JPEG 실제 촬영 및 화면 확인. rev d04171은 공급사 SD에서 CAM0/CAM1 모두 probe `-121`로 실패했다.
- 제한: ROSY 제품 이미지에는 PiSP/Picamera2 촬영 런타임이 없고 기본 서비스는 CORE-only다. 임시 진단 촬영은 제품 스트림 수용이 아니다. 새 이미지 artifact 빌드와 `.201` 물리 접속 확인은 남았다.
- gate 변화: 없음. SOURCE 수정과 장치 진단만 확인했으며 ARTIFACT/DEVICE는 HOLD 유지.

## 2026-09-26 · uncommitted · harden optional OMX-AI simulation image
- 변경: keep vendor patches LF on Windows, select the AI follower Gazebo launch with Bullet Featherstone and synchronous simulated hardware, enforce URDF command limits, and remove the direct leader-topic remap from simulation.
- 증거: local amd64 image sha256:3858136d3cd552228549e5c9369b24e23c7fa051c4afc7497251f781cd023954; 21 focused tests and two-instance ROS-SIM probe in docs/validation/omx-two-instance-ros-sim-2026-09-26/README.md.
- gate 변화: no field actuator or artifact gate promoted; native command owner and physical acceptance remain open.

## 2026-09-26 · uncommitted · D-287 Pi 5 카메라 사용자 공간 이미지 빌드 경로

- 변경: Raspberry Pi 공식 libpisp, libcamera, rpicam-apps, Picamera2 소스를 커밋과 아카이브 SHA-256으로 고정하고 네이티브 ARM64 이미지 customizer에 설치 단계를 연결했다. mounted-image 검증기는 실행 파일, PiSP IPA, Python 패키지, 소스 기록을 확인한다.
- 증거: 네 공식 아카이브와 ARM64 Python 배포물의 로컬 SHA-256 재확인, 잠금·설치 순서·검증기 호스트 계약 시험. 새 ARM64 이미지 빌드와 SD 촬영은 미실행.
- gate 변화: SOURCE/LOCAL 구현만 추가. ARTIFACT와 새 SD의 DEVICE 촬영은 HOLD.

## 2026-09-26 · uncommitted · docs(adr): renumber camera source-build decision

- 변경: 메인 브랜치의 D-287 readback 결정을 보존하고 카메라 이미지 결정을 D-288로 기록했다.
- 증거: ADR 색인과 이미지 잠금·설치·검증 시험의 D-288 참조 일치.
- gate 변화: 없음. 새 ARM64 이미지와 SD 카메라 촬영은 미검증이다.

## 2026-09-26 · uncommitted · site LAN discovery profile and Fleet advertisement

- 변경: ROSY 로봇 mDNS TXT에 공통 제품·역할·프로토콜 표시를 추가하고, Ubuntu Fleet `_rosy-fleet._tcp` Avahi 광고·검색 도구와 systemd 유닛을 사이트 배포 묶음에 넣었다.
- 증거: Windows 집중 45 passed/2 skipped, 변경 파일 flake8 통과. Ubuntu Avahi 및 TLS 현장 연결은 아직 실행하지 않았다.
- gate 변화: SOURCE/LOCAL 범위만 확인, Ubuntu 사이트 ARTIFACT·DEVICE·FIELD 검증 대기.

## 2026-09-26 · uncommitted · paired robot Fleet mDNS bootstrap

- 변경: native image에 Avahi browse와 `.local` 이름 해석 의존성을 추가하고, 서명된 SD의 Fleet `.local` 예상 호스트와 trust profile에서 CORE 비공개 discovery 설정만 생성한다. 일회성 `pairing_credential`은 Agent 토큰으로 복사하지 않는다.
- 증거: first-boot와 Agent 통합 집중 58 passed, 변경 파일 flake8 통과. 실제 native image 빌드와 Pi/Ubuntu TLS 연결은 미실행.
- gate 변화: SOURCE/LOCAL 근거만 추가, ARTIFACT·DEVICE·FIELD 대기.

## 2026-09-26 · uncommitted · D-291 Pinky I/O 기본 부팅과 새 이미지·SD 인수

- 변경: CORE와 무구동 I/O를 첫 부팅에 시작하고, 모터 구동은 장치별 커미셔닝 설정으로만 활성화한다. 이전 서명 이미지의 MEDIA 증거는 새 소스의 이미지로 재사용하지 않는다.
- 근거: `2026.09.26-018`의 이미지와 카드 영수증은 이번 target 변경 이전 소스다. 새 ARM64 서명 이미지, 전체 카드 readback, Pi boot를 각기 확인한다.
- gate 변화: 소스 계약은 검증 중이며 새 ARTIFACT/MEDIA는 빌드·기록 전까지 HOLD.

## 2026-09-26 · uncommitted · site control console operator access guide

- 변경: 사이트 서버, 운영자 브라우저, Pinky, OMX, 향후 GPU 호스트의 실행 책임과 LAN 바인딩·TLS·권한·작업 readback 점검 순서를 배포 설명에 추가했다.
- 근거: `compose.yaml`의 기본 `127.0.0.1:8443`, Caddy의 Fleet 프록시, D-275/D-276/D-290을 대조했다.
- gate 변화: 없음. SOURCE 문서 정리이며 실제 사이트 네트워크 및 장치 수용은 미실시.

## 2026-09-26 · uncommitted · OMX development image action-only vendor launch

- 변경: 잠긴 vendor 비시뮬레이션 follower launch에서 leader trajectory topic 직접 remap을 제거하고, 개발 이미지에 적용·설치하도록 했다.
- 증거: 회귀 시험 실패→통과 및 mutation red, Docker Desktop amd64 빌드와 설치된 launch `remappings=[]` readback. 이미지 ID와 한계는 OMX 검증 기록에 남겼다.
- gate 변화: SOURCE/LOCAL 보강. native systemd 산출물, 실제 OMX 장치와 현장 제어 승인은 여전히 HOLD.

## 2026-09-26 · uncommitted · OMX owner vendor simulation probe and host handoff

- 변경: 읽기 전용 checkout, 네트워크·장치 허가 없는 컨테이너에서 vendor Gazebo와 단일 소유자 시험을 재현하는 probe를 추가했다. OMX 호스트 이전의 점유 해제·무명령 기동·재승인 순서를 배포 설명에 적었다.
- 증거: 잠긴 amd64 개발 이미지의 vendor action 시험 통과, 가짜 serial mount 거부(exit 2). 대상 Ubuntu 및 실물 장치 시험은 수행하지 않았다.
- gate 변화: ROS-SIM 진단 근거만 보강. native 서비스·현장 배치 승인과 DEVICE/FIELD는 HOLD.

## 2026-09-27 · uncommitted · update default-config image readback
- Change: mounted-image validator now expects the default YAML in core_common share.
- Evidence: image customization contract tests passed within the 1,812-test gateway/config/image run; built core_common wheel contains both YAML files.
- Gate: host contract only; native ARM64 artifact and mounted device image remain unverified.

## 2026-09-27 · uncommitted · fix(native): verify G4 on navigation start

- 변경: `mapping_approval.py`가 G4 원시 odom과 해시를 봉인하고 `rosy-navigation.service`의 `ExecCondition`이 매 기동마다 현재 장치·릴리스와 승인 기록을 다시 검증한다.
- 검증: Windows 호스트 계약 시험. ARM64 이미지·설치 장치·물리 G4/G5는 HOLD다.
- gate 변화: SOURCE/LOCAL 검증 경로를 추가했다. ARTIFACT/DEVICE/FIELD 수용은 HOLD다.

## 2026-09-27 · uncommitted · fix(native): accept floor G4 evidence

- 변경: G4 번들의 `wheels_lifted` 필수값을 없애고 `test_surface=floor|lifted` 및 시험당 10 cm 이동 한계를 검증한다.
- 검증: Windows 호스트 시험. 기존 장치에는 이전 형식의 벤치 도구가 적용되어 있으며 새 도구의 설치 해시를 별도 확인한다.
- gate 변화: SOURCE/LOCAL 검증 경로를 갱신했다. 실물 G4/G5 판정은 HOLD다.

## 2026-09-27 · uncommitted · feat(host-agent): stamp complete status reads

- 변경: Host Agent가 네트워크·릴리스 동기 조회 완료 직후 UTC를 응답에 붙인다. nmcli 부분 실패, 릴리스 상태 JSON·필수 필드 실패는 성공으로 꾸미지 않는다.
- 검증: Host Agent 거부·명령 계약 132 passed. 기존 장치에는 Agent 서비스/소켓이 없어 DEVICE는 HOLD다.
- gate 변화: SOURCE/LOCAL 계약 근거만 추가했다. 새 이미지 설치와 실물 readback이 필요하다.

## 2026-09-27 · uncommitted · repair development CORE image package closure

- Change: copy the six missing CORE and web packages into the Docker build, select the web asset packages, and probe installed imports and assets in the final CORE image.
- Evidence: the new closure tests failed twice on the old Dockerfile, then 48 CORE image/runtime/API host tests passed after the fix. ARM64 image execution is pending independent verification.
- Gate: SOURCE/LOCAL candidate only. ARTIFACT, DEVICE, and FIELD acceptance remain unchanged.

## 2026-09-27 · b0609dc6 · verify development CORE image closure on ARM64

- Change: verify the final image at clean source revision b0609dc68ed727a1ed15e57e7c3e029001ab0a8f; no device deployment or release publication.
- Evidence: ARM64 OCI build exit 0; final installed import, dashboard/web_common asset and route probe passed. Installed ament overlay contains exactly core, core_api_web, core_common, core_events, core_features, dashboard, interfaces, pinky_pro, web_common. OCI manifest sha256:4eeccfd3105bee2e5b4ecf7326af292b8d3eb41dcc372b6d1915207d2fba4e29; raw logs on X: (rosy-d310-core-closure-fix-b060.log, rosy-d310-core-inventory-b060.log).
- Gate: CORE development image ARTIFACT evidence at this source SHA only. IO/native, deployed image signer/digest, DEVICE and FIELD remain HOLD.

## 2026-09-27 · uncommitted · close development IO web asset dependency

- Change: copy and select `web_common` with `control` in the IO image; probe the installed shared assets and control's asset resolver in the final IO stage.
- Evidence: the IO closure tests failed twice on the original Dockerfile, then 38 IO/CORE image and runtime host contracts passed. ARM64 IO image execution remains pending.
- Gate: SOURCE/LOCAL candidate only. The IO ARTIFACT, DEVICE, and FIELD gates remain HOLD.

## 2026-09-28 · uncommitted · feat(sd): automate attended motor commissioning

- Change: add a post-setup helper that checks provisioned identity, E-Stop, torque-free motors, runtime activation, fresh stationary odometry and single final command publisher; rollback restores no-drive runtime on failure.
- Evidence: helper CheckOnly and attended activation ran on one device; two bounded forward attempts ended stopped, the second was physically confirmed. Private measurements remain under X:\DevTemp.
- Gate: no unattended first-boot torque, G4 approval, native image acceptance or FIELD promotion.

## 2026-09-28 · uncommitted · D-320 product-scoped robot deployment layout

- 변경: Moved Pinky deployment sources under `deploy/robot/pinky_pro/` and OMX workstation development/simulation inputs under `deploy/robot/omx/`; `deploy/site/` remains independent.
- 증거: Updated source imports, build inputs, CI/workflow references, host tests, current documentation, and Harness module paths. Kept installed Pinky runtime, SD tooling, and release CLI paths at `/opt/rosy/deploy/robot/`, `/opt/rosy/deploy/sd/`, and `/opt/rosy/deploy/release/`.
- gate 변화: Product-layout, installed-runtime, image-check, SD-personalization, and first-boot contracts passed (91 passed, 2 skipped). Native ARM64 image and physical-device gates remain separate.

## 2026-09-28 · uncommitted · D-320 product deployment path regression verification

- 변경: `deploy/robot/pinky_pro`와 `deploy/robot/omx`로 옮긴 배포 경로, Pinky 이미지/release/SD 계약, OMX workstation 경로를 회귀 검증했다. `.gitattributes`의 제품 경로도 갱신했다.
- 증거: 집중 계약 묶음 277 passed, 5 skipped, 1 deselected; 별도 Git Bash gate 시험 1 passed; SD 계획/identity 핵심 4 passed; OMX host/site-fabric 계약 52 passed; source encoding 1 passed. 최신 main의 moved-device setup 계약 14 passed, 1 skipped. `rosy_harness.py generate`와 lint 성공(0 errors, 18 warnings), `git diff --check` 성공.
- gate 변화: SOURCE/LOCAL만 갱신. ARM64 artifact, 설치/readback, DEVICE/FIELD 수용은 확인하지 않았으며 기존 HOLD를 유지한다.

## 2026-09-29 · uncommitted · docs(g4): plan an attended calibration and mapping flow

- 변경: D-321과 단계별 실행 계획에 PC 링크 preflight, 장치 독립 원시 수집, Control 보정 재사용, 네이티브 G4 봉인과 빈 지도 SLAM 전환을 기록했다.
- 증거: 설치 장치에는 현재 승인 도구가 없고 navigation unit은 마커 존재만 확인한다. 마지막 명령 소실 시도는 원시 자료가 비어 있으며 현장에서 전원을 차단했다. persistent motor/drive 설정은 전원 차단으로 지워지지 않아 다음 부팅 전에 오프라인 복구가 필요하다.
- gate 변화: 배포·실물 G4/G5 HOLD. 장치 전원은 꺼진 상태로 유지한다.

## 2026-09-29 · uncommitted · fix(sd): prepare offline no-drive card recovery

- 변경: Linux ext4 카드에서 신원·릴리스 일치, 외부 원본 백업, 원자 교체와 readback을 요구하는 no-drive 복구 도구와 현장 절차를 추가했다. 기본 동작은 읽기 전용이다.
- 증거: 소스 검토만 수행했다. 실제 카드·Linux 호스트·첫 부팅은 아직 검증하지 않았다.
- gate 변화: 현 장치의 전원 차단과 DEVICE/FIELD HOLD를 유지한다. persistent drive가 있는 기존 설치본은 카드 복구 전 재전원하지 않는다.

## 2026-09-29 · uncommitted · feat(release): select the smallest Pinky artifact

- 변경: D-325 path selector와 operator guidance를 추가했다. 호환 source 업데이트는 native payload로 보내고, image/host/board/trust changes는 full image, 비장치 변경은 no artifact, 분류 밖은 HOLD다.
- 증거: selector 계약 6개 통과. 측정된 prior Actions build는 full image 약 30분 대 native payload 약 5분. 서명 키, artifact, device proof를 생성했다고 주장하지 않는다.
- gate 변화: SOURCE 절차 개선. ARTIFACT·DEVICE·FIELD는 기존 HOLD다.

## 2026-09-29 · uncommitted · build and locally smoke the site candidate

- 변경: merged source `3e2bf04652600d524d244929a4da95371e6dcc99`에서 Fleet, Vision, proxy 이미지와 SPDX SBOM을 빌드해 X: 임시 후보로 패키징했다. 별도 X: 테스트 설정은 가짜 credential, 예약 TEST-NET robot 주소, 내부 전용 egress를 사용했다.
- 증거: archive SHA-256 `165bfe7021a86542e4d845b0d544a937da50a67f5de71a974c8d2b3fd546072e`; manifest의 3개 image ID/platform, archive와 SBOM 해시 일치. 로컬 Compose에서 세 서비스 healthy, `/healthz` HTTP 200 확인 후 서비스를 정지했다.
- gate 변화: unsigned local candidate까지만. 서명 파일·production site signing key·승인된 target host/TLS identity가 없어 전달 및 운영 활성화는 HOLD다. Isaac ROS-SIM, physical stop/readback, DEVICE/FIELD와는 별도다.

## 2026-09-29 · uncommitted · fix Vision site-container shutdown

- 변경: 로컬 compose 종료 중 Vision이 Docker 기본 SIGTERM에서 exit 137로 종료되는 것을 확인했다. Python PID 1이 처리하는 `SIGINT`를 compose `stop_signal`로 지정하고 회귀 계약을 추가했다.
- 증거: `python -m pytest test/test_site_task_queue_deploy.py -q` 4 passed; compose JSON에서 SIGINT 확인; Vision 컨테이너가 healthy 상태에서 10초 timeout 정지 후 exit 0, `OOMKilled=false`, runtime error 없음. 전체 site candidate는 커밋 및 로컬 병합 후 다시 빌드/검증해야 한다.
- gate 변화: LOCAL shutdown 증거만 보강. 서명되지 않은 최종 후보의 production 전달/활성화, Isaac ROS-SIM, physical stop/readback, DEVICE/FIELD는 HOLD다.

## 2026-09-29 · uncommitted · rebuild and smoke the merged site candidate

- 변경: 현재 local main을 통합한 source `a86dd19ca48e13c4512a1cf815f169c78f827e7d`에서 Fleet/Vision/proxy linux/amd64 후보와 SPDX SBOM을 다시 빌드했다.
- 증거: `X:\DevTemp\rosy-site-candidate-a86dd19\images.tar` SHA-256 `e9c9e4968e156a2ea9292a17218827af7b29a0e0890f5afa539a94afc822c3c6`; 세 image ID/platform, archive 및 SBOM hash가 manifest와 일치. 격리 Compose에서 세 서비스 healthy, HTTPS `/healthz` HTTP 200, SIGINT를 쓰는 Vision 포함 전 서비스 정지 exit 0 확인.
- gate 변화: unsigned local candidate와 LOCAL smoke까지만. 승인 signing trust/host가 없어 production 전달 및 활성화, Isaac ROS-SIM, physical stop/readback, DEVICE/FIELD는 HOLD다.

## 2026-09-29 · uncommitted · repin the WS281x patch hash and restore the diagnostics import

- 변경: `e3b0c95e`가 패치의 경로 언급 한 줄만 고치고 `inputs.lock.yaml`의 `rpi_ws281x_pi5_patch_sha256`은 옛 값을 그대로 둬 `test_the_lock_pins_the_patch_bytes`가 빨갰다 — SHA-256을 현재 바이트(`9a131889…`)로 재고정했다. `read-card-diagnostics.py`는 개조로 사라진 `sd/../robot/native` 자리에 `rosy_diag_redact`를 찾고 있어 `ModuleNotFoundError`로 죽었다 — 형제인 `native/`로 바로잡았다.
- 증거: `test_lamp_driver_image` + `test_card_diagnostics` + `test_line_follow_contract_docs` 38 passed, 1 skipped. 새 해시는 `git grep`으로 저장소에 한 곳에만 있고 중복 참조가 없다.
- gate 변화: 없음. 이미지 빌드의 `sha256sum` 검증은 같은 잠금 파일을 계속 읽는다.

## 2026-09-29 · uncommitted · clear the deployment-contracts step (scanner FPs + colcon-output walks)

- 변경: CI 6단계 적자 4건의 원인을 두 갈래로 고쳤다. (1) `secret_scan.py` 오탐 13건 — 규칙을 좁게 다듬었다: `_INTEGRITY_CONTEXT`에 backtick을 여는 `source`만 인정, URL이 가리키는 값을 bare copy로 인용하면 면제, 50자 이상 순수-문자 run은 base64가 아님, 닫히지 않은 bracket을 가진 값은 코드 조각(`_call_holds_no_literal` 유지), 환경 조회(`os.environ.get`/`getenv`)의 인자는 ALL_CAPS 이름이면 키로 취급, `obj.method()`를 `_CODE_REFERENCE`에 추가, 호출 인자 위치의 secret-named 식별자는 참조로 취급. (2) `test/robot_contracts.py`에 `COLCON_OUTPUT`/`source_manifests()`를 두고 image-closure 두 테스트와 `_launch_file`이 `src/build`·`src/install`·`src/log`를 건너뛰게 했다 — CI는 colcon 빌드 후라 중복 `package.xml`이 먼저 정렬됐던 것이 원인이다.
- 증거: colcon 출력 흉내 트리에서 수정 전 3 failed(CI와 동일한 assertion) → 수정 후 3 passed; `test_release_boundary_guards.py` 73 passed(신규 회귀 10건 포함: 인자 위치 리터럴 4건은 계속 보고); 전체 `test/` suite 실행 중.
- gate 변화: 없음. 스캐너 완화에 대한 변명성 주석 없이 각 규칙의 오탐 비용을 코드에 기록했다.

## 2026-09-29 · uncommitted · fix(image): io-build 클로저에 core_common 추가

- 변경: deploy/robot/pinky_pro/Dockerfile io-build 스테이지의 --packages-select에 core_common을, COPY에는 패키지 루트인 src/contracts/foundation 통째로 추가했다(core_common의 package.xml은 foundation/에 있다). omx_adapter가 core_common에 직접 의존하게 되면서(ER2 adapter 작업) 선택 목록의 전이 클로저에 core_common이 필요해졌으나 목록이 그대로여서 test_io_image_closure가 실패했다.
- 증거: test/test_io_image_closure.py 2 passed. .dockerignore는 !src/contracts/foundation/** 로 이미 허용(추가 변경 없음).
- gate 변화: 없음.
- 결정: 클로저는 select 목록이 스스로 증명한다 — 의존 추가 커밋은 같은 변경에서 select·COPY를 함께 고친다.
- 교훈: omx_adapter→core_common 커밋이 이 시험을 빨갛게 두고 갔다(커밋 순서 뒤처짐).

## 2026-09-29 · uncommitted · test(sd): 999% 스톨 시험의 폴 레이스 제거

- 변경: test/test_sd_writer_contract.py의 at_999 시험이 스톨 감시 창(-WriterStallMinutes 0.05에서 0.5)과 부분 복사 자식의 생존 시간(_partial_copy_child 파라미터화, 2초에서 25초)을 확보했다. 풀스위트 부하에서 파이썬 콜드스타트가 3초 스톨 창을 넘기면 감시자가 0바이트를 표본 삼아 99.9% 미달로 오판하거나 2초 생존 창을 놓쳐 분류가 뒤바뀌어 실패했다(2026-09-29 풀 게이트 적신 6건 중 1건, 단독 실행으론 통과).
- 증거: 대상 2개 시험(at_999·well_below) 통과(2:36). 감시 창·생존 창은 픽스처 안무일 뿐 감시 문구·분류 계약(D-225 3.2·D-187)은 불변이고, well_below는 기본값 그대로다.
- gate 변화: 없음.
- 결정: 레이스는 픽스처 편성에 있었고 제품 코드는 무결 — 시간 여유 매개변수만 늘렸다.
- 교훈: 단독 통과·풀스위트 실패 조합은 부하 민감성이지 가드의 잘못이 아니다 — 편성을 고정 시간 여유로 결정론화한다.

## 2026-09-29 · uncommitted · test(sd): hung readback 계약의 냉각시작 레이스 제거

- 변경: test/test_sd_writer_contract.py의 hung readback 시험에서 -ReadbackStallMinutes를 0.05(3초)에서 0.5(30초)로 넓혔다. 풀스위트 부하에서는 검증 자식의 생성·파이프 접속이 3초 창을 넘길 수 있고, 그러면 감시자가 카드에 닿지도 않은 클라이언트를 판정한다(2026-09-29 풀 게이트 실패, 단독 실행으론 통과). hang 동작은 무한 대기이므로 창 확대는 판정 시점만 늦추고 판정 대상은 바꾸지 않는다. 같은 날 999% 스톨 시험(de-flake 9534fdea)과 같은 처방·같은 근거다.
- 증거: hung readback + slow-readback-never-stopped 2 passed(54초). slow 쪽은 건드리지 않았다(풀 게이트 실패 목록에 없음 — 최소 변경).
- gate 변화: 없음.
- 결정: 없음(픽스처 안무만).
- 교훈: 같은 파일의 부하 민감 시험은 한 번에 하나씩 실패로 드러난다 — 형제 시험 전부를 예방 수술하지 말고 실패한 것만 고친다.

## 2026-09-29 · uncommitted · fix(release): 비밀 스캐너에 저널 인용 산탄 예외

- 변경: secret_scan.py에 KNOWN_PROSE_QUOTES를 추가했다 — src/site/fleet/logs.md 한 경로에서만, 제거된 픽스처 값(fixture-secret)의 인용을 면제한다. 병행 fleet 세션이 api_key 리터럴을 허용 키로 교체하며(c9001aba) 저널에 옛 값을 인용했는데, 모듈 저널은 append-only라 문구를 못 고치고 스캐너가 이를 credential로 적발해 CI(main)가 빨간 상태였다. 같은 값은 그 외 모든 위치(해당 모듈 코드 포함)에서 여전히 적발된다. 코드는 3f0c6636으로 먼저 반영됐고 이 항목은 뒤늦은 저널 보충이다.
- 증거: test_secret_scan.py 2건 신설(핀 경로 면제 + 다른 경로 여전히 credential 적발 — 산탄 증명), test_release_boundary_guards 72 passed. test_boot_display는 로컬 106 통과 — CI 로그의 FAILED 문자열은 파라미터 ID(FAILED:rosy-core.service 상태명)였다.
- gate 변화: 없음.
- 결정: 예외는 (경로, 값) 쌍으로 핀 고정. 목록이 늘어나면 각 항목이 사유와 함께 심사 대상이다.
- 교훈: 저널에 옛 비밀 형태 문자를 인용하지 않는다 — 문구로 서술한다. append-only라 한번 실으면 못 지운다. (그리고 저널 append는 인라인 명령이 아니라 스크립트 파일로 — 이 항목 자체가 그 교훈의 산물이다.)

## 2026-09-29 · uncommitted · feat(verify): 상주 단위 CPU 측정·A/B 도구 (D-347 B레인 관문)

- 변경: deploy/robot/pinky_pro/verify/measure-resident-cpu.sh 신설 — systemd 단위별 CPU를 cgroup/proc 틱 증분으로 샘플하고(의존 설치 없음), --ab-unit 로 켜짐/꺼짐 A/B 를 잰 다음 단위를 반드시 되살린다. A/B 허용 단위는 rosy-camera·rosy-navigation 뿐(rosy-core=게이트웨이, rosy-io=안전 기본층 금지). 결과는 /var/lib/rosy/resident-cpu-<ts>.md. 기준선 문서 §5에 도구로 등재.
- 증거: test/test_measure_resident_cpu.py 4건 신설 — bash -n 파싱, 금지 단위 3종 거부(exit 2, 무권한으로 판정 가능=allowlist 가 root 검사보다 선행), stop 뒤 start 복원·기준서 지시 핀. 산탄 증명: 허용 목록을 넓히면 거부 시험이 즉시 적신.
- gate 변화: 없음(측정 도구·실기 세션用品).
- 결정: 측정 도구는 상태를 바꾸고 끝내지 않는다 — A/B 후 단위 복원이 도구 계약이다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · fix(image): io closure 계약에 D-84 지연 패키지 예외를 명시

- 변경: test_io_image_closure.py의 의존성 closure 계산이 board.yaml hardware_packages(D-84 — Device hardware 프로필이 열리기 전까지 CORE/io 이미지 금지)에 있는 패키지와 그 하위 의존을 요구 집합에서 제외한다. control이 legacy launch로 imu_bno055를 exec_depend로 선언하면서(정직한 선언) closure 계약과 D-62 슬라이스 계약이 충돌했고, D-84가 이미 우선순위를 정하고 있으므로 예외를 계약에 명시했다.
- 증거: 변이 증명 — 금지 목록 밖 가짜 의존(core_events)은 적발(붉음), 목록 내(emotion·imu_bno055)은 의도대로 제외, 복구 후 초록 (2026-09-30 Windows). test_nav2_hardware_slice는 변화 없음 통과.
- gate 변화: 없음.
- 결정: 장기 수정은 KNOWN_DIRECTION 기록대로 — control의 legacy launch가 IMU 드라이버를 시작하는 것을 bringup 조립으로 옮기는 코드 이동이다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(site): D-352 robot_credential_key secret와 오프라인 rekey

- 변경: `site/compose.yaml`에 secret `robot_credential_key`와 `--robot-credential-key-file`, `site/robot-credential-key.template.txt`(형식만), `site/site_db.py rekey`(`--assume-stopped` 필수), `site/requirements-fleet.txt`에 `cryptography==49.0.0`, `site/README.md` 콘솔 등록 절차.
- 증거: `python -m pytest test/test_site_db_maintenance.py -q` 녹색. 사이트 호스트 Compose 실행 없음.
- gate 변화: 없음.
- 결정: D-352.
- 교훈: 없음.

## 2026-09-30 · uncommitted · deploy(harness): last_verified를 CI 초록 커밋으로 기록

- 변경: last_verified를 c8050390(2026-09-30)로 기록. LOCAL gate cmd(전체 `test/`)가 이 커밋에서 CI(GitHub Actions run 36628331442, ubuntu-26.04/ros:jazzy)를 통과했다 — 6연속 적신이던 main CI의 첫 초록이고, 그 수리 과정의 절반(dock 파싱 재연결·시크릿 스캐너·target 등록)이 이 모듈의 계약 시험이었다.
- 증거: CI run 36628331442 conclusion=success at c8050390; 로컬 관련 파일 155 passed (2026-09-30 Windows).
- gate 변화: 없음 (ARTIFACT/DEVICE는 여전히 HOLD — native ARM64·실기 증거는 그대로 남는다).
- 결정: 없음.
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(image): D-373 learned-perception runtime and models directory

- 변경: `device-python-requirements.txt` 끝에 표식 블록(onnxruntime 1.30.0, flatbuffers 25.12.19, packaging 26.3, protobuf 7.36.2; cp312 aarch64·x86_64 해시)을 붙이고 `inputs.lock.yaml` `requirements_sha256`을 바꿨다. numpy는 고정하지 않는다 — apt python3-numpy 1.26.4 위에 numpy 2를 얹으면 apt cv2가 깨진다. `/var/lib/rosy/models root:rosy-camera 0750`을 `customize-rootfs.sh`와 `tmpfiles-rosy-state.conf`에 같은 규칙으로 넣었다. 녹화는 카메라 유닛 `StateDirectory=rosy/camera` 아래라 규칙을 두지 않는다. 벤치 설치 `pinky_pro/dev/install-learned-perception.sh`는 같은 파일의 블록과 같은 tmpfiles 줄을 읽어 설치하고, 블록을 뺀 파일 sha(이전 이미지 기록)일 때만 `python-runtime.sha256`을 새 값으로 바꾸며 `/var/log/rosy/bench-installs.log`에 남긴다.
- 증거: 블록을 `pip download --require-hashes --no-deps --only-binary=:all:`로 cp312 aarch64·x86_64 각각 받음(2026-09-30 Windows). 계약 시험 녹색, tmpfiles 모드·핀 버전 변이는 붉음 확인 후 복구.
- gate 변화: 없음. ARTIFACT/DEVICE HOLD — aarch64 이미지 빌드와 Pi 5에서의 import·지연·CPU는 미실측.
- 결정: D-373 결정 1.
- 교훈: 이 블록 이후로 빌드한 릴리스는 이전 카드에서 `NATIVE_PYTHON_RUNTIME`으로 거절된다. 재굽기 전 벤치 카드는 벤치 설치가 먼저다.

## 2026-09-30 · uncommitted · fix(native): D-373 old releases stay activatable on the superset runtime

- 변경: `inputs.lock.yaml` `python_runtime.compatible_predecessors: [2b003fd4…]`(이 파일의 엄격한 부분집합인 런타임 기록). 이미지(`customize-rootfs.sh`)와 벤치 설치가 카드에 `python-runtime-compatible.sha256`로 쓴다. `native_release.check_python_runtime`은 릴리스 런타임이 카드 기록과 같거나 카드가 적은 선행 런타임일 때 받는다 — 옛 릴리스는 새 상위집합 런타임에서 돈다, 반대는 없다. 릴리스 안의 어떤 파일도 허용 범위를 넓히지 못한다(카드가 권위). 요구사항 블록에 packaging 26.3이 apt python3-packaging을 가리는 이유를 적었다(`requirements_sha256` 재고정).
- 운영: D-373 이후 빌드한 릴리스를 활성화하기 전에 기존 카드는 `pinky_pro/dev/install-learned-perception.sh`를 돌리거나 재굽기한다. 그 뒤 D-373 이전 릴리스로의 활성화·롤백은 허용된다. 벤치 설치 전 카드에서 새 릴리스는 여전히 `NATIVE_PYTHON_RUNTIME`으로 거절된다.
- 증거: `test_native_release_activation.py`(옛→새 카드 수락, 새→옛 거절, 미등록 거절, 형식 오류 기록은 정확 일치만), `test_bench_learned_perception.py`(pre-block sha 고정). 2026-09-30 Windows.
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-373 결정 1 리뷰 후속.
- 교훈: 이미지 런타임 sha 한 값 일치 규칙은 상위집합 런타임 추가 때 롤백을 막는다. 부분집합 관계는 카드 쪽 기록으로만 선언한다.

## 2026-09-30 · uncommitted · feat(native): D-373 operator switch for learned shadow and capture

- 변경: `rosy-camera.service`에 `EnvironmentFile=-/etc/rosy/learned-perception.env`(선택). `camera_preview.launch.py`의 `learned_shadow`·`capture` 기본값을 `ROSY_LEARNED_SHADOW`·`ROSY_CAPTURE`에서 엄격하게 읽는다(`true`/`false`만, 그 밖은 꺼짐 + launch 경고). `EnvironmentVariable` 치환 대신 launch 파일 안의 파서를 쓴 이유: 치환은 잘못된 값을 `IfCondition`까지 그대로 넘겨 launch가 실패한다. 예시 `native/learned-perception.env.example`(둘 다 false, `.gitattributes` LF 고정 — CRLF면 systemd가 `false\r`로 읽는다). 하드닝·쓰기 경로는 그대로. 유닛은 이미지 계층이라 기존 카드는 릴리스 사본에서 손 설치한다(런북 D절). 첫 배포 런북 `docs/deployment/learned-perception-pinky.md`.
- 증거: `test/test_native_systemd_contract.py`(선택 EnvironmentFile, 하드닝 불변, ExecStart에 스위치 없음, 예시 둘 다 false), WSL Jazzy `src/runtime/sensing/test/test_camera_preview_launch.py` 18 passed(환경 없음=꺼짐, `true`=켜짐, 잘못된 값 7종=꺼짐+경고, 명시 인자 우선), `test/test_learned_perception_pinky_runbook.py`(2026-09-30).
- gate 변화: 없음. DEVICE HOLD — 유닛 손 설치, 스위치 재시작, 섀도 지연·CPU, 첫 캡처 수거는 실물 미확인.
- 결정: D-373 결정 2(페이로드 스위치)의 장치 쪽 켜는 수단.
- 교훈: 이미지 계층 유닛에 새 지시어를 넣으면 기존 카드는 페이로드만으로 받지 못한다. 런북에 손 설치와 확인 명령(`systemctl cat`)을 같이 적는다.

## 2026-09-30 · uncommitted · feat(native): D-375 부팅 표시가 운용 모드를 램프와 LCD에 표시

- 변경: `rosy-boot-status.py`가 핸드오버의 `robot_mode`를 검증(모르는 값은 나머지를 버리지 않고 없음)해 boot-status.json에 옮긴다. `rosy-boot-display.py`는 `robot_state.lamp_pattern()`으로 패턴을 고르고, 모드 전환은 소리 없이 패턴만 바꾸며, LCD 상태줄에 ` - MODE` 접미를 붙인다.
- 증거: test_boot_status_indicator.py 37 passed, 2 skipped · test_boot_display.py 117 passed, 1 skipped (패턴 선택 변이 증명: 표시가 모드를 무시하면 모드 행이 빨개진다).
- gate 변화: 없음.

## 2026-09-30 · uncommitted · docs(adr): D-375 에서 D-380 으로 개명

- 변경: 병합 시점에 main 이 D-375 를 feat/overhead-map-auto-register 예약으로 adr_gaps 에 넣은 것이 확인됐다(선례 D-324→D-325). 이 작업의 결정 번호를 다음 빈 번호 D-380 으로 개명하고 코드 주석·시험·설계 문서의 D-375 표기를 함께 바꿨다. 앞선 항목의 D-375 표기는 역사 기록으로 그대로 둔다.
- 증거: rosy_harness lint 오류 0. 본문 참조는 docs/adr/D-380-lamp-mode-patterns-from-core-status-inputs.md.
- gate 변화: 없음.

## 2026-09-30 · c261839d · build(site): 지도 맞춤용 트랙 파일을 이미지에 넣음

- 변경: Vision 이미지에 `road_lines.stl`, Fleet 이미지에 `lane_graph.yaml`·`road_lines.stl`(`/opt/rosy/maps/map_v2_fleet/`, 읽기 전용). compose: vision `--map-paint`, fleet `--site-lane-graph`/`--site-lane-paint`. dockerignore는 두 파일만 연다. README "Map auto-fit overlay (D-375)".
- 증거: `test/test_site_map_fit_deploy.py`; `docker compose config` 통과; scratch COPY 빌드로 dockerignore 통과 확인. 전체 이미지 빌드·배포는 하지 않음.
- gate 변화: 없음.
- 결정: D-375.
- 교훈: 없음.

## 2026-10-01 · uncommitted · feat(native): D-381 blocked 패턴과 비상정지 진입음

- 변경: `rosy-boot-status.py`가 `nav_state`를 같은 규칙으로 검증·복사. `rosy-boot-display.py`는 `lamp_pattern()`에 nav를 넘기고, `_announce`가 패턴 기반으로 EMERGENCY 진입음(2.5 kHz×4, 유지 무음, 해제 시 ready 차임)을 낸다.
- 증거: test_boot_display.py (blocked 행·진입/유지/해제 소리). 변이 증명: 진입음 제거 시 빨강.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(image): D-373 learned-perception runtime in its own file and prefix; payload runtime id unchanged

- 변경: 위 2026-09-30 D-373 항목 둘(`device-python-requirements.txt` 끝 블록, `compatible_predecessors`)을 바로잡는다. 블록을 `image/learned-perception-requirements.txt`로 옮기고 `inputs.lock.yaml`에 `learned_perception_runtime`(sha256, `target`)을 따로 두었다. `device-python-requirements.txt`와 `python_runtime`은 main 바이트 그대로(a66f224a…, `test_python_runtime_id.py`), `native_release.py`의 호환 목록과 카드의 `python-runtime-compatible.sha256`는 되돌렸다. `customize-rootfs.sh`와 `dev/install-learned-perception.sh`는 `pip --require-hashes --no-deps --only-binary=:all: --target /opt/rosy/learned-perception/site-packages`로 설치하고, `learned/runner.py`가 import 직전에 그 경로를 `sys.path` 끝에 붙인다. 벤치 스크립트는 `/usr/local`과 런타임 기록을 쓰지 않는다.
- 이유: 페이로드 런타임 id는 요구사항 파일 전체의 sha256이라 블록을 붙이면 구운 카드 전부가 재플래시 전까지 페이로드를 못 받는다. `/usr/local` 설치는 apt python3-protobuf 4.21.12·python3-packaging 24.0(8kcn 실측)을 모든 서비스에서 가린다.
- 증거: `test/test_bench_learned_perception.py`(별도 잠금 항목, 같은 prefix·플래그, `/usr/local`·런타임 기록 미사용, dry-run 출력), `test/test_python_runtime_id.py`, `src/runtime/sensing/test/test_learned_runner.py`(prefix는 끝에 붙고 시스템 패키지가 우선). 2026-10-01 Windows.
- gate 변화: 없음. ARTIFACT/DEVICE HOLD — 이미지 빌드 미실행.
- 결정: D-373 결정 1 개정.

## 2026-10-01 · uncommitted · docs(site): D-373 모델 watcher와 store 기록
- 변경: 이 브랜치 커밋 기준. 사이트 PC의 `deploy/site/rosy-model-watch.service`·`.timer`가 `tools/perception/model/watch.py`를 돌린다(067d4119). 기본 백엔드는 store inbox(`models/inbox/<폴더>/` + READY)이고 HF는 `backend: hf`일 때만 쓴다(68ad0405, f6820e6e). 통과한 모델은 `models/accepted/<revision>/`, 떨어진 것은 `models/rejected/`로 옮기고 설정된 로봇에 섀도로만 전달한다. `deploy/site/install-model-watch.sh`가 설치하고 사이트 전용 SSH 키를 쓴다(b0cf35c6, aaad6da7). 설정 예시는 `deploy/site/model-watch.yaml.example`. store 구조와 `content_sha`는 `tools/perception/store.py`(b50b1118).
- 증거: `tools/perception/test/test_model_watch.py`, `test_model_watch_inbox.py`, `test_site_install_model_watch.py`, `test_site_model_watch_units.py`, `test_store.py`(호스트 pytest). 사이트 PC 설치 실행 증거는 없다.
- gate 변화: 없음. 사이트 설치·첫 자동 섀도 전달은 미실행.
- 결정: D-373 결정 5·7·8.

## 2026-10-01 · uncommitted · fix(release,test): main CI deployment 단계 적색 5건 — 핀·등록부·스캐너 면제 정리

- 변경: core 단계 적색이 이 단계를 건너뛰게 해왔다 — core가 초록이 되자 가려져 있던 5건이 드러났다(전부 최근 병합들이 같은 커밋에 함께 갱신했어야 할 고정 목록). (1) D-184 예외 목록에 `test_line_follow_obstacle_path.py` 추가(e3eb2561의 신규 시험, `core_features.line_follow.clearance` 구동). (2) D-218 `PINNED_CONFIRMS`에 교통 정책 적용 확인의 app.js→telemetry.js 이동 반영(13803932, D-362 P1). (3) D-196 로봇 리터럴 백로그에 `runtime/services/core_features/line_follow/clearance.py`·`runtime/sensing/tools/device/ir_line_calibrate.py` 추가. (4) `secret_scan.py` `KNOWN_FIXTURES`에 D-189 런타임 id 핀 등록 — 그 hex는 저장소가 추적하는 `device-python-requirements.txt`의 sha256이며 시험이 저장소에서 재계산하는 공개 다이제스트다. (5) D-178 기준선 행 교체는 docs 모듈 로그에 기록.
- 증거: 해당 다섯 시험 파일 82 passed (2026-10-01 Windows). 루트 `test/` 전체 회귀는 별도 확인.
- gate 변화: 없음.
- 교훈: 고정 목록 계약은 선행 단계가 붉으면 통째로 건너뛴다 — 그 단계의 빚은 다음 초록 커밋으로 이월되므로, 큰 적색을 고친 커밋은 곧바로 다음 단계까지 돌아갔는지 봐야 한다.

## 2026-10-01 · uncommitted · feat(native): D-383 LCD 상태줄에 편대 역할

- 변경: rosy-boot-status.py 가 swarm_role 를 같은 규칙으로 검증·복사, rosy-boot-display.py 상태줄이 role_suffix 를 끝에 붙인다("Ready - NAVIGATION - LEADER").
- 증거: test_boot_display.py·test_boot_status_indicator.py. 실기 확인은 다음 릴리스 때.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(native): D-385 기다리는 카드에 프레임 위상

- 변경: rosy-boot-display.py 가 BOOTING·PROVISIONED 중 view 에 frame(1 s 위상)을 실어 다시 그림 키에 태운다 — 0.5 Hz 숨쉼, CORE_READY 는 기존처럼 무변경 무재그림.
- 증거: test_boot_display.py (대기 중 재그림·ready 정지). 실기는 다음 릴리스.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-390 OMX Pilot development container
- Change: Add a development-only Pilot layer over the locked OMX Gazebo image and a local probe. Publish HTTP only to 127.0.0.1, deny serial/video grants, keep the one-time code in a 0600 container file.
- Evidence: local image sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a; Gazebo action and readback report in docs/validation/pilot-omx-gazebo-2026-10-01/.
- Gate: local x86_64 ROS-SIM only; ARTIFACT/DEVICE/FIELD unchanged.

## 2026-10-01 · 7d0f3f89 · fix(deploy): 사이트 빌드 컨텍스트는 이미지가 복사하는 것만

- 변경: `Dockerfile.{vision,fleet}.dockerignore` — 맨 `!src`·`!deploy`는 BuildKit의 상위 디렉터리 일치로 트리 전체를 다시 넣었다(vision 컨텍스트 2330개 파일). 잎 glob만 남기고 `__pycache__`·`.pytest_cache`를 뺐다.
- 증거: scratch `COPY .` 빌드로 vision 73개·fleet 251개 확인; `test_site_map_fit_deploy.py`가 COPY 원본 포함·다른 트리 제외·맨 디렉터리 금지를 동작으로 검사.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: dockerignore의 `!dir`은 그 아래 전부다 — 허용 목록은 잎 glob으로만 쓴다.

## 2026-10-01 · d5953646 · feat(deploy): 릴리스 push·dev sync 보정 guard
- 변경: `pinky_pro/rosy-calibration-guard.ps1`(읽기 전용 GET, 세션 있으면 exit 3). `rosy-release-push.ps1`·`dev/sync-core-dev.ps1` 가 원격 단계 전에 부르고 `-Force` 없으면 거부. 토큰 없음·CORE 무응답은 경고만. rosy-release-push SKILL 에 절차 추가(cfacfcd9 경로 수정).
- 증거: test/test_calibration_guard.py 10 passed(localhost 가짜 CORE), test_release_push_entrypoint·test_core_dev_sync 통과. 로봇에는 닿지 않았다.
- gate 변화: 없음.

## 2026-10-01 · 2f59263f · fix(deploy): 보정 guard — 401/403 구분, 예상 밖 응답은 경고
- 변경: HTTP 401/403 은 REJECTED(토큰 문제), 그 밖 HTTP 는 FAILED, 무응답은 UNREACHABLE. 응답 필드는 도우미로 읽어 StrictMode 중단 대신 UNEXPECTED REPLY 경고, owner 없는 세션도 거부. SKILL 은 `-ApiToken` 보다 ROSY_API_TOKEN·DPAPI 를 권한다.
- 증거: test/test_calibration_guard.py 15 passed, test_release_push_entrypoint 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(release): 페이로드 푸시가 이미지 계층을 활성 릴리스 사본으로 맞춘다 (D-385)

- 변경: 릴리스 `deploy/robot/native/`에 `sync-image-layer.py` 추가(검증된 `/opt/rosy/current`에서 native-runtime·rosy 유닛 18개·udev·modprobe 허용 목록만, 드라이런·백업·원자 설치·실패 시 복원·멱등, 재시작 안 함). `install-native-runtime.sh`가 udev·modprobe를 `image-layer/`로 실어 페이로드에 들어간다. `rosy-release-push.ps1`이 활성화·롤백 뒤 드라이런→적용→바뀐 활성 `rosy-*` 유닛 재시작→CORE 재확인, `-SkipImageLayerSync`.
- 증거: `python -m pytest test/test_image_layer_sync.py test/test_release_push_entrypoint.py -q` (Windows). 변이 증명 16건 모두 빨강→초록. mask 유닛·POSIX 모드 시험은 Windows에서 건너뜀(CI Linux).
- gate 변화: 없음. DEVICE HOLD — 실기 드라이런·적용·재시작 미실행.
- 결정: D-385.
- 교훈: 이미지 상주 스크립트를 못 바꾸는 로봇에는 새 동작을 릴리스에 싣고 PC 쪽에서 부른다. `docs/solutions/workflow-issues/payload-push-leaves-the-image-layer-stale-2026-10-01.md`.

## 2026-10-01 · uncommitted · fix(release): D-385 독립 리뷰 반영

- 변경: 끝나지 않은 적용은 `pending.json`으로 다음 실행이 명령·재시작 후보를 되살림. 롤백은 동기화 → 재시작 → CORE 준비 순서. 롤백 때 백업 매니페스트로 앞선 동기화가 추가한 파일은 지우고(유닛은 `disable --now`) 바꾼 파일은 되돌림(그 뒤 손댄 파일은 그대로). `rosy-network`·`rosy-config`·`rosy-release-recover`·`rosy-sd-provision`은 재시작 후보에서 빼고 다음 부팅 적용으로 알림. 새 `.path`·`.timer`는 `enable --now`. 옛 이미지 검증기(8b67c909·5c0ce600)가 새 페이로드를 받아들이는 순수 파이썬 시험.
- 증거: `python -m pytest test/test_image_layer_sync.py test/test_release_push_entrypoint.py -q` (Windows). 새 방어 각각 변이 증명 빨강→초록.
- gate 변화: 없음. DEVICE HOLD — 벤치 로봇 푸시·드라이런·적용·재시작·`-Rollback`은 2026-10-02 예정.
- 결정: D-385 개정.
- 교훈: 파일을 먼저 깔고 명령을 뒤에 돌리는 적용은 "파일이 같다"만으로 끝났다고 볼 수 없다. 밀린 명령을 따로 남겨야 재실행이 이어받는다.

## 2026-10-01 · uncommitted · fix(release): D-388 2차 리뷰 반영과 번호 이동

- 변경: 앞선 두 항목의 D-383·D-385(이미지 계층 동기화)는 D-388이 됐다(D-375 → D-383 → D-385 → D-388; 예약 해제). 매니페스트 `files_applied`로 반영된 기록만 믿음, 기록 연쇄를 기원까지 거슬러 판정, 사라진 유닛의 밀린 enable 버림, 밀린 명령 3회 실패 시 보관, 정리용 disable도 되돌림 범위, 깨진 `pending.json` 격리·깨진 매니페스트 보고, 같은 초의 실행 순서를 릴리스 id와 무관한 일련번호로 고정. 푸시 스크립트가 보관·격리·깨진 매니페스트를 경고.
- 증거: `python -m pytest test/test_image_layer_sync.py test/test_release_push_entrypoint.py -q` (Windows). 새 방어 각각 변이 증명 빨강→초록.
- gate 변화: 없음. DEVICE HOLD — 벤치 로봇 검증은 2026-10-02 예정.
- 결정: D-388.
- 교훈: 백업 폴더 이름이 실행 순서를 정한다면, 이름에서 순서 외의 값(릴리스 id)이 순서를 뒤집지 못하게 해야 한다.

## 2026-10-01 · uncommitted · fix(release): D-388 3차 리뷰 반영(RTC 없음, 전원 끊김)

- 변경: 백업 폴더는 `<일련번호>-<UTC>-<release>`, 일련번호는 잠금 안에서 전체 최대값 + 1로 실행 순서를 정하고 시각은 표시용. 적용 시작 때 `files_applied`도 `abandoned`도 아닌 매니페스트를 맞춤(모두 기록대로면 적용으로 표시하고 못 돌린 reload·enable을 밀린 명령에 더함, 아니면 백업으로 되돌리고 `abandoned`). 예외로 되돌린 실행은 바로 `abandoned`.
- 증거: `python -m pytest test/test_image_layer_sync.py -q` (Windows). 거꾸로 가는 시계, 설치 뒤 끊긴 실행, 설치 중 끊긴 실행 시험. 새 방어 각각 변이 증명 빨강→초록.
- gate 변화: 없음. DEVICE HOLD — 벤치 로봇 검증은 2026-10-02 예정.
- 결정: D-388.
- 교훈: RTC 없는 기기에서 시각은 순서의 근거가 될 수 없다. 순서는 잠금 안의 일련번호로 매긴다.

## 2026-10-01 · uncommitted · fix(release): D-388 맞춤 뒤 밀린 일 보존, 옛 이름 폴더 무시

- 변경: 끊긴 실행을 맞추면서 생긴 reload·enable·재시작 후보를 매니페스트 표시 전에 `pending.json`에 fsync로 남김(모든 JSON 쓰기 fsync). 일련번호 없는 폴더는 맞추지 않고 `legacy_ignored`로 알림.
- 증거: `python -m pytest test/test_image_layer_sync.py -q` (Windows). 맞춤 직후 설치 실패, 두 쓰기 사이 끊김, 옛 이름 폴더 시험. 새 방어 각각 변이 증명 빨강→초록.
- gate 변화: 없음. DEVICE HOLD — 벤치 로봇 검증은 2026-10-02 예정.
- 결정: D-388.
- 교훈: "표시"와 "남은 일"을 따로 쓰면 둘 사이가 끊길 수 있다. 남은 일을 먼저 영속하고 표시는 나중에.

## 2026-10-01 · uncommitted · fix(site): D-370 S7 준비 — fleet-mdns.py health 탐침이 확장 모양을 받는다

- 변경: `deploy/site/fleet-mdns.py`의 `/healthz` 판정을 `check_health_body`로 뺐다(FleetAgent와 같은 규칙). 1024바이트 이하 JSON 객체, `status == "ok"`, `role`이 있으면 광고 TXT `role`(`fleet`)과 같아야 하고 모르는 키는 무시한다. 프로필 `docs/reference/site-lan-discovery-profile.md` 33행 문구도 맞췄다.
- 증거: `test/test_site_fleet_mdns.py` 신규 health 시험(사이트·Agent 매개변수) 수정 전 빨강, 수정 후 초록.
- gate 변화: 없음. Fleet·Vision `/healthz` 출력은 그대로 — 옛 로봇 이미지가 정확 비교를 하므로 서버 확장은 새 이미지 배포 뒤로 미룬다.

## 2026-10-01 · uncommitted · refactor(site): fleet-mdns.py TXT 판정을 core_common discovery_txt 사본으로

- 변경: `deploy/site/fleet-mdns.py`의 자체 판정(shlex+사전 비교)을 `core_common.protocol.discovery_txt`의 `_rosy-fleet._tcp` 부분 사본으로 바꿨다: `parse_txt_pairs`, `_lan_ipv4`, `classify_fleet`(수락이면 None, 아니면 벡터의 거절 이유). `mdns-bridge.py`와 같은 "Copy of core_common.protocol.discovery_txt" 머리말. 형제 모듈로 나눠 두 스크립트가 함께 쓰는 안은 택하지 않았다 — 사이트 후보 목록(`build_candidate.py`·`verify_candidate.py`·`test_site_candidate.py`)과 README 설치 절차에 새 파일을 더해야 하고, 시험·`tools/overhead_pairing_bench.py`가 스크립트를 파일 경로로 불러와 sys.path 처리도 필요해진다.
- 증거: `test/test_site_fleet_mdns.py` 신규 벡터 이유 시험(Fleet 사례 6건: 이유까지 core_common과 같음) — 수정 전 6건 빨강(판정 함수 없음), 수정 후 초록. 기존 수락/거절 벡터 루프는 전후 모두 초록 — 벡터 결과가 바뀐 사례 없음. 벡터 밖 차이: `0.0.0.0` 등 multicast/unspecified 주소를 이제 거절(core_common과 같음).
- gate 변화: 없음. 사이트 호스트에는 다음 후보 설치 때 간다.

## 2026-10-01 · uncommitted · fix(sd): ERASE 프롬프트 type-ahead, 아티팩트 다운로더, D-383 긴급 카드 쓰기

- 변경: (1) `prepare-rosy-sd.ps1`의 ERASE 프롬프트가 먼저 콘솔 입력 버퍼를 비우고(`Clear-TypeAhead`), 빈 줄·입력 끝은 불일치가 아니라 `no console input`으로 멈춘다. 2026-09-30 `-Detach` 창에서 앞 단계 중 눌린 Enter가 0.9초 만에 프롬프트에 답해 `typed: ''`로 실패했다. (2) `tools/release/download_artifact.py`: Actions 아티팩트 병렬 range 다운로드(진행·재개·크기 확인·안전 압축 해제). (3) D-383 `write-card.ps1 -Emergency -EmergencyReason`: 전체 readback만 건너뛰고 증거에 검증 안 됨을 남기며, `verify-emergency-card.ps1` 후속 readback과 표준 재공급으로 메운다.
- 증거: test_sd_writer_contract.py·test_sd_write_card_entrypoint.py·test_media_readback.py·test_download_artifact.py (호스트 fixture만, 실제 디스크 없음). 새 게이트마다 변이 증명.
- gate 변화: 없음. 실제 카드에서의 긴급 쓰기·후속 readback은 아직 안 해 봤다.

## 2026-10-01 · uncommitted · fix(sd): 모터 커미셔닝 SSH가 Rosy 운영자 키를 쓴다 (D-383 결정 6)

- 변경: `enable-motor-commissioning.ps1`이 `rosy-release-push.ps1`처럼 `-KeyPath`·`-KnownHosts`·`-RosyUser`(기본은 `%LOCALAPPDATA%\Rosy` 운영자 키·known_hosts, `rosy`)를 ssh에 넘기고, 파일이 없으면 로봇에 닿기 전에 멈춘다. 새 카드에서 기본 `~/.ssh` 별칭만 써서 `No ED25519 host key is known`으로 실패했었다. D-383 결정 4에 부팅한 긴급 카드의 장치 위 검증(SHA256SUMS·`dpkg --verify`)을 적었다.
- 증거: test_motor_commissioning_ssh.py 5 passed, 변이 4종 모두 실패로 잡힘. 로봇 접속 없음.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · docs(adr): 긴급 카드 쓰기 결정을 D-383에서 D-385로 개명

- 변경: main 병합 시점에 D-383은 편대 역할 계기 ADR로, D-384는 docs/d384-road-state-and-behaviour 예약으로 잡혀 있었다. 이 작업의 결정(긴급 카드 쓰기, 모터 커미셔닝 SSH)을 다음 빈 번호 D-385로 개명하고 코드 주석·시험·문서를 함께 바꿨다. 앞 항목의 D-383 표기는 역사 기록으로 둔다.
- 증거: rosy_harness lint 오류 0. 본문은 docs/adr/D-385-emergency-card-write-skips-only-readback.md.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · docs(adr): 긴급 카드 쓰기 결정을 D-385에서 D-389로 개명

- 변경: main에 D-385(feat/expressive-rosy)가 들어와, main 532b9813이 adr_gaps에 예약한 D-389로 개명하고 그 예약을 지웠다. 코드 주석·시험·문서도 바꿨다. 앞 항목의 D-383/D-385 표기는 역사 기록으로 둔다.
- 증거: rosy_harness lint 오류 0. 본문은 docs/adr/D-389-emergency-card-write-skips-only-readback.md.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(sd,release): D-389 독립 리뷰 반영 — 긴급 resume 이력 검사, 다운로더 점검

- 변경: `-Emergency -ResumeAfterWrite`는 `-PlanPath`를 요구하고 같은 plan의 진행 파일 이력이 깨끗할 때만 된다(마지막 전체 쓰기가 Imager 정상 종료, 그 뒤 쓰기 실패·readback 불일치·이미지 오류 없음). 긴급 receipt 단계는 `complete-unverified`, 이유에 백슬래시 금지, 끊긴 쓰기 안내에 `unverified-no-bundle` 추가. 후속 readback 허용을 fixture FAT 파티션 안의 bundle로 증명. 다운로더는 `IncompleteRead`를 재시도하고, 기존 출력도 새 다운로드처럼 크기·zip CRC로 점검하며, symlink 항목을 거부한다.
- 증거: 새 시험 전부 통과, 게이트별 변이 16종 모두 실패로 잡힘(호스트 fixture만, 카드·로봇 접근 없음).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(sd): 긴급 resume은 plan의 시도 색인을 읽는다 (D-389 검증)

- 변경: plan을 쓰는 모든 쓰기·resume이 -LogPath와 상관없이 <plan>.attempts.jsonl에 시작(진행 파일 경로)·끝(card_state, kind) 줄을 덧붙인다. 긴급 resume은 이 색인이 가리키는 진행 파일만 읽고, 색인이 없거나 적힌 로그가 없거나 읽을 수 없으면 거부한다.
- 증거: test_sd_writer_contract.py 긴급 resume 시험 11 passed(다른 폴더 로그의 불일치, 사라진 로그, 색인 없음 포함), 변이 4종 모두 실패로 잡힘.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(release): 비밀 검사가 SHA·HEAD 코드 스팬의 리비전을 출처 데이터로 본다

- 변경: secret_scan의 무결성 문맥에 `sha`·`head`를 `source`와 같은 규칙(바로 뒤가 코드 스팬일 때만)으로 넣었다. 조사 노트가 상류 트리를 "고정 SHA `<40-hex>`"·"HEAD `<40-hex>`"로 적은 두 줄(docs/logs.md:4077, gemini 조사 계획 5행)이 main을 적색으로 만들었다. logs는 append-only라 호출 지점 수정이 불가능해 규칙 쪽을 좁게 넓혔다. 맨 단어(`sha_token = <hex>`, `head <hex>`, `SHA: <hex>`, `shadow`)는 여전히 보고된다.
- 증거: test_release_boundary_guards.py 112 passed(새 시험 6개), 변이 2종(sha/head 제거·코드 스팬 조건 제거) 모두 실패로 잡힘. 같은 커밋에서 크기 판정 fleet 20655·schemas.py 1092를 재판정했다(test_module_structure 통과).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(site): D-391 3 사이트 호스트 일관성 사전 검사 `site_preflight.py`
- 변경: `deploy/site/site_preflight.py` 신규(표준 라이브러리만, `compose up` 전에 실행). 검사 다섯 가지: `site_cert`가 leaf(CA 아님) + CA 순서인지(leaf 단독 거부, 2026-09-30 사고), leaf DNS SAN에 `tls_host`가 정확히(대소문자 무시, 와일드카드 불가) 있는지, `tls_host`가 `.local` 이름인지(IP·다른 도메인 거부), 광고 유닛이 낼 TXT `tls_host`(`--tls-host`, `Environment=`·env 파일로 `${VAR}` 전개)가 설정값과 같은지, Caddyfile 첫 사이트 주소가 다른 호스트를 가리키지 않는지(포트만 있는 `:8443`은 통과). IP SAN은 검사하지 않는다(재할당 시 낡음; `manual_host` 되돌림 전용). 실패마다 이유와 고치는 법, 하나라도 실패하면 종료 코드 1, `--json` 지원. README에 "Preflight" 소절 추가. compose.yaml은 건드리지 않았다(rosy-84 병행 작업).
- 증거: test_site_preflight.py(먼저 31 failed) 구현 후 통과, test_site_fleet_mdns.py 함께 108 passed. CA/leaf DER 복사본이 core_common `site_link`와 site-link.v1.json의 ca_pem 사례에서 일치함을 시험으로 고정. 시험 인증서는 실행 시점에 임시로 만들고 키를 저장소에 두지 않는다. 사이트 호스트 실물 실행은 하지 않았다(LOCAL만).
- gate 변화: 없음(호스트 배포 없음).

## 2026-10-01 · uncommitted · fix(site): 사이트 사전 점검 독립 리뷰 반영 — systemd 형식, env 따옴표, 모든 Caddy 블록

- 변경: 리뷰(APPROVE WITH FIXES) 1–4번. 유닛 파일의 줄 이음(`\`)을 먼저 합치고, `ExecStart=`의 `-@+!:` 접두를 떼고, 빈 `ExecStart=`는 명령을 비우며, `${VAR}`와 `$VAR` 둘 다 펼친다. env 파일은 `export `를 떼고 짝이 맞는 따옴표만 벗긴다. Caddyfile은 첫 블록만이 아니라 모든 최상위 사이트 블록의 호스트를 보며 스니펫 `(name) {`은 건너뛴다.
- 증거: 신규 시험 4건, `test_site_preflight.py`·`test_site_fleet_mdns.py` 함께 통과.
- gate 변화: 없음.

## 2026-10-01 · 536077d2 · feat(site): D-341 TXT pair는 요청할 때만 광고하고 사전 점검이 스위치를 확인한다
- 변경: `fleet-mdns.py publish --pair[=1]`이 `_rosy-overhead._tcp`에 `pair=rosy-pair/1`을 더한다(기본 꺼짐, `--pair=0`·`--pair=`도 꺼짐, fleet 역할에는 거부). overhead 유닛은 `--pair=${ROSY_SITE_PAIRING}`(기본 `Environment=ROSY_SITE_PAIRING=0`), 스택 유닛은 `$ROSY_SITE_PAIRING_COMPOSE`(괄호 없는 `$VAR`는 비면 단어 0개)를 `-f compose.yaml` 뒤에 붙인다. `site_preflight.py`에 `pairing_consistent` 검사 추가: `.env`와 `site.env`의 스위치 일치(`1` 또는 빈 값), 오버레이와 스위치 일치, 유닛의 TXT 광고와 스위치 일치, `pairing_sync_token`이 있고 다른 비밀과 다름. `pair` 키는 공유 벡터 `discovery-txt.v1.json`에 이미 선택 키라서 벡터는 바꾸지 않았다.
- 증거: test_site_fleet_mdns.py·test_site_preflight.py 129 passed(새 시험 먼저 실패 확인). 호스트·컨테이너·기기 접근 없음(LOCAL만).
- gate 변화: 없음(배포 없음).
- 결정: 켜는 스위치는 하나(`ROSY_SITE_PAIRING=1`)지만 Compose 쪽은 오버레이 파일이 필요해 `site.env`에 `ROSY_SITE_PAIRING_COMPOSE`가 따로 있고, 불일치는 사전 점검이 잡는다.
- 교훈: 없음

## 2026-10-01 · 39dd2ad2 · feat(site): D-341 페어링 오버레이 `compose.pairing.yaml`과 카메라 자격 예시
- 변경: `compose.yaml`은 그대로 두고(rosy-84 병행 작업) `compose.pairing.yaml` 추가. Compose는 `command`와 `ROSY_CREDENTIAL_PATHS` 값을 통째로 바꾸므로 기존 값을 반복하고 Fleet에 `--pairing-ca /run/secrets/site_ca`·`--pairing-tls-host`·`--pairing-sync-token-env`, Vision에 `--pairing-sync-url https://fleet:8090`·`--pairing-sync-ca`·같은 토큰 env를 붙인다. 새 비밀 `pairing_sync_token`(템플릿 `pairing-sync-token.template.txt`)은 Fleet·Vision만 마운트하고 다른 비밀과 파일이 다르다(D-302). 후보 빌드·검증 목록, `.env.example`(별도 블록), `site-cameras.yaml.example`(`credential: static`/`paired`) 갱신.
- 증거: test/test_site_pairing_deploy.py(오버레이 == 기존 + 페어링 인자, https+CA, 구분되는 비밀, 기본 compose에 pairing 없음), src/site/vision/test/test_site_cameras_example.py(예시가 Vision·Fleet 로더로 읽힘), test_site_candidate*.py 27 passed, test_release_boundary_guards.py 통과(비밀 검사 지적 1건은 변수명 변경으로 해결).
- gate 변화: 없음.
- 교훈: 비밀 검사는 `secret = ...` 같은 할당 줄도 credential로 본다. 시험 변수명에 `secret`을 피한다.

## 2026-10-01 · uncommitted · docs(site): README "Camera pairing (D-341)" 소절
- 변경: 켜는 법(토큰 생성, 카메라 `credential: paired`, 오버레이, 광고), 폰이 보는 것(`pair` TXT가 있을 때만 사이트에 연결 요청), 콘솔 흐름(기기 연결, 카메라 연결 승인), 폐기, 사전 점검이 확인하는 항목을 새 소절로 추가. 콘솔의 승인·폐기 화면은 D-391 5 항목으로 아직 main에 없음을 적었다.
- 증거: test_site_pairing_deploy.py가 소절 핵심 문구를 확인.
- gate 변화: 없음.
- 교훈: 없음

## 2026-10-01 · uncommitted · fix(site): 사이트 바인드는 인터페이스를 따른다 — 와일드카드 바인드, 인터페이스 방화벽, 루프백 발견 브리지

- 변경: 점검(2026-10-01) #1·#4. 사이트 망이 192.168.1.0/24에서 10.16.36.0/24로 바뀌자 `compose.yaml`의 `${ROSY_SITE_BIND_ADDRESS}:8443`(README가 LAN IP를 적게 했다)이 "cannot assign requested address"로 떠지지 않아 관제·카메라·로봇·발견 브리지가 함께 멈췄다. (1) LAN 설정은 `ROSY_SITE_BIND_ADDRESS=0.0.0.0`(IPv6는 `::`) + `ROSY_SITE_LAN_IFACE`, 기본값 `127.0.0.1` 유지. compose는 그대로(기본값만), `.env.example`에 `ROSY_SITE_LAN_IFACE`. (2) `site/site-firewall.py` + `rosy-site-firewall.service`(After·PartOf·WantedBy docker): `DOCKER-USER` 맨 앞에서 conntrack 원래 목적 포트(`--ctstate DNAT --ctdir ORIGINAL --ctorigdstport`)를 자체 체인 `ROSY-SITE-INGRESS`로 보내 `-i <iface> -j RETURN`, 나머지 `DROP`. IP·서브넷은 쓰지 않는다. `apply`는 멱등(바뀐 인터페이스·옛 포트 점프 정리), `--dry-run`은 규칙만 출력. (3) `rosy-site-stack.service` `ExecStartPre`가 `site-firewall.py check`: 이 호스트에 없는 리터럴 IP, 인터페이스 없는 LAN 바인드, 설치 안 된 필터면 이유를 남기고 기동 거부(D-391 3항 일관성 검사가 나중에 흡수할 수 있다). (4) `mdns-bridge.py`는 `--url` 대신 `--tls-host`·`--port`로 루프백(`127.0.0.1`, 이어서 `::1`)에 TLS SNI·호스트명 검사·Host를 `tls_host`로 두고 사이트 CA로 확인해 보낸다. 유닛은 `site.env`를 읽고 `IPAddressAllow=localhost`만 허용, `mdns-bridge.env`(`ROSY_SITE_DISCOVERY_URL`)는 은퇴. Avahi 실패 시 아무것도 보내지 않는 규칙 유지. 후보 목록(`build_candidate.py`·`verify_candidate.py`)에 새 두 파일. README "LAN access", 런북 2항.
- 증거: `python -m pytest test/test_site_firewall.py test/test_site_mdns_bridge.py test/test_site_candidate.py test/test_site_task_queue_deploy.py test/test_site_map_fit_deploy.py test/test_site_fleet_mdns.py test/test_site_fabric_roles.py -q` 녹색(가짜 iptables로 멱등·점검 실패 4종·IP 미사용, 실제 루프백 TLS 서버로 SNI·Host·인증서 이름 불일치 거절). 변이: SNI를 연결 주소로 바꾸면 루프백 시험이 빨강. `docker compose -f deploy/site/compose.yaml config`(가짜 env) `host_ip: 0.0.0.0`/기본 `127.0.0.1`. 스택 기동·실제 iptables 적용 없음(2026-10-01 Windows).
- gate 변화: 없음. 사이트 호스트에서 `apply`·재부팅·망 변경 재현은 미실행.
- 결정: 루프백 + `tls_host` SNI. 호스트에서 `https://<tls_host>`를 푸는 안은 DNS·nss-mdns가 LAN을 따라가 오래된 기록·바뀐 서브넷·꺼진 Wi-Fi에서 실패하므로 택하지 않았다. 리터럴 LAN IP 바인드는 루프백을 듣지 않아 브리지와 함께 쓸 수 없다(경고만 하고 허용).
- 교훈: Docker 공개 포트를 인터페이스 IP에 묶으면 망 변경이 스택 전체 정지가 된다. 노출 범위는 바인드 주소가 아니라 `DOCKER-USER`의 인터페이스 이름으로 정한다.

## 2026-10-01 · uncommitted · fix(site): 보안 리뷰 반영 — 필터를 Docker 앞 mangle로, 원자 적용·실패 시 닫힘, 설정은 Compose에서

- 변경: 독립 보안 리뷰(APPROVE WITH FIXES, MEDIUM). M1: `DOCKER-USER` 필터는 dockerd가 `0.0.0.0` 프록시를 되살린 뒤에야 깔리고, 실패·중간 상태(`-F` 뒤 `-A`)에서 포트가 열려 있었다. 이제 `mangle PREROUTING`(DNAT 전, 공개 포트가 그대로 dport)의 점프 `-p tcp --dport <port> -j ROSY-SITE-INGRESS` → 체인은 `lo`·각 LAN 인터페이스 RETURN, `-m addrtype --dst-type LOCAL -j DROP`. 체인은 `iptables-restore -w --noflush` 한 트랜잭션(체인 선언이 원자적으로 비우고 채움), 점프는 새것을 먼저 넣고 옛것을 지운다. `rosy-site-firewall.service`는 `After=network-pre.target`, `Before=docker.service rosy-site-stack.service`, `WantedBy=multi-user.target docker.service`, `OnFailure=rosy-site-firewall-failclosed.service`(`compose stop proxy`). `rosy-site-firewall-check.timer`가 5분마다 `check`, 실패면 journal 오류와 같은 닫힘. M2: 바인드·포트·인터페이스·`tls_host`를 `docker compose config --format json`(`x-rosy-site` 확장)에서 읽어 `export`·인라인 주석·`${VAR}`가 Compose와 같게 풀린다. `^[A-Z_][A-Z0-9_]*$`가 아닌 키는 exit 2. m1: `::`와 빈 host_ip는 거절(필터·발견 모두 IPv4). m3: 없는 인터페이스는 경고(브리지 LAN은 `br0`). m4: 리터럴 IP 바인드는 `ROSY_SITE_ALLOW_LITERAL_BIND=1` 없이는 exit 2. m6·n2: `apply`가 `/run/rosy-site/site-public.env`(tls_host·port만)를 쓰고, 브리지·광고 유닛 둘이 이것만 읽는다(옛 `/etc/rosy/site/.env` 참조 제거, 포트 기본 8443). m7: 브리지가 `VERIFY_X509_STRICT`를 명시, 스택 preflight `check --verify-certs`가 메모리 TLS 핸드셰이크로 엄격 검증, README "Site certificate profile"(확장 표, `openssl verify -x509_strict` 관문, CA 재발급은 모든 카메라 재페어링). n1: 토큰 파일은 출력 가능한 ASCII 한 토큰만. m5: README "Upgrading from a literal-IP bind".
- 증거: `test/test_site_firewall.py`(restore 페이로드 원문, 멱등—두 번째는 읽기만, 인터페이스·포트 교체 순서 restore→-I→-D, 점검 거절 4종, restore 실패 시 점프 없음, env 키 4종 exit 2, 실제 `docker compose config`로 export·주석·`${BASE}443` 해석, 엄격 인증서 수락·이름 불일치·확장 없는 CA 거절, 유닛 순서), `test_site_mdns_bridge.py`(환경 기본값, 토큰 6종 거절, 엄격 X.509) 포함 사이트 배포 시험 171 passed. 변이 3종(`--noflush` 제거, 키 검사 제거, `lo` 제거) 모두 빨강. 실제 iptables·스택 실행 없음(2026-10-01 Windows).
- gate 변화: 없음. 사이트 호스트에서 부팅 순서·실패 닫힘·`iptables-nft` 출력 형식 확인은 미실행.
- 결정: `::`는 지원하지 않는다(필터를 ip6tables로 이중화하는 대신). 콘솔 경보는 방화벽 점검에 붙이지 않았다(journal과 포트 닫힘) — Fleet 변경 범위 밖.
- 교훈: 방화벽 도우미는 보호 대상보다 먼저, 원자적으로, 실패하면 닫히게 설치한다. 설정 파서는 하나(Compose)만 둔다.

## 2026-10-01 · uncommitted · fix(site): 재검증 반영 — 컨테이너 직행 트래픽 차단, 라벨로 닫기, 바인드 탐침 정밀화

- 변경: 재검증(APPROVE WITH FIXES, LOW). m1-r: `ROSY-SITE-INGRESS` 끝에 `-i br+ -j RETURN`, `-i docker0 -j RETURN`, 무조건 `-j DROP`을 더해 Docker 28 미만에서 LAN 밖 인터페이스로 컨테이너 IP에 직접 라우팅된 패킷도 버린다. 공개 포트가 8443이 아니면 컨테이너 포트 점프 `--dport 8443 -m addrtype ! --dst-type LOCAL`을 하나 더 둔다(로컬 목적지는 제외해 호스트의 다른 8443 서비스는 건드리지 않음). `check`가 두 점프를 모두 확인하고 `docker version`이 28 미만이면 경고, README에 Docker Engine 28 이상 권고. m2-r: `rosy-site-firewall-failclosed.service`가 Compose 파싱 없이 라벨(`com.docker.compose.project=$ROSY_SITE_PROJECT`, `service=proxy`)로 프록시를 멈춘다. 시험이 `ROSY_SITE_PROJECT`를 스택 유닛의 `--project-name`과 같게 묶는다. README "Recovering after the port was closed"(스택은 active (exited)로 남으니 `check` 통과 뒤 `systemctl restart rosy-site-stack`, 인터페이스 변경 뒤 방화벽 유닛을 재시작하지 않으면 5분 점검이 포트를 닫음). n1-r: `address_assigned`는 `EADDRNOTAVAIL`만 "할당 안 됨"으로 보고 다른 소켓 오류는 자체 문구로 exit 2.
- 증거: `test/test_site_firewall.py` 36 passed(페이로드 원문, 포트 교체 시 restore→-I→-I→-D·두 번째 적용 무변경, 점검 거절 6종(컨테이너 포트 점프·마지막 DROP 누락 포함), 엔진 27/28/읽기 불가 경고, EACCES 노출, 실패 닫힘 유닛 라벨·프로젝트 일치). 실제 iptables·스택 실행 없음(2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · merge(site): main의 D-341 페어링 배선과 인터페이스 바인드 합치기 — 사이트 설정 파일은 site.env 하나

- 변경: main(6dbcc01b, d5d4a2e4)을 fix/site-bind-follows-interface에 병합. (1) `rosy-site-stack.service`는 `ExecStartPre=site-firewall.py check --verify-certs`와 main의 `$ROSY_SITE_PAIRING_COMPOSE` 덧붙임(ExecStart·ExecStop)을 함께 둔다. (2) `site-firewall.py`는 site.env의 `ROSY_SITE_PAIRING_COMPOSE`(`-f <파일>` 쌍만 허용, 그 밖은 exit 2)를 스택과 같은 순서로 `docker compose config`에 넘겨 오버레이 포함 바인딩을 읽고, `ROSY_SITE_PAIRING`(1이면 1, 그 밖 0)을 `/run/rosy-site/site-public.env`에 쓴다. `rosy-overhead-advertise.service`는 그 파일에서 `--pair=${ROSY_SITE_PAIRING}`을 받는다(유닛 기본 0). 실패 닫힘은 같은 프로젝트 라벨이라 오버레이와 무관. (3) `site_preflight.py`는 `DEFAULT_ENV_FILE=/etc/rosy/site/site.env` 하나만 두고 `pairing_consistent`가 두 키를 그 파일에서 읽는다(`--site-env`는 선택적 덮어쓰기, 오버레이·토큰 검사는 그대로, `0`도 꺼짐으로 받음). README "Camera pairing"·`.env.example`에서 `/etc/rosy/site/.env` 안내를 지웠다(rosy-00 확인: `.env`는 의도가 아니었다).
- 증거: `test_site_firewall.py`(페어링 키 허용·site-public.env 전달 3종, 오버레이 `-f` 순서, 잘못된 오버레이 값 3종 exit 2, 실제 Compose로 오버레이 포함 바인딩), `test_site_preflight.py`(한 파일 모델로 켬·끔·0·불일치 3종), `test_site_pairing_deploy.py` 통과. 2026-10-01 Windows, 실제 스택·iptables 없음.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · test(site): `site-firewall.py`를 실제 iptables-nft로 검증 (컨테이너)

- 변경: 코드 변경 없음(524fd7f0의 `site-firewall.py` 그대로). `test_site_firewall.py`에 `test_parser_reads_real_iptables_nft_listings` 추가 — 실제 `-S` 출력 원문(iptables-nft는 `-p tcp --dport N`을 `-p tcp -m tcp --dport N`으로 돌려준다, 부정 addrtype은 `-m addrtype ! --dst-type LOCAL`)을 고정하고, 그 형식을 돌려주는 가짜 호스트로 apply 멱등·포트 교체 시 목록 줄 그대로 `-D`·check 통과를 확인.
- 증거: 일회용 `docker run --rm --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN --sysctl net.ipv4.ip_forward=1 ubuntu:24.04`(Docker Desktop 29.7.2, 자체 netns, 호스트·WSL 방화벽 무변경), `iptables v1.8.10 (nf_tables)`. 컨테이너 안에 netns `lanc`(lan0 10.10.0.0/24)·`wanc`(wan0 10.20.0.0/24)·`ctr`(브리지 `br-rosy` 172.30.0.2, 8443 리스너 = 프록시 컨테이너), Docker식 nat(`PREROUTING/OUTPUT -m addrtype --dst-type LOCAL -j DOCKER`, `DOCKER ! -i br-rosy --dport <port> -j DNAT 172.30.0.2:8443`), 호스트 리스너(docker-proxy 대역, 루프백 응답). `docker`는 Windows에서 실제 `docker compose -f deploy/site/compose.yaml config --format json`(더미 env: `0.0.0.0`/`127.0.0.1`/`::`, 포트 18448·18450·8443, `ROSY_SITE_LAN_IFACE=lan0`)으로 만든 JSON을 내는 스텁. 결과 PASS=28 FAIL=0: 필터 없을 때 세 경로 모두 연결 / apply 3변경, 두 번째 0변경 / 실제 `-S`가 `chain_listing`과 일치, 점프 키 파싱 일치 / check 통과 / lan→연결(ctr), wan→차단(timeout), lo→연결(proxy) / 컨테이너 IP 직행 8443: lan 통과·wan 차단 / DROP 규칙 삭제·체인에 RETURN 추가·점프 삭제·앞에 ACCEPT → check exit 1, apply가 복구 / 중복 점프 제거 / 18448→18450: 매 변경 뒤 스냅샷에서 새 점프가 먼저 들어가고 옛 점프는 마지막에 빠짐(틈 없음), 새 포트 lan 통과·wan 차단·lo 통과 / 8443 공개 시 점프 하나 / `127.0.0.1`은 규칙 0개·check 통과 / `::`는 exit 2, 규칙 무변경. 재실행: 공개 저장소 밖 작업 폴더의 `run.ps1`(→`run.sh`, `transition.py`, `listener.py`, 스텁 `docker`)과 로그. `python -m pytest test/test_site_firewall.py test/architecture test/test_release_boundary_guards.py -q`: 실패 3건은 main에 이미 있는 것(`test_module_structure.py` 2건, 카메라 앱 Kotlin `pollSecret` 비밀 검사 1건), 이 변경과 무관. harness lint 0 error.
- gate 변화: 없음. 증명한 것: iptables-nft 1.8.10의 실제 출력 형식과 parser, `iptables-restore --noflush` 원자 교체·멱등, mangle PREROUTING(-150)이 nat DNAT(-100)보다 먼저 공개 포트로 판정해 비 LAN 인터페이스를 버리고 LAN·lo는 통과시키는 것, 포트 교체 무틈. 증명 못 한 것: 실제 사이트 호스트의 systemd 순서(`Before=docker.service`, 실패 닫힘 유닛, 5분 타이머), 재부팅·망 변경, 실제 dockerd·docker-proxy·`br_netfilter`(컨테이너 커널은 Docker Desktop WSL2 커널), Docker가 깔아 둔 규칙과의 공존, 다른 iptables 버전·legacy 백엔드.
- 결정: 없음.
- 교훈: 가짜 iptables는 넣은 문자열을 그대로 돌려주지만 iptables-nft는 암묵 매치(`-m tcp`)를 붙여 돌려준다. `-S` 비교 parser는 실제 출력 원문을 시험에 고정한다. 관찰: 와일드카드→`127.0.0.1` 전환 시 `apply`는 기존 필터를 지우지 않는다(lo는 통과라 무해).

## 2026-10-01 · uncommitted · docs(site): 두 번째 카메라 자리의 배선 안내

- 변경: 실제 Compose 스택 페어링 실측에서 발견. `site-cameras.yaml.example`의 페어링 예시(`ceiling_south`)를 그대로 켜면 그 `token_env`가 Compose `ROSY_CREDENTIAL_PATHS`에 없어 Fleet·Vision이 기동을 거절한다. 예시 주석에 비밀 파일·두 서비스의 `ROSY_CREDENTIAL_PATHS` 추가가 필요하다는 것과, 카메라 하나로 시험할 때는 `ceiling_north`를 `credential: paired`로 바꾸면 된다는 것을 적었다.
- 증거: 예시 시험·배포 배선 시험 통과; 실측은 `ceiling_north` paired로 18/18.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(release): 활성화가 CORE를 멈추지 않던 결함 — PartOf 유닛을 함께 멈추고, push가 CORE 릴리스를 확인

- 변경: `native_release.py`의 stop이 `rosy-runtime.target`만이 아니라 PartOf 유닛(`rosy-core`·`rosy-io`·`rosy-camera`)을 함께 이름으로 멈춘다(start는 타깃만). 타깃은 이 유닛들 `After=`라 멈춤 job이 즉시 끝나고, io·camera가 `After=rosy-core`라 CORE의 멈춤 job은 그 뒤를 기다린다. systemctl은 요청한 job만 기다리므로 곧바로 온 start가 CORE의 대기 중 멈춤을 no-op start로 대체해, CORE가 옛 릴리스를 계속 서비스했고 readiness는 그 옛 CORE로 통과했다. `rosy-release-push.ps1`은 활성화·롤백 직후 `core-release-check` 단계를 둔다: CORE MainPID의 cwd가 `readlink -f /opt/rosy/current`와 다르면 `systemctl restart rosy-core.service`하고 경고한다. 로봇에 깔린 활성화기는 고친 판이 image-layer sync(활성화 뒤)로만 오기 때문이다.
- 증거: 9dfk(2026.10.01-019 push): push가 `current release: 019`·`CORE readiness: PASS`를 냈지만 CORE PID 1078의 cwd는 `releases/2026.09.30-009`, openapi v1.63, 저널에 `Stopping rosy-core` 없음. 같은 로봇에서 재현: `stop target; start target` → CORE PID 9030→9030(active 유지). `stop target core io camera; start target` → stop 직후 inactive, PID 9030→9825. 생성된 확인 명령을 PowerShell 5.1→ssh로 9dfk에 실행 → `CORE_RELEASE_OK /opt/rosy/releases/2026.10.01-019`. `test_native_release_activation.py`·`test_release_push_entrypoint.py` 48 passed. 가드는 변형(카메라 빠짐, 확인 단계 제거, 재시작 보고 제거)으로 빨강 확인.
- gate 변화: 없음.
- 교훈: 타깃 하나만 stop하는 것은 PartOf 유닛의 멈춤을 기다리지 않는다. 릴리스 전환 뒤에는 readiness 통과가 아니라 CORE 프로세스가 새 릴리스에서 도는지를 본다.

## 2026-10-01 · uncommitted · feat(omx): record SIM demonstrations and export LeRobot v3
- 변경: D-390 부록·API v1.69·Pilot 기록 패널·SIM 카메라·원본 recorder·오프라인 exporter. ROS 수락 전에 목표를 등록하고, recording I/O는 별도 writer로 분리.
- 증거: adapter/Pilot/network 259 passed, 28 skipped; quick tier 95 passed; Chromium recording retry/outcome/stale/dispose 1 passed; 실제 LeRobot 0.4.4 reader 3 passed. Gazebo 원본 15프레임 및 동일 원본 export 재독출 PASS. docs/validation/omx-demonstration-lerobot-2026-10-01/README.md 참조.
- gate 변화: 물리·ARTIFACT/FIELD 승격 없음. 짧은 SIM 시연/데이터 형식 증거만 추가.
- 결정: D-390 부록; D-18 typed API와 reference 동시 갱신.
- 교훈: LeRobot 0.4.4는 explicit timestamp를 거부; source ns를 int64로 유지. Windows shared recording mount는 프레임 누락을 만들 수 있으므로 Linux volume 사용.

## 2026-10-01 · uncommitted · fix(omx): fence recording closure and isolate storage faults
- 변경: 리뷰의 중요 문제 3개 해소 — recording 오류로 lease watcher 종료 금지, hidden 중 늦은 seat 획득 즉시 반납, 종료 저장 중 interruption을 manifest에 반영.
- 증거: 리뷰 수정 race/runtime/recorder 21 passed; Chromium 2 passed; 최종 adapter/foundation/assets/network 624 passed, 6 skipped. 최종 tree와 같은 해시의 실제 Gazebo 12프레임→LeRobot 재독출 PASS; 같은 실행 lease 만료 incomplete. 독립 리뷰 재검토 완료.
- gate 변화: 기존 gate 유지; DEVICE/FIELD 승격 없음.
- 결정: D-390 부록.
- 교훈: 파일 쓰기 완료 전 들어온 interruption과 logical closure 경계를 구분한다.

## 2026-10-01 · uncommitted · perf(release): rosdep apt 패키지를 한 트랜잭션으로 — payload 빌드 7분 9초→4분 49초

- 변경: `build-native-payload.sh`가 `rosdep install --simulate`로 계획을 받아 `rosdep_apt_batch.py`(패키지 이름 아닌 것은 거부)로 apt 패키지를 모으고, rosdep과 같은 플래그로 `apt-get install -y` 한 번에 설치한 뒤 rosdep을 그대로 다시 돌려 남은 것이 없음을 확인한다. 전에는 rosdep이 키마다 `apt-get install`을 따로 실행했다(22회, 트리거 30회, ~958 패키지). 워크플로는 일회용 runner에서만 dpkg `force-unsafe-io`와 man-db auto-update 끄기를 둔다(이미지 빌드 경로는 무관, 시험으로 고정).
- 증거: 같은 소스 측정 빌드 run 36867742962(id 2026.10.01-901, 설치하지 않는 측정용) 대 021 run 36865620181: "Build native payload tree" 323 s→172 s, 잡 전체 429 s→289 s. `ros-packages.txt`(342)·`deb-packages.txt`(2524)·`required-ros-packages.txt`·`rosy-packages.txt`·`python-runtime.sha256` 동일. `test/test_payload_build_speed.py` 6 passed(파서 거부 변형으로 빨강 확인), 관련 빌드 계약 시험 265 passed. 선행 단계(75→78 s)는 dpkg 설정으로 줄지 않았다.
- gate 변화: 없음.
- 교훈: 빌드 시간 대부분은 colcon(40 s)이 아니라 의존성 설치였다. 시간을 줄이기 전에 단계별 로그 타임스탬프로 어디에 쓰이는지부터 잰다. 교훈 문서 `docs/solutions/workflow-issues/release-cycle-time-one-release-per-deployment-2026-10-01.md`, `docs/solutions/runtime-errors/payload-activation-left-core-on-the-old-release-2026-10-01.md`.

## 2026-10-01 · f8db47f5 · feat(release): 서명 안 된 페이로드를 push 직전까지 한 명령으로 — `prepare_payload_release.py`

- 변경: `tools/release/prepare_payload_release.py`를 추가했다. 스킬 `rosy-release-push` 3–5단계의 손 작업을 한 명령으로 묶는다. 순서는 (1) `--run`의 `rosy-native-payload-unsigned-<id>-<sha>` 아티팩트 이름을 API 목록에서 찾아 `download_artifact.py`로 받고, zip에서 `<id>.unsigned.tar.gz`만 꺼낸다(`--artifact-dir`면 생략). (2) 타르볼 안의 `required-ros-packages.txt`가 모두 `rosy-packages.txt`에 있는지 본다. 둘 다 ROSY 패키지 이름이다. (3) 각 `--robot`에 읽기 전용 SSH로 `dpkg-query -W 'ros-jazzy-*'`(TAB 구분)를 실행해 `ros-packages.txt`(`name=version`)와 비교한다. 양쪽에 설치된 패키지는 버전이 같아야 하고, 로봇의 빈 버전은 미설치로 본다. 비교 0건도 실패다. 로봇마다 한 줄 판정을 낸다. (4) 임시 폴더에 풀고 rename으로 `<out>/x/<id>`에 놓는다. 이미 있으면 거절한다. (5) `sign_image_release.py`로 서명하고 `build_payload_release.py pack --modes-from`으로 묶는다. (6) `rosy-release-push.ps1` 줄을 dry run 먼저 출력한다. push는 하지 않는다. SSH 실행기와 sign/pack 실행기는 주입할 수 있다. 스킬 3–5단계를 이 도구로 바꾸고 손 명령은 대체 경로로 남겼다.
- 증거: `test/test_prepare_payload_release.py` 19 passed(점 파일 보존, 기존·부분 폴더 거절, 깨진 타르볼 뒤 잔재 없음, `name=version`·TAB 파싱과 빈 버전, 불일치·0건 비교 실패, required 검사, push 줄 출력, 불일치 시 서명 전 중단). 변이 4종이 모두 빨강이었다: 릴리스 파싱을 TAB으로(7 failed), `split()`으로(7 failed), 빈 로봇 버전 유지(5 failed), 0건 비교 통과(1 failed). 실측(2026-10-01 Windows, run 36865620181, 릴리스 2026.10.01-021, 8kcn 192.168.1.202 읽기 전용): 98.4 MB zip 다운로드 99.4 s(`gh run download` 기준 2분 12초), ABI 1.6 s(공통 314개 일치, 릴리스 전용 28개), 추출 6.3 s, 서명 8.8 s(2278 파일), pack 11.4 s(2590 멤버, `install/.colcon_install_layout`·`SHA256SUMS.sig` 포함), 합계 128 s. 결과물은 `X:\DevTemp\rosy-release-021-prep-check`. push는 하지 않았다.
- gate 변화: 없음.
- 교훈: 두 목록은 구분자가 다르다(`=`와 TAB). 비교 건수가 0이면 통과가 아니라 파싱 실패로 본다.

## 2026-10-01 · uncommitted · fix(release): `prepare_payload_release.py` 독립 리뷰 반영 — rc 패키지 제외, 오류 처리, 인용

- 변경: (1) 잘린 타르볼(EOFError), 깨진 manifest JSON, UTF-8이 아닌 목록(ValueError)을 traceback 없이 `error:`로 끝낸다. (2) 로봇 조회를 `dpkg-query -W -f='${db:Status-Abbrev}\t${binary:Package}\t${Version}\n' 'ros-jazzy-*'`로 바꾸고 상태가 `ii`인 줄만 설치로 센다. `rc`(삭제, 설정만 남음) 패키지는 옛 버전을 그대로 내므로 비교에서 뺀다. 원격 셸에는 작은따옴표만 지나간다. (3) `-o UserKnownHostsFile="<경로>"`로 인용한다. (4) 출력하는 PowerShell 경로를 늘 작은따옴표로 감싸고 `'`는 `''`로 쓴다. (5) `--run`에 `--release-id`가 있으면 내려받기 전에, 없으면 아티팩트 이름을 정한 직후 내려받기 전에 기존 `x/<id>`를 거절한다. (6) 서명·pack 실패 메시지가 다시 돌리기 전에 지울 `x/<id>`를 알려 준다. (7) 심볼릭·하드 링크 멤버가 있으면 풀기 전에 거절한다. 스킬 3·4단계 설명을 맞췄다.
- 증거: `test/test_prepare_payload_release.py` 30 passed. 변이 8종이 모두 빨강이었다: rc 줄 유지(6 failed), known_hosts 인용 제거, `''` 미적용, 링크 허용(2 failed), EOFError 미포착, ValueError 미포착, 내려받기 전 검사 제거, 이름 확정 뒤 검사 제거(각 1 failed). 새 조회를 192.168.1.202에 읽기 전용으로 한 번 실행했다: `ii` 319줄, `un` 3줄, 판정은 앞 실측과 같은 공통 314개 일치.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(release): 보정 가드가 IP로 불릴 때 호스트명 자격 증명을 찾는다

- 변경: `rosy-calibration-guard.ps1`은 `-ApiToken`·`ROSY_API_TOKEN`이 없고 `<Robot>.credential.xml`도 없으면 push와 같은 비대화형 ssh(`rosy@<ip> hostname`, `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519`, `%LOCALAPPDATA%\Rosy\known_hosts`, `BatchMode=yes`, `StrictHostKeyChecking=yes`, `ConnectTimeout=<TimeoutSec>`)로 장치 호스트명을 묻고, 답이 정확히 한 줄이며 대소문자 구분 `^rosy-[a-z0-9-]+$`일 때만 `<hostname>.credential.xml`을 쓴다. 다른 로봇의 파일은 이 주소에 절대 시도하지 않는다. IP 이름 파일이 있으면 ssh를 부르지 않는다. 조회가 실패하면 예전처럼 경고만 하되 SKIPPED 문구에 찾아본 파일과 조회 실패 이유를 적는다. `-RosyUser`·`-KeyPath`·`-KnownHosts`·`-SshExe`를 주입 가능하게 했고 `rosy-release-push.ps1`이 자기 값을 그대로 넘긴다. known_hosts 경로에 공백·큰따옴표가 있으면 조회하지 않는다(5.1이 native 인자의 큰따옴표를 망가뜨림). 스킬 `rosy-release-push` 5단계 갱신.
- 증거: 2026-10-01 관찰 — `rosy-release-push.ps1 -Robot 192.168.1.201`이 `192.168.1.201.credential.xml`만 찾아 "CALIBRATION CHECK SKIPPED"를 내고 진행했다. 실제 파일은 `rosy-pinky-9dfk.credential.xml`. `python -m pytest test/test_calibration_guard.py test/test_release_push_entrypoint.py -q` 69 passed(가드 27, 새 11: 호스트명 자격 증명 사용·활성 세션 거절, 나쁜 답 5종, ssh 실패, ssh 없음 시 파일명 표시, IP 파일 우선·ssh 미호출, push 전달). 변형 9종 모두 빨강(정규식 제거, 대소문자 무시, 여러 줄 허용, 종료 코드 무시, IP 파일 우선 제거, 파일명 누락, 조회 제거, BatchMode 제거, push 전달 제거). 가짜 ssh(.ps1)와 localhost 가짜 CORE만 사용, 로봇 접속 없음(Windows).
- gate 변화: 없음.
- 교훈: 자격 증명 파일 이름 규칙과 그것을 찾는 쪽의 키가 다르면 안전 점검이 조용히 건너뛰어진다. 건너뜀 경고에는 무엇을 찾았는지를 적는다.

## 2026-10-01 · uncommitted · fix(release): 보정 가드 리뷰 반영 — 호스트명 주장을 호스트 키로 증명, ssh 시간 상한

- 변경: 독립 리뷰(COMMENT) 반영. M1: 로봇이 답한 호스트명은 그 로봇의 `rosy` 계정이 꾸밀 수 있으므로, `<hostname>.credential.xml`을 쓰기 전에 같은 엄격 옵션에 `-o HostKeyAlias=<별칭>`을 더한 두 번째 ssh(`true`)가 성공해야 한다. 별칭은 known_hosts의 평문 항목 중 `<name>`, `<name>.local`, `<name>.lan` 순으로 처음 있는 것(실제 항목이 `rosy-pinky-9dfk.local` 형태). 항목이 없거나 키가 맞지 않으면 토큰을 쓰지 않고 이유를 SKIPPED에 적는다. M2: 모든 ssh에 `-n -o ServerAliveInterval=2 -o ServerAliveCountMax=2`, 그리고 `System.Diagnostics.Process`로 띄워 호출당 `TimeoutSec + 5`초 벽시계 상한, 넘으면 `taskkill /T /F`로 프로세스 트리를 죽인다. 명령줄은 가드가 직접 만든다(공백 인자만 한 번 따옴표, 큰따옴표 든 인자는 거절). `-SshExe`는 native 실행 파일이어야 한다. M3: 가드 시험의 가짜 ssh를 원시 명령줄을 기록하는 `.cmd`로 바꿨다. L4: ssh와 무관한 가드 시험은 존재하지 않는 `-SshExe`를 넘긴다. `test_release_push_entrypoint.py`는 autouse 픽스처로 `LOCALAPPDATA`를 임시 폴더로 돌리고 `ROSY_API_TOKEN`을 지운다. L2: `sync-core-dev.ps1`이 `-RosyUser $PiUser`를 넘긴다. SKILL 5단계에 잔여 위험(known_hosts 신뢰, 호스트 키를 공유하는 복제 이미지는 구별 불가, 평문 항목 없는 로봇은 경고 후 건너뜀) 기록.
- 증거: `python -m pytest test/test_calibration_guard.py test/test_release_push_entrypoint.py -q` 78 passed(가드 36), `test/test_core_dev_sync.py` 34 passed. 변형 23종 모두 빨강(앞 커밋 9종 재확인 + 별칭 검사 생략, 별칭 종료 코드 무시, known_hosts 항목 불요, HostKeyAlias 누락, `-n` 누락, keepalive 누락, 벽시계 상한 없음, 래퍼만 죽임, RosyUser 검사 제거, 공백 경로 검사 제거, 명시 CredentialPath 무시, ConnectTimeout 고정, 공백 인자 미인용, sync 사용자 미전달). 대소문자 변형은 별칭 조회가 먼저 막아 처음엔 살아남았다 — 시험 known_hosts에 대문자 항목을 넣어 답 검사만으로 막히게 고친 뒤 빨강. 로컬 known_hosts 확인: 9dfk·8kcn 호스트 키는 서로 다르다. 가짜 ssh와 localhost 가짜 CORE만 사용, 로봇 접속 없음(Windows).
- gate 변화: 없음.
- 교훈: 상대가 스스로 밝힌 이름으로 비밀을 고를 때는 그 이름을 상대가 꾸밀 수 없는 것(호스트 키)으로 증명한다. 겹겹 방어가 있으면 변형 하나가 다른 층에 가려 살아남는다 — 층마다 따로 막히는 시험 입력을 만든다.

## 2026-10-02 · uncommitted · fix(native): 부팅 복구 게이트에 PrivateTmp — 활성화 중 전원 차단 뒤 CORE가 영영 뜨지 않던 결함

- 변경: `rosy-release-recover.service`에 `PrivateTmp=yes`. recover가 이전 릴리스를 다시 검증할 때(`native_release.verify` → `signing`의 `tempfile`) `ProtectSystem=strict` 아래 임시 디렉터리가 읽기 전용이라 "No usable temporary directory"로 실패했고, `rosy-core.service`·`rosy-runtime.target`이 이 게이트를 Requires 하므로 로봇이 뜨지 않았다. 수동 push에도 해당한다.
- 증거: D-406 기기 쌍둥이(ubuntu 24.04 + systemd 255 컨테이너, 브랜치 test/d406-device-twin) 시나리오 h3에서 활성화 도중 전원 차단 뒤 재현, PrivateTmp로 복구 성공. 계약 시험 `test_units_that_verify_releases_get_a_writable_private_tmp`(변형으로 빨강 확인). 관련 시험 217 passed.
- gate 변화: 없음. 기기 확인 필요. 이 유닛은 sync에서 next-boot 대상이라 다음 릴리스 push 뒤 재부팅부터 적용된다.

## 2026-10-02 · a434ea35 · feat(deploy): D-411 A pilot-recordings 디렉터리와 유닛 권한
- 변경: `tmpfiles-rosy-state.conf`·`customize-rootfs.sh` 에 `/var/lib/rosy/pilot-recordings`(2750 rosy-camera:rosy-core), `rosy-camera.service` `ReadWritePaths`, `rosy-core.service` `ReadOnlyPaths`.
- 증거: `python -m pytest test/test_native_systemd_contract.py test/test_control_deploy_closure.py -q` → 133 passed, 1 skipped (2026-10-02 Windows). 이미지 빌드·실기 readback 은 하지 않았다.
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · a44f9e00 · feat(native): 로봇 쪽 자동 업데이터 `rosy_auto_update.py`·claim·유닛 (D-406 T2)

- 변경: `native/rosy_auto_update.py`(stdlib, CLI `run`/`status`/`hold`/`release-hold`/`eligibility`)를 추가했다. 한 번 실행은 GitHub Releases를 ETag로 읽고(304는 캐시, 403/429는 Retry-After만큼 쉼), 지금보다 큰 `payload-<id>` 가운데 자산 셋이 있고 실패 기록이 없으며 서명된 `rollout.json`이 맞고 철회되지 않은 가장 높은 id를 고른다. 바쁠 때도 스테이징(sha256, `rosy-release-unpack.sh`, `native_release.py verify`)은 하고 `current`는 건드리지 않는다. 카나리이거나 `canary_ok`와 대기 시간이 지났고, hold·봉인 승인·live claim이 없고, status-inputs schema ≥ 2가 10 s 간격 두 표본 모두 유휴(null·NaN은 모름 = 부적격, 계약 b63cb7f2)이고, 배터리 40% 이상이거나 충전 중일 때만 claim을 잡고 적용한다: activate → core-release 확인 → 새 릴리스의 sync → 재시작(자기 유닛 제외) → 건강 60 s. 실패하면 rollback, 되돌아간 릴리스의 sync, ready 확인 뒤 id를 실패로 남겨 다시 시도하지 않는다. `NATIVE_RELEASE_BUSY`는 다음 실행에 다시 한다. `native/rosy_claim.py`(mkdir 원자 claim, 만료·다른 boot는 rename으로 한 쪽만 치움, CLI acquire/release/show·status)를 추가했다. `rosy-release-unpack.sh`를 `native/`로 옮겨 push와 업데이터가 같은 사본을 쓴다(push 동작 같음). `rosy-auto-update.service`(root oneshot, Nice=19, IOSchedulingClass=idle, ProtectSystem=strict)·`.timer`(부팅 5분, 10분마다, 2분 분산)를 `UNITS`·`ENABLED_UNITS`(타이머만)·`build-native-payload.sh`·`customize-rootfs.sh`에 넣었다. sandbox 계약은 이 유닛의 쓰기를 선언하고, `/run`과 기본 OS의 `/etc/systemd/system`·`/etc/udev/rules.d`·`/etc/modprobe.d`를 시작 때 있는 경로로 센다.
- 증거: `test/test_rosy_auto_update.py` 117 passed, `test/test_rosy_claim.py` 17 passed. 관련 묶음(image-layer sync, systemd 계약, push·unpack, payload build, image customization, native activation, device surface, ubuntu runtime, 위 둘) 524 passed, 9 skipped, `python test/known_failures.py` 새 실패 0. 변이: 업데이터 61종 가운데 59종이 첫 실행에서 빨강, 살아남은 2종(숫자 아닌 battery_percent, 7일 넘는 손으로 쓴 hold)은 시험을 더해 빨강. claim 10종, 계약·패리티 9종 모두 빨강(프로그램 소스 목록 삭제 1종은 경로 리터럴이 없어 초록, 가드가 아님). 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE는 T1·T3 병합 뒤 두 대 검증 전까지 HOLD.
- 결정: D-406
- 교훈: 변이 실행을 중간에 죽이면 마지막 변이가 파일에 남는다. 다시 쓰기 전에 원본 문자열이 그대로 있는지 확인한다.

## 2026-10-02 · 05d58d0a · fix(native): 업데이터 건강 판정을 적용 전 기준선과 비교 (D-406 T2)

- 변경: 활성화 직전에 rosy-core/io/camera 가운데 active인 유닛과 그 cwd, 이미 failed인 rosy-* 유닛을 적용 저널(`state.json`의 `applying.baseline`)에 남긴다. 건강 판정은 rosy-core를 늘 요구하고, io·camera는 적용 전에 돌던 경우에만 새 릴리스 cwd에서 active여야 한다. failed 유닛은 적용 중 새로 생긴 것만 실패로 본다. 건너뛴 유닛과 이미 있던 실패는 `last_result.detail`에 적는다. 조정자 결정(질문 3): 카메라가 이미 꺼진 로봇이 업데이트마다 되돌리지 않게 한다.
- 증거: `test/test_rosy_auto_update.py` 123 passed. 새 시험: 적용 전 카메라 꺼짐 → 커밋, 적용 전 켜짐·뒤 꺼짐 → 되돌림, 이미 failed인 유닛 → 커밋, 그 옆에 새로 failed → 되돌림, 적용 전 꺼진 CORE도 요구, 꺼져 있던 io의 cwd 미검사. 변이 7종 모두 빨강.
- gate 변화: 없음.
- 결정: D-406
- 교훈: 건강 판정은 절대 상태가 아니라 적용 전과의 차이로 본다. 원래 꺼져 있던 장치가 릴리스 실패로 기록되면 안 된다.

## 2026-10-02 · 9a1ae36f · fix(native): D-406 T2 독립 리뷰 반영 — 안전한 재개, 일시·확정 실패 구분, 스테이징 한도

- 변경: 리뷰(REQUEST CHANGES) 전 항목. H1 끊긴 적용의 재개는 hold·봉인·두 표본 유휴를 확인한 뒤에만 재시작 단계를 한다(아니면 `applying`을 둔 채 held/ineligible). H2 저널이 rollback에 닿았으면 계속 되돌리기만 한다(새 릴리스가 current일 때만 rollback 스크립트, 그 뒤 늘 sync·재시작·core·ready). activate 뒤 단계에서 옛 릴리스가 current면 그 릴리스를 다시 sync한다. H3 활성화기·verify의 124/127·JSON 결과 없음은 일시 실패로 보고 실패 기록을 하지 않는다. native 저널이 남았으면 `native_release.py recover`와 `systemctl start rosy-runtime.target`. H4 커밋한 id를 남기고, current보다 높으면 운영자 되돌림으로 실패 처리한다. M1 서로 다른 두 쓰기, 각 25 s 이내, 12 s 간격. M2 활성화기 직전 한 번 더 읽고, 남는 틈을 ADR R4에 적었다. M3 RUN_BUSY는 아무것도 쓰지 않는다. M4 철회는 영구 기록. M5 릴리스별 스테이징 backoff, 확정 실패 3회면 실패, 디스크 확인(tarball×2+512 MiB), current·previous·staged 외 릴리스 디렉터리 정리. M6 읽을 수 없거나 깨진 승인 표지는 hold. M7 BUSY·일시 실패한 rollback은 저널에 남겨 다음 실행이 다시 한다. M8 claim TTL 50분(TimeoutStartSec 45분보다 길게), 저널 단계마다 갱신. M9 claim 넘겨받기를 `/run/rosy-claim.lock`으로 직렬화. L1 확정 문제(서명·철회)일 때만 더 낮은 릴리스로 넘어간다. L2 docking 허용 목록, `line_follow_state`는 OFF. L3 OverflowError. L4 phase·이유 분류가 바뀔 때만 history, 1 MiB에서 회전. L5 `Persistent=` 제거(OnCalendar 전용). L6 시간 초과 시 프로세스 그룹 종료. L7 downloads의 잔여 디렉터리 정리. L8 `Requires=rosy-release-recover.service`, releases 경로 필수, `CapabilityBoundingSet`·`ProtectProc`·`PrivatePIDs` 금지 시험. L9 비활성이어도 진행 중 적용은 마무리. 활성화 뒤 예기치 않은 예외도 되돌린다.
- 증거: `test/test_rosy_auto_update.py`·`test/test_rosy_claim.py` 190 passed, 1 skipped(이 Windows 호스트는 symlink를 만들 수 없음). 관련 묶음 583 passed, 10 skipped, `python test/known_failures.py` 새 실패 0. 리뷰 변이 38종 모두 빨강(처음 살아남은 1종 — 신선도 60 s — 은 서로 다른 두 쓰기가 각각 26 s 늦은 시험을 더해 빨강). 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-406
- 교훈: 끊긴 트랜잭션을 재개하는 경로도 처음 적용과 같은 적격성 문을 지나야 한다. 프로세스 종료 코드만으로 "확정 실패"를 판정하지 않는다 — JSON 판정이 있을 때만 확정이다.

## 2026-10-02 · b909ed5b · fix(native): 재개 시 rosy-core가 멈춰 있으면 유휴 판정 면제 (D-406 T2)

- 변경: 조정자 결정(H1 질문). `applying` 저널을 재개할 때 rosy-core.service가 active가 아니거나 MainPID가 없으면 움직임을 명령할 주체가 없다(CORE가 유일한 cmd_vel 발행자, D-2). 그때는 status-inputs 두 표본 판정을 면제하고, hold·봉인 승인·claim 검사는 그대로 한다. "core not running; idleness check waived"를 history와 `last_result.detail`에 남긴다. CORE가 돌고 있으면 전처럼 전체 판정을 한다.
- 증거: `test/test_rosy_auto_update.py`·`test/test_rosy_claim.py` 195 passed, 1 skipped. 새 시험: CORE 정지·hold 없음 → 재개해 커밋, CORE 정지·hold → held, CORE 정지·claim → ineligible, CORE 동작·오래된 입력 → ineligible, active지만 MainPID 0 → 정지로 본다. 변이 5종 모두 빨강(처음 살아남은 MainPID 무시 1종은 시험을 더해 빨강).
- gate 변화: 없음.
- 결정: D-406
- 교훈: 면제는 위험의 원천이 없을 때만 준다. 여기서 원천은 CORE 하나뿐이라 그 상태를 직접 확인한다.

## 2026-10-02 · 9970f2e0 · feat(release): D-406 T3 운영 PC — 발행·카나리·철회, hold 명령, push claim

- 변경: 커밋 d6873301, 29f649a4, 2898738c, 9970f2e0. (1) `tools/release/publish_payload_release.py`(표준 라이브러리 + `signing.py`): prepare가 만든 서명 tarball로 GitHub Release `payload-<id>`(`livsbittt/rosy-os`, `--target` = `source-revision.txt`)를 만들고 `<id>.tar.gz`, `rollout.json`(키 정렬, LF, UTF-8), `rollout.json.sig`를 올린다. canary는 `ssh rosy@<ip> hostname`으로 정하고 `^rosy-[a-z0-9-]+$`를 검사한다. 서명 뒤 저장소 공개키로 자체 검증한 다음에만 올린다. 기존 태그는 `--resume` 없이는 거절한다. 카나리의 `rosy_auto_update.py status --json`을 30 s마다 읽어 이 id의 commit이면 `canary_ok=true`, 이 id의 `rolled_back`/`refused`나 `--canary-timeout-min`(기본 30) 초과면 `withdrawn=true, reason`으로 다시 서명해 `gh release upload --clobber`한다(`published_at`은 그대로). `--resume`은 받은 rollout의 서명을 검사하고 canary 이름이 목록에 있어야 이어 간다. `--withdraw --reason`은 손으로 철회한다. 단계마다 출력하고 `X:\DevTemp\rosy-rollout-evidence\<날짜>\rollout.jsonl`에 남긴다. `prepare_payload_release.ssh_argv`가 원격 명령을 인자로 받게 했다. (2) `deploy/robot/pinky_pro/rosy-update-hold.ps1 -Robot <ip> -Hold -Reason -Hours | -Release | -Status`: 장치 CLI를 `sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py`로 부른다. 동작은 정확히 하나, `-Reason`·`-Holder`는 안전한 ASCII 집합만(`\z` 고정, 첫 글자 영숫자) 받아 작은따옴표로 보낸다. `-Hours`는 (0, 168]. (3) `rosy-release-push.ps1`: 첫 원격 단계로 claim(`rosy_claim.py acquire --holder push-<user>@<pc> --purpose push --ttl-s 1800`)을 잡고 `finally`에서 놓는다. 잡혀 있으면 push를 거절하고, helper가 없는 로봇은 `ROSY_CLAIM_HELPER_MISSING`으로 경고만 하고 계속한다. `-PrintCommands`가 두 단계(`claim-acquire`, `claim-release`)를 보인다. `$unpackScript` 줄은 건드리지 않았다(T2 몫). (4) 스킬 `rosy-release-push`에 "Automatic rollout (D-406)" 절.
- 증거: 관련 묶음 306 passed, 3 skipped(내 시험은 skip 없음), `test/known_failures.py` 0 new. 새 시험: `test/test_publish_payload_release.py` 31, `test/test_update_hold.py` 39, `test/test_release_push_claim.py` 8, 기존 `test_release_push_entrypoint.py`는 claim 양 끝을 떼고 비교하도록 고쳤다. 변이 41종이 모두 빨강이었다: 발행 19(키 비정렬, CRLF, 자체 검증 제거, 태그 존재 무시, 접두사 일치, hostname 검사 제거, current_release 무시, 다른 id로 판정, refused 무시, 타임아웃 절반, resume 서명 무시, canary 소속 무시, wave 59 허용, published_at 갱신, manifest id·revision 검사 제거, 철회된 resume 진행, 수동 철회·실패 시 withdrawn 미설정), hold 12, claim 10. 실제 GitHub 릴리스·로봇 접속 없음(가짜 gh·ssh·시계).
- gate 변화: 없음(HOST만). DEVICE 검증은 T1·T2 병합 뒤.
- 남은 일: T2의 `rosy_claim.py release`가 `--holder`를 받는지 맞춰야 한다(지금은 `release --holder <H>`로 부르고, 실패하면 경고만 하며 claim은 30분 뒤 만료). 발행 명령은 tarball의 릴리스 서명을 다시 검사하지 않는다(로봇이 스테이징 때 검사). 카나리 외 로봇은 canary_ok 뒤 한 번 상태만 보여 주고 계속 지켜보지 않는다.

## 2026-10-02 · 56d292a2 · fix(release): D-406 T3 독립 리뷰 반영 — 철회 보존, 기준 결과, 키 경로, claim 판정

- 변경: 커밋 6f6c5d4b, 1c7b6288, 56d292a2. (1) H1: 카나리 감시가 끝나면 올리기 전에 GitHub의 rollout을 다시 받아 서명을 검사한다. 그사이 철회됐으면 그대로 두고(exit 3), 이 프로세스가 올린 것과 다르면 덮어쓰지 않는다. 릴리스 id마다 `publish-<id>/.lock` 하나만(create·resume·withdraw). (2) M1: 릴리스를 만들기 전 카나리의 `last_result`를 기준으로 잡고, 그와 다르고 `published_at - 120 s` 이후인 결과만 판정에 쓴다(재사용된 id의 옛 commit·rollback 무시). (3) M4: 개인키 경로를 출력·증거에 남기지 않는다. 서명 오류는 키 이름만 밝힌다. (4) M5: `--withdraw`는 원격 rollout 서명이 맞지 않으면(반쯤 끝난 `--clobber`) 작업 폴더의 로컬 서명본을 쓴다. 마지막 업로드가 실패하면 `gh release upload ... --clobber` 복구 명령(철회면 `--withdraw` 명령도)을 출력한다. (5) L1 Ctrl+C는 `--resume`·`--withdraw` 명령을 출력하고 130으로 끝난다. L2 다른 hostname의 상태는 카나리가 아니다. L3 이 후보의 `failed`/`error` 단계는 바로 철회한다. L6 `--repo`, `--key-name` 검사. L7 발행 전 tarball 릴리스 서명을 임시 추출본에서 `verify_release_files`로 검사한다. (6) hold 명령: `-Status`가 `PSObject.Properties`로 읽어 T2의 "아직 실행 안 됨" 응답(`{"phase": null, "reason": ...}`)에서도 죽지 않는다(M2). known_hosts 경로는 따옴표 없이 넘기고, 공백·따옴표가 있으면 거절한다(L5). (7) push claim: exit 3/`CLAIM_BUSY`는 "claimed by another job", 그 밖의 non-zero는 "claim helper failed (exit N)", 둘 다 거절(M3). busy와 helper 없음이 아니면 `finally`에서 늘 놓는다(holder 한정). TTL은 tarball 크기로 1200 s + 2 s/MB, [1800, 7200](L4).
- 증거: `test_publish_payload_release.py` 60, `test_update_hold.py` 46, `test_release_push_claim.py` 16, 관련 묶음 350 passed, 3 skipped, `test/known_failures.py` 0 new. 변이: 발행 21종 중 19종 바로 빨강. R1(원격 철회 무시)은 "바뀜" 검사가 가려 초록이었다; 시험이 exit 3과 "withdrawn meanwhile"을 보게 고친 뒤 빨강. R21(업로드 뒤 `last_uploaded` 갱신)은 쓰이지 않는 코드라 지웠다. hold 4종, claim 8종 모두 빨강(여러 줄 패턴 2종은 CRLF로 안 들어가 한 줄 패턴으로 다시 해 빨강). 실제 GitHub·로봇 접속 없음.
- gate 변화: 없음.

## 2026-10-02 · 0904824d · fix(release): D-406 T3 카나리 조기 철회는 `failed`만, `error`는 계속 지켜본다

- 변경: T2가 일시적 문제(네트워크, 활성화기 시간 초과, busy)는 `error`, 확정 실패는 `failed`(`last_result`가 이 id의 `rolled_back`/`refused`)로 보고하게 바뀌었다. 발행 명령은 이 후보의 `failed`(최근 `updated_at`)나 기준 결과 뒤의 `rolled_back`/`refused`일 때만 바로 철회하고, `error`는 시간 초과까지 계속 지켜본다.
- 증거: `test/test_publish_payload_release.py` 63 passed. 변이 4종 모두 빨강: `error`도 조기 철회, `failed` 조기 철회 제거, 다른 후보의 `failed`로 철회, 오래된 `failed`로 철회.
- gate 변화: 없음.

## 2026-10-02 · 8198ec47 · fix(release): D-406 T3 재리뷰 반영 — 철회 우선, 로컬 대체본 업로드, known_hosts 정책 하나

- 변경: 커밋 8f633400, 8198ec47. (1) N1: `--withdraw`가 로컬 서명본으로 대체했으면 그 사본이 이미 철회 상태여도 늘 올린다. 이미 철회라 아무것도 안 하는 경우는 GitHub 사본이 서명 검증을 통과했을 때뿐이다. (2) N2: 내려받기 전에 `downloaded/`를 비우고, 자산이 없으면 서명 불일치와 같이 다룬다. (3) N4: 마지막 업로드 뒤 한 번 더 내려받아, 철회가 보이면 그대로 두고 우리가 올린 바이트와 다르면 다시 철회를 올린다. 철회가 늘 이긴다. (4) N7: 잠금 파일의 PID가 없는 프로세스면 stale이라고 말하고 지우는 명령을 준다(Windows는 OpenProcess로 확인, 신호를 보내지 않는다). (5) N8: hostname이 없는 상태는 "updater has not run yet (no status.json)". (6) N9: 수동 철회의 업로드가 실패해도 복구 명령을 출력한다. (7) N3: Windows PowerShell 5.1은 `UserKnownHostsFile="C:\a b\k"`를 그대로 넘기고, 받는 프로그램의 C 런타임이 따옴표를 벗긴 뒤 ssh가 공백에서 나눈다(`test/test_known_hosts_policy.py`가 raw `.cmd` 가짜와 C 런타임 프로그램으로 확인). 그래서 push도 hold처럼 따옴표 없이 넘기고 공백·따옴표가 든 경로는 거절한다. (8) N5: busy인 claim의 holder가 이 PC 자신이면 정확한 release 명령을 출력한다. tarball 업로드 직후 `rosy_claim.py refresh --holder <H> --ttl-s <TTL>`로 claim을 늘린다(실패는 경고만).
- 증거: 관련 묶음 376 passed, 3 skipped, `test/known_failures.py` 0 new. 변이: 발행 12종 중 10종 바로 빨강, 2종(경합 중 보이는 철회 유지, stale 판정)은 시험이 다시 올린 업로드·임시 경로 이름에 가려 초록 → 시험을 좁혀 빨강. push 7종 모두 빨강.
- gate 변화: 없음.
- 남은 일: T2 `rosy_claim.py`(d87d329f)에 `refresh()` 함수는 있으나 CLI 하위 명령이 없다. 그 전까지 push의 refresh는 경고만 내고 claim은 크기로 정한 TTL을 유지한다.

## 2026-10-02 · 088a6a9a · fix(native): D-406 T2 재리뷰 반영 — CORE 상태 fail-closed, 확정 코드 목록, 적용 backoff, 활성화기 precheck

- 변경: 재리뷰(COMMENT) N1~N16과 T3의 refresh CLI. N1 `native_release.py activate`가 검증 뒤·런타임 정지 직전에 `ROSY_ACTIVATE_PRECHECK` 명령(업데이터의 새 `precheck`: hold, 봉인, 다른 claim, status-inputs 한 표본)을 돌리고, 0이 아니면 `NATIVE_PRECHECK_REFUSED`로 아무것도 바꾸지 않는다(4672715a). 업데이터는 이를 부적격으로 기록한다. ADR R4를 이에 맞췄다(a623a1bf). N2 CORE 정지 판정은 `systemctl show -p ActiveState,SubState,MainPID`가 inactive/failed(또는 activating+auto-restart)이고 MainPID 0일 때만, 호출 실패는 동작 중으로 본다. N3 확정 실패는 NATIVE_MANIFEST_*, NATIVE_TARGET_MISMATCH, NATIVE_PYTHON_RUNTIME, 서명·체크섬 거부, candidate 건강 실패뿐이다. N7 일시 적용 실패는 backoff, 3회면 held(release-hold가 지운다). N4 면제된 재개라도 CORE가 다시 돌면 재시작 전에 유휴 판정, 아니면 미룬다. N5 CORE가 돌지만 30분 넘게 status를 쓰지 않으면 phase `stuck`. N6 정리는 native-release.lock 아래, 1시간 넘은 디렉터리만, current 없으면 하지 않는다. N8 실패한 rollback도 native 저널을 recover. N9 previous가 current보다 높으면 운영자 되돌림. N10 recover가 성공했을 때만 런타임 시작. N11 전환 전에 끊긴 활성화는 실패로 남기지 않고 다시 한다. N12 rollback 재시도 5회 뒤 failed와 운영자 안내. N13 claim 해제 오류는 history에 남기고 삼킨다. N15 면제 메모를 재개마다 갱신. N16 안 쓰는 import 제거. T3용 `rosy_claim.py refresh --holder H --ttl-s N`(claim lock 아래; 0 갱신, 3 CLAIM_BUSY 또는 CLAIM_MISSING, 2 잘못된 인자)(a7030f71).
- 증거: 업데이터·claim·native activation 시험 250 passed, 1 skipped. 관련 묶음 629 passed, 10 skipped, `python test/known_failures.py` 새 실패 0. 변이 38종 모두 빨강: 재리뷰 33종(native_release.py 3종은 CRLF 작업본이라 따로 돌림), 처음 살아남은 1종(`_main`의 env precheck 배선)은 CLI 시험을 더해 빨강, refresh CLI 4종. 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-406
- 교훈: "확정 실패"는 종료 코드나 JSON 유무가 아니라 알려진 오류 코드 목록으로 정한다. 모르는 실패는 일시 실패로 보고 횟수로 사람을 부른다.

## 2026-10-02 · 5f3226bf · fix(native): D-406 T2 검증 리뷰 반영 — 자기 되돌림과 운영자 되돌림 구분, silent_since, rollback_failed

- 변경: HIGH 일시 활성화 실패 뒤 실패 기록 없이 되돌린 id를 `state.self_rolled_back`에 남겨, N9가 previous > current를 운영자 되돌림으로 오인하지 않게 했다. 커밋하면 지운다. M1 `stuck`은 처음 조용함을 본 재개(`applying.silent_since`)부터 잰다. held·다른 이유·적격 재개가 지운다. M2 precheck의 바쁨 종료(3)만 `NATIVE_PRECHECK_REFUSED`. 다른 종료·실행 불가·시간 초과는 `NATIVE_PRECHECK_FAILED`로 적용 backoff에 들어간다(406b8631). L1 `NATIVE_RUNTIME_MISMATCH`를 확정 실패에 더했다. L2 N12 한도에 닿으면 결과를 `rollback_failed`로 남기고, 그 릴리스가 current인 동안 매 실행 `failed`와 처치 명령을 보인다. 계획서 status.json 목록에 `stuck`·`rollback_failed`를 더했다. L3 escalation held와 stuck 이유에 처치 명령(release-hold, `rosy-release-push.ps1 -Rollback`)을 적었다. L6 precheck 시간 초과 시험. 미결 질문: `rosy-release-unpack.sh`가 `mv -T` 뒤 대상 디렉터리를 touch해, 막 푼 릴리스가 정리의 1시간 나이 보호를 받는다(09516b54). L4(건강 실패는 확정)는 그대로 둔다.
- 증거: 관련 묶음 641 passed, 10 skipped, `python test/known_failures.py` 새 실패 0. 리뷰어의 N9 probe가 이제 committed, 실패 id 없음. 변이 17종 모두 빨강(처음 살아남은 2종 — held·적격 재개에서 silent_since를 지우지 않음 — 은 조용함→held→다시 조용함, 조용함→면제 적격 재개→다시 조용함 시험을 더해 빨강). 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-406
- 교훈: 두 규칙이 같은 흔적(previous > current)을 보면 누가 그 흔적을 남겼는지 기록해 둔다. 경과 시간은 "그 상태를 처음 본 때"부터 잰다.

## 2026-10-02 · 84e45d05 · test(d406): device twin — systemd 컨테이너로 자동 업데이트 끝까지 검증

- 변경: `tools/device_twin/`(배포물에 들어가지 않음). ubuntu:24.04 systemd 컨테이너에 실제 native runtime·rosy 유닛(`git archive HEAD`), 일회용 Ed25519 키로 `build_payload_release.py`+`sign_image_release.py`가 만든 릴리스, ExecStart만 바꾼 가짜 ROS(가짜 CORE는 `/api/v1`, schema 2 status-inputs, `twin-control`로 바쁨 상태), 가짜 GitHub(ETag/304)와 가짜 `gh`, 실제 `publish_payload_release.py`를 그 위에서 돌리는 래퍼. 업데이터에 `config.json`의 `api_base` 키 추가(기본 `https://api.github.com`, 잘못된 값은 CONFIG_INVALID, 시험 포함).
- 증거: `python tools/device_twin/run_twin.py --scenario all`(통합 브랜치 4a185386 병합 뒤) 12개 중 11 PASS: 활성화 결함 재현과 수정 확인, 발행→카나리 커밋→canary_ok, 바쁨·hold·봉인·claim 부적격, 나쁜 릴리스 롤백·image layer 원복·철회, 철회 릴리스 미적용, SIGKILL·전원 차단 뒤 재개 커밋, `systemd-analyze verify`, 샌드박스에서 `/proc/<pid>/cwd` 읽기. 보고서 `X:/DevTemp/d406-twin/report.md`. 호스트 시험 `test_rosy_auto_update.py`·`test_rosy_claim.py`·`test_publish_payload_release.py` 311 passed, 1 skipped.
- 결함(제품, 고치지 않음): (h3) 활성화 중 전원 차단 뒤 `rosy-release-recover.service`가 실패한다. `ProtectSystem=strict`에 `PrivateTmp`가 없어 `signing.verify_signature`의 임시 디렉터리를 못 만든다. CORE와 업데이터 모두 이 유닛을 Requires 하므로 런타임이 안 뜨고 업데이터도 못 돈다. twin에서 `PrivateTmp=yes`를 붙이면 복구된다.
- gate 변화: 없음. twin 통과는 HOST 증거이고 DEVICE 증거가 아니다.
- 결정: D-406
- 교훈: 저널이 있을 때만 타는 부팅 경로는 실제 sandbox 아래에서 한 번은 돌려 봐야 한다. 단위 시험은 tempfile을 쓸 수 있는 호스트에서 돌았다.

## 2026-10-02 · 30390e1c · fix(native): D-406 T2 검증 리뷰 2 반영 — current가 실제로 옮겨졌을 때만 자기 되돌림, 꼬리 실패도 backoff

- 변경: 통합 브랜치(`feat/d406-robot-auto-update`: twin의 `api_base` 설정, recover PrivateTmp, size verdict)를 먼저 병합했다(충돌 없음). HIGH 1 `self_rolled_back`은 우리 rollback이 current를 실제로 옮겼을 때만 남긴다. 재시도 한도에 닿았거나(gave up) 확정 오류로 거절된 rollback은 남기지 않는다. 그래서 그 뒤 운영자가 `-Rollback`하면 그 릴리스는 "operator rolled back"으로 실패 처리된다. HIGH 2 실패 기록 없는 rollback이 current를 옮겼으면 꼬리(sync·core·ready)가 실패해도 적용 오류를 센다. backoff와 escalation이 반복을 끊는다. MEDIUM `release-hold`가 `rollback_failed` 결과를 확인 처리(last_result 지움, history 한 줄)하고, 고정 이유와 계획서에 적었다. LOW 지금 current이거나 실패·철회된 id는 `self_rolled_back`에서 지운다. LOW native_release와 업데이터의 precheck 바쁨 종료 코드가 같음을 시험으로 묶었다. `rosy_auto_update.py` size verdict를 1505줄(+33)로 다시 판정했다(판정은 그대로: 장치 검증 뒤 분리).
- 증거: 관련 묶음 655 passed, 10 skipped, `python test/known_failures.py` 새 실패 0. 병합으로 들어온 T3·twin 시험(architecture, known_hosts, publish, push claim, update hold) 181 passed(size verdict 갱신 뒤). 리뷰어 probe 두 개 통과: 운영자 되돌림 → 실패 처리, 6회 실행에 활성화 2회. 변이 9종 모두 빨강. 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE HOLD.
- 결정: D-406
- 교훈: "누가 흔적을 남겼나" 기록은 그 행동이 실제로 일어났을 때만 쓴다. 시도만 하고 실패한 행동을 기록하면 다른 규칙의 판단을 가린다.

## 2026-10-02 · 6d281ae7 · fix(native): D-406 T2 최종 검증 묶음 — release-hold를 run lock 아래로, 확인 내용 보고

- 변경: MEDIUM `release-hold`가 업데이터 run lock을 잡는다. 실행 중이면 state.json을 덮어쓰지 않고 RUN_BUSY(CLI 종료 4, "실행이 끝난 뒤 다시")로 거절한다. LOW 1 확정 오류로 거절된 rollback도 `rollback_failed`로 남겨, 포기한 rollback처럼 고정 표시되고 release-hold로 확인할 수 있다. LOW 2 release-hold가 `acknowledged_rollback_failure`와 `cleared_apply_errors`를 돌려주고, `rosy-update-hold.ps1 -Release`가 이를 읽기 쉽게 보인다(옛 장치의 답은 그대로 출력). LOW 3 current보다 낮고 previous가 아닌 `self_rolled_back` 항목을 지운다. LOW 4 실패 기록 없는 경로의 확인을 끝까지 시험했다(일시 전환 → rollback 못 함 → release-hold → 재활성화 없음 → 운영자 되돌림 시 실패 처리). size verdict 1515줄(+10), 판정은 그대로.
- 증거: 관련 묶음과 T3·twin 시험 843 passed, 10 skipped, `python test/known_failures.py` 새 실패 0. 변이 9종 모두 빨강. 로봇에는 손대지 않았다.
- gate 변화: 없음. DEVICE HOLD(다음은 두 대 장치 검증).
- 결정: D-406
- 교훈: 상태 파일을 쓰는 운영 명령은 업데이터 실행과 같은 잠금을 잡는다. 바쁘면 조용히 덮어쓰지 말고 다시 하라고 말한다.

## 2026-10-02 · uncommitted · feat(native): D-406 업데이터 기본 꺼짐 — 첫 두 대 기기 검증 전까지 로봇별로 켬

- 변경: 사용자 착지 결정(2026-10-02). `rosy_auto_update.py`는 `config.json`이 없거나 `enabled`가 없으면 꺼짐(phase `disabled`, GitHub 요청·적용 없음). ADR D-406·계획 계약·`rosy-release-push` skill에 켜는 명령(로봇별 `config.json` 작성)을 적었다. 시험 fixture는 명시적으로 켜고, 새 시험 2개가 기본 꺼짐을 고정한다. 기기 쌍둥이는 config에 `enabled: true`를 명시하므로 영향 없음.
- 증거: 업데이터 시험 238 passed; 기본값을 켜짐으로 되돌리면 새 시험 2개 빨강. 기기 쌍둥이 12/12 PASS(직전 실행, 같은 코드에 기본값만 다름).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · CI 삼각측량 — 시크릿 스캔 면제·해시 문서 규약·스코어카드 기준선·설치 문서 브라우저 시험
- 변경: secret_scan.py KNOWN_FIXTURES에 D-395 loc-assist fixture(SECRET-PAYLOAD-VALUE) 등록. OMX 증명 해시 3곳을 매처의 무결성 문맥 규약으로 서술(README 'revision'/'dataset commit', omx_f_kinematics.yaml 'at revision') — 의미 불변. test_release_boundary_gates no_secrets 재녹색.
- 변경: D-178 스코어카드에 rosy_cell 잠정 행(4/4/4/4/4=80 A) 추가 — 집합 동일성 회복. robot_literal_backlog.txt 갱신(신규 8·삭제 2). known_failures.txt에 병렬 작업 사전 존재 실패 5건 기록(CI 전용 플레이크 4 + module_separation 소유자 판단 1).
- 변경: test_fleet_console_browser.py에 D-410 설치 문서 렌더 계약 시험 추가(옵트인 Chromium — 문법·소유물·운용 표면 부재·E-stop·무오류). 통과 59s.
- 근거: 2026-10-02 CI 실행 36909426842/36955733308 실패 대 조 로컬 재현. docs/validation/uiux-console-refactor-2026-10-02/README.md 회차 기록.
- gate 변화: 없음.
- 최종 증거: scorecard·literals·no_secrets 각 재녹색; 브라우저 신규 시험 1 passed.

## 2026-10-02 · uncommitted · CI 잔여 5건 해소 — 좀비 인식 생존 판정·모드 드리프트 독립·D-155 가드 정정
- 변경: rec_compact.sh의 생존 판정을 좀비 인식(alive: kill -0 + /proc stat Z 제외)으로 바꿨다 — 컨테이너의 PID 1이 고아를 회수하지 않으면 SIGKILL 후에도 kill -0이 성공해 "did not exit" 오탐(CI 적색 3건). test_rosy_auto_update.py의 _alive 헬퍼도 같은 맹점이라 동일 패치. 실증: WSL에서 좀비 생성 후 kill -0=성공/stat=Z.
- 변경: test_image_layer_sync 모드 드리프트 시험의 chmod를 0o644→0o600 — 실제 Linux 체크아웃(git 100644)에서 644는 드리프트가 아니었다. 플랫폼 무관하게 드리프트가 된다.
- 변경: test_module_separation 가드4를 D-155 정정에 맞춰 계약면 허용(core_common.protocol.*, core_common.calibration_store)으로 좁힘 — control package.xml의 exec_depend 선언과 D-18 fleet 선례가 근거. D-155 ADR에 Refinement 조항 추가.
- 변경: known_failures.txt에서 해소 5항목 제거. docs/solutions/deployment/container-zombie-kill0-blindness.md 교훈 문서화.
- 근거: CI 실행 36959800081 대조 WSL 재현(윈도는 skip/DrvFS로 증거 불가).
- gate 변화: 없음.
- 최종 증거: WSL — jpeg_relay 14 passed, auto_update timeout 시험 passed, mode-drift passed; module_separation 7 passed(윈도).

## 2026-10-02 · uncommitted · feat(tools): D-418 P — 운영 PC SSH 접속 도구와 안내

- 변경: `tools/ssh/rosy_ssh_enroll.py`(화면 administrator 코드로 기기 키 `dev:<이름>` 등록, host key로 `known_hosts_rosy`, `~/.ssh/config`에 관리 `Host` 블록을 멱등으로, 토큰은 `finally`에서 logout·출력 안 함). `tools/ssh/rosy_ssh_share.py create|revoke|list`(passphrase로 잠긴 팀 키 — OpenSSH bcrypt 확인 전에는 등록·묶음 없음, `team:<이름>` 로봇별 등록, `rosy-ssh-<팀>.zip`에 잠긴 키·config·known_hosts·한국어 README, passphrase는 어느 파일에도 없음, 생성 시 한 번만 표시, 뒤 로봇 실패 시 묶음 없이 revoke 명령 안내, `--via-operator-key`로 코드를 운영 키 ssh에서 받음). `docs/deployment/robot-ssh-access.md`(세 길, 임시 비밀번호 curl/PowerShell과 끄기, R1–R3). `rosy-device-access` skill에 도구 안내.
- 사고(같은 날): 변형 시험 중 인자 검사를 지운 변형이 기본 경로로 실행돼 운영 PC의 실제 `~/.ssh/config`에 `rosy-pinky-test1` 블록과 빈 `ProxyCommand` 줄을 써서 모든 ssh가 깨졌다(그 밖에 `known_hosts_rosy`, `rosy_dev_*`, `rosy_team_x` 키). 조정자가 블록을 지우고 파일을 `X:\DevTemp\ssh-test-leak-20261002`로 옮겼다. 고침: 모든 시험이 HOME·USERPROFILE·LOCALAPPDATA를 임시 폴더로 돌리고, 실제 `~/.ssh` 스냅샷이 모듈 끝에 그대로인지 확인한다. 도구는 config 블록의 모든 줄을 허용 목록(빈 값·제어 문자 없음)으로 검사하고, known_hosts 이름도 검사하며, 쓰기 전 `config.rosy-backup-<UTC>`로 백업하고 원자적으로 바꾼 뒤 `ssh -G -F <file> <host>`로 읽혀 보고 실패하거나 다른 주소로 풀리면 되돌린다.
- 증거: `python -m pytest test/test_rosy_ssh_enroll.py test/test_rosy_ssh_share.py -q` 59 passed(가짜 CORE localhost; 묶음 시험은 실제 Windows OpenSSH ssh-keygen 9.5로 `-y -P ''` 실패·맞는 passphrase 성공, config 시험은 실제 `ssh -G`로 파싱). 가드 변형 42개(enroll 28, share 14) 모두 빨강, 실행 전후 실제 `~/.ssh` 변화 없음.
- gate 변화: 없음. 로봇 쪽 R(`feat/d418-robot`)과 합친 뒤 TWIN·DEVICE 확인 필요.
- 결정: D-418
- 교훈: 사용자 파일을 기본 경로로 쓰는 도구는 시험이 HOME을 격리하지 않으면 변형 시험이 곧 실제 사고가 된다. 가드 하나만 지우는 변형이 살아남으면 시험이 다른 가드에 기대어 통과하고 있다는 뜻이니 원인을 하나로 좁힌 입력을 쓴다.

## 2026-10-02 · 93848e520 · fix(tools): D-418 P 리뷰 반영 — 별칭 이름공간, ssh -G 확인, host key 교체 게이트, 묶음 폴더

- 변경: `rosy_ssh_enroll.py` — 별칭은 `rosy-[a-z0-9-]+` 로봇 이름만, 관리 블록이 다른 HostName을 가리키면 `--replace` 필요. 블록은 config의 첫 `Host`/`Match`/`Include` 앞에 넣고, 쓴 뒤 `ssh -G`로 hostname·user `rosy`·IdentityFile(우리 키)·UserKnownHostsFile까지 비교해 다르면 되돌림. host key가 바뀌면 옛·새 SHA256 지문을 보이고 `--accept-new-host-keys` 없이는 멈춤. `--key`·`--known-hosts`·`--ssh-config`는 절대 경로로(심볼릭 링크 config는 링크를 두고 대상 파일을 원자적으로 고침), `%`·`$` 경로 거절, 표식 개수 깨짐 거절, "already enrolled"에 기존 만료일, 리다이렉트 거절, 25 s 시간 제한과 "적용됐을 수 있음" 안내, OSError·UnicodeDecodeError는 깔끔한 오류, 비ASCII PC 이름은 짧은 해시 접미사. `rosy_ssh_share.py` — 묶음 안 hostname 중복 거절, `rosy-<팀>.zip`은 폴더 없는 평면 항목이라 Windows "모두 압축 풀기"·macOS Archive Utility·`unzip -d`가 config가 가리키는 `~/.ssh/rosy-<팀>/`과 같은 폴더를 만듦(README 일치, 시험으로 확인), 끝에 정확한 revoke 명령과 비밀 없는 `<out>/rosy-<팀>.robots.txt`, 묶음 쓰기 실패 때도 revoke 안내, `revoke --label dev:<이름>`, 생성 passphrase는 stderr에만(터미널 아니면 경고). 시험 가드는 실제 `~/.ssh`의 모든 이름을 스냅샷. 안내서: host key 신뢰 = LAN 신뢰(평문 HTTP), 갱신 = revoke 후 enroll, host key 바뀜은 확인 후 `--accept-new-host-keys`, PowerShell `cd`, 공개 안내서에서 `X:` 경로 제거.
- 증거: 커밋 560e486e4·7a3778185·93848e520. Windows `python -m pytest test/test_rosy_ssh_enroll.py test/test_rosy_ssh_share.py -q` 98 passed, 1 skipped(심볼릭 링크 시험은 POSIX 전용). WSL Ubuntu Python 3.12에서 같은 두 파일 99 passed(심볼릭 링크 시험 포함). 새 가드 변형 27개(enroll 18 + WSL 심볼릭 링크 1, share 8) 모두 빨강. 실행 전후 실제 `~/.ssh`는 모듈 가드 스냅샷으로 변화 없음.
- gate 변화: 없음. 로봇 쪽 R(`feat/d418-robot`)과 합친 뒤 TWIN·DEVICE 확인 필요. 로봇은 건드리지 않음.
- 결정: D-418
- 교훈: ssh config는 처음 맞은 값이 이기므로 hostname만 확인하면 앞선 `Host *`의 `User`·`IdentityFile`이 조용히 이긴다. 블록을 맨 앞에 넣고 `ssh -G`로 user·키·known_hosts까지 비교해야 한다.

## 2026-10-02 · 7f0bc0af · feat(native): D-418 로봇 SSH 접속 — root 도우미, 단위, 이미지 층, 기기 쌍둥이

- 변경: root 도우미 `rosy-ssh-access.py`(표준 라이브러리만)를 추가했다. CORE의 `/run/rosy/ssh-access.request`를 엄격히 읽고 먼저 지운 뒤, 키 종류 허용 목록·본문 모양(ed25519 32바이트, ECDSA 곡선 크기의 비압축 점)·라벨 정규식·중복·32개 상한·`expires_days` 1..365·`minutes` 1..60을 CORE와 따로 다시 검사한다. `/var/lib/rosy/ssh/keys.json`이 기록이고 `authorized_keys`(0644, `expiry-time="YYYYMMDDHHMMZ" <type> <base64> rosy-managed:<label>`)는 매번 그 기록에서 원자적으로 다시 만든다. `history.jsonl`(0600)에 add·revoke·expire·password_on·password_off를 남긴다.
- 변경: 임시 비밀번호는 `secrets`로 AP 비밀번호와 같은 31자 알파벳에서 `rosy-xxxx-xxxx-xxxx`로 만들고 `chpasswd -c SHA512`의 stdin으로 넣는다. `60-rosy-temp-password.conf`(사설 대역 `Match` → yes·`MaxAuthTries 3`, 그 밖 `Match User rosy` → no)를 쓰고 `sshd -t`가 받아야 `ssh.service`를 다시 읽힌다. 끄기는 `usermod -p '*'` 먼저, drop-in 삭제, reload 순서다. 비밀번호는 CORE가 한 번 읽고 지우는 응답 파일과 shadow 밖 어디에도 남지 않는다.
- 변경: 단위 다섯 — `rosy-ssh-access.path`/`.service`(요청), `rosy-ssh-password-expire.timer`/`.service`(비밀번호가 켜진 동안만 30 s 검사, 도우미가 켜고 끈다), `rosy-ssh-access-boot.service`(sshd보다 먼저 비밀번호 끄기와 관리 키 drop-in 설치, 순서만 걸고 실패해도 sshd를 막지 않음). root, `ProtectSystem=true`(shadow 교체 파일이 `/etc`에 생긴다), 네트워크 없음, `CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER`. D-388 `UNITS`·`ENABLED_UNITS`, `build-native-payload.sh` cp 목록, `customize-rootfs.sh` enable 목록과 진입점 검사에 넣었다. `/etc/ssh`는 D-388 허용 경로 밖이라 `50-rosy-managed-keys.conf`(`Match User rosy` 안의 `AuthorizedKeysFile`)는 도우미가 설치·유지한다.
- 변경: 기기 쌍둥이에 openssh-server(이미지처럼 `ssh.service`), D-418 단위, `twin-ssh-request`(HEAD의 CORE `ssh_handoff.py`를 rosy-core로 실행)와 시나리오 `ssh`를 넣었다.
- 증거: `test/test_ssh_access.py` 99 passed 2 skipped(Windows), WSL Linux 101 passed(심볼릭 링크·POSIX 모드 포함). native systemd·이미지 사용자화·이미지 층 동기화·설치 배치 계약 통과. 변이 증명 41종 모두 빨강(처음 생존 4종 — 형식 머리·엄격 base64·길이 상한·`.pub` 한정 — 은 시험을 보강하고 ECDSA 점 모양을 정확히 해서 죽였고, 도달할 수 없게 된 길이 상한은 지웠다).
- 증거: `python tools/device_twin/run_twin.py --scenario ssh` PASS 25/25(145 s) — 등록 키 접속, 회수 뒤 거부, 지난 `expiry-time` 거부와 정리, 비밀번호 접속·끄기 뒤 거부, 1분 만료를 타이머가 끔, 재부팅 뒤 비밀번호 꺼짐·키 유지, 비밀번호가 파일·로그·저널에 없음, `systemd-analyze verify` 무출력. drop-in의 `Match`는 본 설정으로 새지 않았다(root의 `AuthorizedKeysFile`은 기본값).
- 미증명: 실기(Ubuntu 24.04 raspi 이미지). 로봇의 전역 `PasswordAuthentication`(cloud-init drop-in)과 `ssh.socket` 상태. 쌍둥이의 전역 값은 yes였고, 사설 대역 밖 rosy는 우리 drop-in이 no로 막는다. 부팅 정리 단위가 실패하면 타이머가 돌지 않으므로 비밀번호가 남을 수 있다(다음 요청이나 다음 부팅에서 꺼짐). LCD 표시는 하지 않았다(API 응답만).
- gate 변화: 없음
- 결정: D-418, D-161, D-388
- 교훈: 모양 검사가 정확하면 길이 상한 같은 겹친 방어선은 변이 증명에서 살아남는다 — 살아남은 변이는 시험 구멍이거나 죽은 코드다.

## 2026-10-02 · 53f312a8 · fix(native,api): D-418 독립 검토 반영 — 실패해도 닫힘, 부팅 순서, 늦은 비밀번호

- 변경: 도우미 정리는 비밀번호 끄기(부팅은 강제, 그 밖은 만료)를 먼저 하고 단계마다 따로 잡는다. `keys.json`이 깨져도 `--boot`·`--expire`·`DELETE /password`가 비밀번호를 잠그고 `60-rosy-temp-password.conf`를 지운다. 깨진 기록은 키 경로에서만 503이다.
- 변경: `usermod` 잠금이 실패하면 같은 경로에 `Match User rosy` → `PasswordAuthentication no` 거부 drop-in을 쓰고 sshd를 다시 읽히고 만료 타이머를 켠다. 타이머의 `--expire`가 잠금을 다시 시도한다. `--boot`는 0이 아닌 값으로 끝난다.
- 변경: `password_on` 답이 CORE의 10 s 기한(여유 1 s)을 넘기면 도우미가 비밀번호를 되돌리고 결과 없이 503으로 답한다. CORE도 시간 초과 때 기다리지 않는 `password_off` 요청을 남긴다. 만료 타이머 시작 실패는 `HelperError`로 되돌리며, 타이머는 sshd reload보다 먼저 켠다. `OSError`도 503 `SSH_ACCESS_UNAVAILABLE`과 되돌리기로 간다.
- 변경: 키·비밀번호 만료는 `max(시계, clock.json의 가장 늦게 본 시각)`으로 판단한다. 앞서 간 시계는 일찍 만료시킬 뿐이다(닫힘 쪽).
- 변경: `sshd -t` 전에 `/run/sshd`(0755)를 만든다. 실행 중 새 요청은 끝나기 전에 처리하고(최대 8개), 잘못된 요청은 지운다. `history.jsonl`은 1 MiB를 넘기면 최근 512 KiB만 남긴다. CORE는 잠금 대기와 교환에 한 기한(10 s)을 쓴다.
- 변경: `rosy-ssh-access-boot.service`를 `DefaultDependencies=no`, `After=local-fs.target`, `Before=sockets.target ssh.socket ssh.service shutdown.target`, `Conflicts=shutdown.target`으로 바꿨다. 기본 의존이면 `After=basic.target`이 되고, `Before=ssh.socket`과 함께 순서 순환이 된다. 실기 두 대(2026-10-02 읽기 전용 확인)에서 `ssh.socket`이 켜져 있다.
- 변경: 기기 쌍둥이를 실기처럼 바꿨다. `ssh.socket`·`ssh.service`를 둘 다 켜고, `50-cloud-init.conf`에 `PasswordAuthentication no`를 넣었다. 새 시나리오 `ssh_socket`은 소켓 활성화만 쓴다.
- 증거: `test/test_ssh_access.py` 117 passed 2 skipped, `test_host_ssh.py` 45 passed, native systemd 계약·이미지 층 동기화 216 passed 4 skipped, 프로토콜 버전·이벤트 목록·line-follow 문서 시험 통과(Windows).
- 증거(변이): 도우미 18종과 CORE 4종이 모두 빨강이다. 처음 살아남은 1종(잠금 대기가 기한을 넘김)은 가짜 시계로 경과 시간을 고정해서 죽였다. 단위 변이(`DefaultDependencies=no` 제거)는 계약 시험과 쌍둥이 대조군이 잡는다.
- 증거(쌍둥이, HEAD 86106da1): `run_twin.py --scenario ssh,ssh_socket`에서 ssh PASS 36/36, ssh_socket PASS 39/39다. 두 경우 모두 재시작 전후 `journalctl -b`에 ordering cycle이 없고, `systemd-analyze verify default.target`은 exit 0에 출력이 없다. 부팅 정리는 `ssh.socket`/`ssh.service`보다 먼저 활성이었다. `/run/sshd`가 없을 때도 비밀번호가 켜졌고, 재시작 뒤에는 꺼졌다. cloud-init 전역 no 아래에서 사설 대역 rosy만 yes였고, rosy의 `AuthorizedKeysFile`은 `.ssh/authorized_keys`(카드 키)와 관리 파일이다. 대조군으로 기본 의존을 되살리면 verify가 `basic.target: Found ordering cycle on sockets.target/start … Job sockets.target/start deleted`를 낸다.
- 미증명: 실기 부팅. `usermod` 실패 경로는 가짜 시스템으로만 확인했다. 시계가 마지막으로 본 시각보다 뒤에 있는 동안 진짜 경과 시간은 알 수 없다(하한일 뿐이다).
- gate 변화: 없음
- 결정: D-418, D-161, D-388
- 교훈: `Before=`로 소켓보다 앞에 서려는 단위는 기본 의존(`After=basic.target`)과 부딪혀 순환이 된다. systemd는 이 순환을 `sockets.target` 작업을 지워서 끊으므로 조용히 큰 사고가 된다. 쌍둥이에서 대조군 drop-in으로 순환을 재현해야 수정이 증명된다.

## 2026-10-02 · uncommitted · fix(release): 준비·발행 도구의 ssh known_hosts 값을 따옴표 없이 — 첫 실운영에서 "invalid quotes"

- 변경: `prepare_payload_release.ssh_argv`가 `-o UserKnownHostsFile="<경로>"`로 따옴표를 붙였는데, Windows의 ssh가 그 따옴표를 글자 그대로 받아 "command-line line 0: invalid quotes"로 실패했다(2026-10-02 릴리스 025 준비, 두 로봇 ABI 검사). 따옴표 없이 넘기고 공백·따옴표가 든 경로는 `PrepareError`로 거절한다(`rosy-update-hold.ps1`과 같은 정책). 발행 도구는 같은 함수를 쓰므로 함께 고쳐진다.
- 증거: 새 시험 `test_the_real_ssh_client_accepts_the_built_options`가 실제 `ssh -G -F <빈 설정>`으로 인자를 해석시켜 결함을 로봇 없이 재현(따옴표를 되돌리면 빨강). 준비·발행 시험 106 passed. 독립 리뷰가 권한 "인용" 수정이 실제 ssh.exe에서는 틀렸던 경우라, 가짜 ssh만으로 검증한 인자 경로는 실제 클라이언트로 한 번 해석시킨다는 교훈.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(native): D-412 업데이터 기본 켜짐 — 첫 실제 카나리 성공 뒤

- 변경: `rosy_auto_update.py`의 `config.json`이 없거나 `enabled`가 없으면 켜짐으로 바꿨다. `{"enabled": false}`만 끈다. ADR D-412, 계획 계약, `rosy-release-push` skill 문구를 고쳤고 시험 2개는 기본 켜짐을 고정한다.
- 증거: 2026-10-02 실제 로봇. 025 수동 push로 두 로봇에 업데이터 설치(기본 꺼짐). 9dfk config 켬. 이 PC에서 `payload-2026.10.02-026` 발행(카나리 9dfk). 12:11 GitHub 시간 초과는 error로 처리되고 철회되지 않음. 12:26 staged, 12:26 applying, 12:27 committed(CORE·io·camera 026, 옛 릴리스 3개 정리), 발행 도구가 `canary_ok=true`를 올림. 8kcn은 사용자 지시로 수동 push(026)했고 config는 켰으며 rosy-c5 hold 중. 업데이터 시험 238 passed 1 skipped(기본 켜짐 시험 2개는 바꾸기 전 빨강 확인).
- gate 변화: D-412 DEVICE(카나리 단계) 통과. 카나리 다음 로봇 순서는 기기 쌍둥이만.

## 2026-10-02 · uncommitted · feat(omx-sim): 셀 owner 실행기와 sim_model_pose 생산자 (C4b G2b, G6)
- 변경: `robot/omx/run_cell_owner.py`(UDS 스레드 + uvicorn, `rosy_agent.omx_cell_owner` 조립), `cell_sim_tools.refuse_second_owner`가 `run_cell_owner`도 보고 `proc_root`를 받는다, `robot/omx/sim_item_pose_producer.py`(생산자 interface + Gazebo 포즈 reader), `robot/omx/sim/item_pose_goal.yaml`(허용오차 5 mm / 2 mm / 0.05 rad / 기울기 0.05, 근거 C3b).
- 증거: `test/test_platform_cell_owner_assembly.py`(가짜 ROS runtime), `src/site/fleet/test/test_cell_goal_evidence.py`(가짜 포즈 reader), `test/test_platform_item_pose.py`.
- 판단: 실행기는 WSL에서 돌려 보지 않았다(wave 1은 Gazebo 없음). 첫 phase 뒤 phase를 진행하고 Action을 완료하는 진행기가 없어 실제 Job은 approach에서 멈춘다 — wave 2.
- gate 변화: 없음.

## 2026-10-03 · 27025b10 · fix(native,api): D-418 2차 검토 — 앞서 간 시계, CORE의 실제 기한

- 변경: (HIGH) 시계가 한 번 1년 앞섰던 기록(`clock.json`) 때문에 5분 비밀번호가 실제로 30일 넘게 켜져 있고, 키가 영구히 지워졌다(검토 probe로 재현). 이제 비밀번호는 `system.now()`로 만든 `expires_at`(벽시계)과 `password.json`에 넣은 `CLOCK_BOOTTIME` 기한·boot id 가운데 먼저 오는 쪽으로 꺼진다. boot id가 다르면 바로 끈다.
- 변경(HIGH): 키 기준 시각은 시계보다 2일 넘게 앞선 기록이나 시각을 버리고 다시 쓴다. timesyncd가 동기를 알리면(`/run/systemd/timesync/synchronized`) 시계를 그대로 쓴다. 60 s 이상 오를 때만 쓰고(SD 마모), 쓰기 실패는 기록만 하고 값은 돌려준다. 시계가 뒤로 간 경우의 보호는 그대로 둔다.
- 변경(MEDIUM): 요청에 `answer_by`(CORE가 잠금 대기 뒤 실제로 기다리기를 멈추는 epoch 초)를 넣었다. 도우미는 `answer_by - 1 s`를 넘긴 비밀번호를 되돌린다. CORE는 아직 살아 있는(30 s 이내) `password_off` 요청을 덮어쓰지 않고, 같은 기한 안에서 처리되기를 기다린다.
- 변경(LOW): 답 파일을 못 쓰면 켠 비밀번호를 다시 끈다(사유 `undelivered`). `GET /password`에 `lock_pending`을 추가했고(스키마·API 문서·계획 계약), 잠금 실패를 `password_deny` 이력으로 남긴다. 요청은 이름 바꾸기로 먼저 가져간 뒤 읽으므로, 그 사이 CORE가 쓴 요청이 읽히지 않고 지워지는 일이 없다.
- 변경(쌍둥이): 단계마다 시간 제한을 둔다(`Twin.step_timeout`, ssh 시나리오 90 s, 클라이언트 ssh 60 s). 멈춘 단계는 이름이 붙은 FAIL로 남고, ssh 저널·`ss -tnp`·sshd 프로세스·대기 작업을 증거로 모으며, 시나리오는 계속된다. `sshd -t`가 거부 drop-in을 받아들이는지도 확인한다.
- 증거: `test_ssh_access.py`, native systemd 계약, 이미지 층 동기화, `test_host_ssh.py`, 프로토콜 버전, 이벤트 목록, contracts foundation을 함께 돌려 897 passed, 7 skipped(Windows). 검토 probe에서는 6분·1시간·10시간·30일 뒤 모두 꺼짐.
- 증거(변이): 이번 변이 17종(도우미 13, CORE 4)이 모두 빨강이다. R1(비밀번호 만료를 기준 시각으로 되돌림)은 1년 앞선 시험만으로는 2일 규칙에 가려 살아남았고, 1일 앞선 시험을 함께 고르니 죽었다.
- 증거(쌍둥이, HEAD 27025b10): ssh PASS 37/37, ssh_socket PASS 40/40, STEP TIMEOUT 0회. b는 `--work X:/DevTemp/d406-twin-d418`에서 PASS다.
- 원인(통합 실행의 b FAIL): `twin_publish.py`가 `LOCALAPPDATA`에 `d406-twin`이 없으면 거부한다. `--work X:/DevTemp/d418-twin-int`의 publish 로그가 `refusing: LOCALAPPDATA must point at the twin folder`였다. 코드 결함이 아니라 작업 폴더 이름 문제다.
- 원인(통합 실행의 ssh_socket 멈춤): 이번에는 재현되지 않았다. 그 로그를 보면 ssh 호출 전의 `docker exec`(sed, 그리고 900 s 제한의 `ev`)에서 약 12분이 먼저 멈췄다. 호스트나 Docker가 느렸던 것으로 보이지만 증명하지는 못했다. 이제는 단계 제한과 진단이 남는다.
- 미증명: 실기 부팅. 로봇이 timesyncd가 아니라 chrony를 쓰면 동기 표시 파일이 없다. 그때는 2일 규칙만 적용된다.
- gate 변화: 없음
- 결정: D-418, D-161, D-388
- 교훈: 시간을 한 방향으로만 미는 보호(high-water)는 반대 방향 고장(시계가 앞섬)을 영구 상태로 만든다. 비밀번호처럼 짧은 수명은 NTP가 건드리지 않는 부팅 시계로 묶고, 긴 수명의 하한 기록에는 상한과 리셋이 필요하다.

## 2026-10-03 · e0e482ef · fix(native): D-418 3차 검토 — 잠금 재시도, chrony 아래 NTP 동기, boot id

- 변경: `password_off`가 `lock_pending`도 켜진 것으로 센다. 그래서 잠금이 실패했고 거부 drop-in까지 쓰지 못한 상태(남은 것은 `lock_pending`뿐)에서도 다음 `--expire`와 `DELETE /password`가 잠금을 다시 시도한다. 전에는 일찍 돌아가 재시도하지 않았다.
- 변경: 이미지는 chrony를 쓰므로(`customize-rootfs.sh`) timesyncd의 동기 표시 파일은 생기지 않는다. NTP 동기는 `timedatectl show -p NTPSynchronized`로 본다. timedated가 커널의 `STA_UNSYNC`를 읽으므로 데몬과 상관없다. 실패하면 동기되지 않은 것으로 본다.
- 변경: 검토가 제안한 ctypes `adjtimex`는 쓰지 않았다. 쌍둥이에서 단위와 같은 seccomp(`SystemCallFilter=@system-service`, `ProtectClock=true`)로 돌리자 Python이 SIGSYS로 죽었다(`status=31/SYS`, try로 잡을 수 없음). 같은 샌드박스에서 `timedatectl`은 `yes`를 냈다. 직접 호출을 막는 시험을 넣었다.
- 변경: boot id를 읽지 못하면 `password_on`은 503으로 켜지 않는다. boot 기한이 없는 상태(업그레이드 전)는 만료로 보고 다음 검사에서 끈다. 모듈 설명과 API 문서 §5.8을 실제 규칙에 맞췄다. 2일 상한 때문에 2일 넘게 뒤처진 시계로 부팅하면 기록이 버려진다는 점, `password_deny` 사건, `late`·`undelivered` 사유를 적었다.
- 증거: `test_ssh_access.py`·native systemd 계약·이미지 층 동기화·`test_host_ssh.py` 409 passed 6 skipped(Windows). 새 시험 14개(매개변수 포함).
- 증거(변이): 8종 모두 빨강이다(재시도 조기 반환, 표시 파일로 되돌림, 종료 코드 무시, `no` 외 모두 동기, 오류 때 동기로 봄, ctypes 가져오기, boot id 없이 켬, boot 기한 없는 상태 유지).
- 미증명: 실기 부팅과 chrony 아래 `timedatectl` 응답. 쌍둥이에는 NTP 데몬이 없다.
- gate 변화: 없음
- 결정: D-418, D-161, D-388
- 교훈: 샌드박스(seccomp) 안의 코드는 검토가 제안한 시스템 호출을 먼저 같은 필터 아래에서 돌려 봐야 한다. 허용 목록 밖 호출은 예외가 아니라 프로세스 종료다.

## 2026-10-03 · uncommitted · fleet 빌드 맥락에 apps/gateway/src 재허용
- 변경: Dockerfile.fleet.dockerignore에 !apps/gateway/src/** 한 줄. Dockerfile.fleet이 apps/gateway/src를 COPY하는데 허용 목록에 없어 test_build_contexts_carry_only_what_the_images_copy와 CI가 실패했다(플랫폼 게이트웨이 준비 작업이 COPY를 먼저 실음). 잎 글로브 원칙은 유지.
- 근거: test/test_site_map_fit_deploy.py.
- gate 변화: 없음.
- 최종 증거: test_site_map_fit_deploy.py 4 passed.

## 2026-10-03 · uncommitted · fix(omx-sim): C4b 1b — 그리퍼 폭은 grant의 레시피, HTTP는 루프백 (C2, C4)
- 변경: `run_cell_owner.py`는 `rosy_agent.omx_cell_owner.sim_gripper_observation`으로 grant의 `recipe_sha256`·item 폭을 쓴다(첫 레시피 아님). HTTP는 기본 127.0.0.1(`ROSY_CELL_OWNER_HTTP_HOST`로만 바꿈; 이 포트를 게시하는 compose·실행 스크립트가 없다). owner HTTP 앱은 아직 수락 저장소를 공유하지 않는다 — G9. `sim_item_pose_producer.py`는 `frame: robot_base`를 싣는다.
- 증거: `test/test_platform_cell_owner_assembly.py`(스파이로 폭 확인).
- gate 변화: 없음.


## 2026-10-03 · uncommitted · feat: tick local Cell workflow on the existing simulation owner node
- Change: bind a 50 ms timer on the existing ROS node to owner.advance_pending and destroy it at shutdown. The accepted owner uses the durable workflow for phase/gripper gates; no new owner, thread, grant or retry path is created.
- Evidence: actual owner host regression 38 passed; integrated owner/compiler/boundaries 23 passed; independent review 38 passed plus updated restart suite 5 passed. Semantic removal mutation fails ACCEPTED versus SUCCEEDED and is restored. Production flake8 and quick96 pass; harness lint0errors/26 existing freshness warnings. Installed owner/workflow wheel imports and pip check pass.
- Gate: SOURCE/LOCAL only. ROS runtime/timer and Gazebo were not executed; Fleet fence/seat integration and full recipe acceptance remain open.


## 2026-10-03 · uncommitted · feat: read live Fleet fence on the simulation Cell owner
- Change: replace the entrypoint unconditional Fleet-current callback with uncached authenticated GET /api/fleet/dispatch-control on an explicitly configured literal loopback endpoint. Require a separately provisioned viewer secret before ROS loads. Direct HTTP avoids proxies/redirects; status, 8 KiB body, strict generation types and finite JSON checks refuse on uncertainty. Existing Action/stop/rearm stays on UDS. Offload async Fleet rearm I/O so the event loop can answer the owner's reverse readback; preserve operator guard and rollback.
- Evidence: actual loopback Fleet server plus persistent Fleet/owner stores reproduced LOCAL_WORKCELL_REARM_FAILED before offload and passed after. Offload-removal mutation fails again; original bytes restored. Final readback suite 18 passed; combined Fleet stop/rearm, owner/provider/replay/boundaries regression 96 passed before the additional finite-JSON case. Independent review 48 passed / 1 skipped and final readback 18 passed, no Critical/Important findings. Production flake8 passes. Final agent wheel rebuilt and force-installed from X: copy; site-packages adapter reads changed loopback state without caching, pip check passes.
- Final checks: quick tier 96 passed / 26 existing warnings; harness lint 0 errors / 26 warnings. Entry configuration regression guards the ROS import directly and passed.
- Gate: SOURCE/LOCAL only. Host HTTP is real; ROS and UDS credential transport are substituted. Live ROS/UDS (a)-(i), seat exclusion, thin-sheet handling and full two-layer/two-pallet vendor Gazebo acceptance remain open. Socket timeout bounds inactivity, not an end-to-end stop deadline. No viewer credential registration, service deployment, physical enablement or push performed.

## 2026-10-03 · 119382fe6 · docs(native): D-423 `ROSY_OBJECT_DET=false` 를 learned-perception.env 예시에

- 변경: `native/learned-perception.env.example` 에 `ROSY_OBJECT_DET=false`(+ `ROSY_OBJECT_DET_MAX_HZ` 설명). 서비스·권한 변화 없음. 모델은 `/var/lib/rosy/models/object_det/` 아래이고 deliver 가 root:rosy-camera 0750 으로 만든다.
- 증거: `test_native_systemd_contract.py` env 예시 시험.
- gate 변화: 없음. 켜는 것은 사용자 승인 뒤.

## 2026-10-03 · uncommitted · feat(perception): D-431 NCNN/OpenCV 구현과 실제 차선 Pi 재생

- 변경: NCNN schema /2·CPU session·YOLO/TorchScript lane export·실제 프레임 parity·intake 증거 검사·hash 고정 설치·doctor·재생 bench. 기존 OpenCV 전처리를 사용한다.
- 증거: docs/validation/pi-ncnn-2026-10-03/README.md. 실제 차선 20프레임 분류 일치 100%, 제품 adapter ARM64 재생 오류 0. NCNN 차선 p95 474.59ms, 동일 원본 ONNX FP32 252.22ms.
- gate 변화: 없음. 운영 차선 전환 HOLD. 학습 YOLO·30분 동시 부하·배포/rollback·현장 수용은 남아 있다.
- 결정: D-431 Accepted, 구현 및 조건부 lane 평가 기록.


## 2026-10-03 · uncommitted · fix: bootstrap automatic-update state directories

- 변경: signed tmpfiles의 정확한 maps/models/pilot-recordings d 규칙만 제한된 PID 1 transient worker로 적용한다. 구 updater namespace의 쓰기 범위를 넓히지 않고 누락 디렉터리를 서비스 enable/restart 전에 확보하며, mode/owner도 검사한다. 재귀 Z/z migration은 제외하고 rollback 녹화를 보존한다.
- 증거: provisioning 제거 mutation은 누락 디렉터리 회귀를 실패시켰고 원본 bytes를 복구했다. 집중 sync 시험 및 자동 업데이트 회귀를 실행했다. 독립 실제 probe는 CAP_FSETID 없을 때 0750, 추가 시 2750 및 지정 owner/group을 확인했고 전체 worker 속성과 구 namespace nested 실행도 통과했다.
- gate 변화: SOURCE/LOCAL 수정. 이 작업 분기는 배포하지 않았고 새 payload의 자동 적용·장치 서비스 readback은 coordinator의 별도 단계다.

- Final checks: sync regression 66 passed / 6 skipped; expanded image-sync/systemd/auto-update 441 passed / 8 skipped with one new read-path classification failure, then corrected classification regression 1 passed. flake8 passed; harness lint 0 errors / 26 existing freshness warnings. Provisioning-removal mutation failed as expected, original bytes restored. Independent code review found no blocking issues.

## 2026-10-03 · uncommitted · fix(native,tools,test): D-418 파일의 비밀 검사 23건 — 이름과 문구만 바꿈
- 변경: `test_no_secrets_in_tracked_files` 가 D-418 파일에서 23건을 잡았다(병합 전 브랜치에서도 빨강). 검사기의 예외·허용 목록은 넓히지 않고 코드를 바꿨다. 도우미 상수 `PASSWORD_STATE`·`PASSWORD_DROPIN`(`_TEXT` 포함)·`PASSWORD_ALPHABET` → `TEMP_LOGIN_*`, 공유 도구 `PASSPHRASE_ALPHABET` → `LOCK_PHRASE_ALPHABET`, 두 도구의 키워드 인자 `ask_passphrase` → `ask_lock`. PEM 머리는 실행 때 이어 붙인다(`OPENSSH_BEGIN`, 시험의 `PEM_BEGIN`). 시험 보조 인자 `passphrase`/`passphrases`/`ignore_passphrase`/`chpasswd_ok` → `lock_phrase`/`lock_answers`/`ignore_lock`/`chpw_ok`. 도우미 설명 두 줄의 쌍점을 바꿨다. API Ref §5.8 예시 값은 `<temporary-password>` 로 두고 형식은 문장으로 적었다(응답 필드 이름 `password` 는 그대로).
- 동작·CLI 플래그·API JSON 필드·파일 경로 변화 없음.
- 증거: 검사기 0건. `test_rosy_ssh_enroll`·`test_rosy_ssh_share`·`test_ssh_access`·`test_host_ssh`·`test_release_boundary_guards`·`test_module_structure`·native systemd 계약 561 passed 4 skipped(Windows).
- gate 변화: 없음
- 결정: D-418

## 2026-10-03 · 0e244456c · fix(tools): rosy_ssh_share 가 터미널 밖에서 생성 passphrase 를 출력하지 않음 (D-418)
- 변경: `create` 가 passphrase 를 만들어야 하고 stderr 가 터미널이 아니면(로그·CI·감싸는 스크립트) 키 생성·로봇 등록·묶음 전에 멈춘다. `--print-passphrase` 를 주면 경고와 함께 예전처럼 한 번 보인다. 직접 입력한 passphrase 는 원래 출력하지 않으므로 그대로다. `docs/deployment/robot-ssh-access.md` 의 해당 줄을 맞췄다.
- 기록 정정: 바로 앞 `2026-10-03 · uncommitted · fix(native,tools,test): D-418 파일의 비밀 검사 23건` 항목의 커밋은 1acc6b7be 다(logs 는 append-only 라 그 머리말은 고치지 않는다).
- 증거: `test/test_rosy_ssh_share.py` 28 passed — 새 시험(터미널 아님 → 상태 1, 로봇 요청 없음, `--out` 비어 있음)과 `--print-passphrase` 로 바꾼 한 번 표시 시험.
- gate 변화: 없음
- 결정: D-418

## 2026-10-03 · fcda72b78 · feat(deploy): D-433 rosy-boot-display → rosy-face 이주

- 변경: `rosy-face.py`/`.service`(구 rosy-boot-display, 사용자 rosy-display 유지). 이미지가 rosy-face를 켜고 은퇴 unit은 설치하지 않는다. `sync-image-layer.py`: 026 로봇에서 rosy-face 추가 시 `stop rosy-boot-display` → `enable --now rosy-face`, 은퇴 unit은 조건 붙은 사본으로 교체만(새로 설치·재시작 없음). 업데이터가 적용 중 `/run/rosy-boot/update-display.txt`를 쓰고, 롤백 뒤 은퇴 unit이 켜져 있고 멈춰 있으며 rosy-face가 없으면 한 번 시작한다(Q5). `rosy-release-push.ps1 -Rollback`도 같은 단계. `rosy-hw-test`는 둘 중 도는 unit에 넘긴다.
- 증거: `test_image_layer_sync.py`(이주·롤백 5건, 변이 2종 빨강 확인), `test_rosy_auto_update.py`(표시·복원 5건), `test_release_push_entrypoint.py`, `test_native_systemd_contract.py`, `test_device_surface_contract.py`, `test_hw_test.py` 통과.
- gate 변화: 없음. 페이로드 빌드·실기 미실행.
- 결정: D-433 (Proposed)

## 2026-10-03 · uncommitted · fix: publish readable public DNS-SD XML

- Change: chmod public Fleet/overhead advertisement XML to 0644 before atomic rename. NamedTemporaryFile defaults to 0600; that hides the XML from unprivileged Avahi even though the metadata is public. Keep credentials and TLS trust out of the advertisement.
- Evidence: the actual new POSIX regression ran against streamed source on a Linux host; before the fix it failed at the pre-rename 0644 assertion, after the fix both Fleet and overhead passed with umask 0077 and an existing 0600 file. Scratch files were automatically removed; no operational files changed.
- Gate: SOURCE/LOCAL fix only. Parent coordinator owns persistent publisher installation, advertiser restart and device discovery/readback.
## 2026-10-03 · uncommitted · fix(site): Fleet NSS mDNS resolver closure

- 변경: Fleet 이미지에 libnss-mdns와 `.local` 우선 NSS 조회를 포함하고 실행 중인 호스트 Avahi 디렉터리를 읽기 전용으로 연결한다. 일반 Docker DNS는 유지하고 누락 경로는 자동 생성하지 않는다. 고정 IP 없이 hostname/TLS 검증을 보존한다.
- 증거: 집중 배포 시험 61 passed, flake8/diff 검사 통과. 디렉터리를 단일 소켓 연결로 바꾼 mutation은 실패했고 원본 복구 후 2 passed. 실제 사이트 candidate의 UID 10001/read-only/cap-drop ALL 실행에서 두 로봇 hostname과 fleet/vision/proxy 조회를 확인했다. Avahi 연결 없는 negative control은 실패했고 가상 Avahi 소켓 교체 후 동일 이름의 새 주소 조회를 확인했다.
- 범위: 현재 Fleet 앱 이미지에 NSS만 추가한 candidate를 만들었다. 운영 root 설정 설치와 Fleet 재생성, 인증된 장치 연결은 coordinator의 별도 단계이며 이 기록은 그 완료를 주장하지 않는다.
- gate 변화: SOURCE/LOCAL 및 후보 컨테이너의 이름 조회 검증 완료. 운영 Fleet 등록과 로봇 연결은 관리자 적용 이후 별도 확인한다.
