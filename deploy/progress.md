---
module: deploy
logical_modules: [M01, M13, M14]
owner: 릴리스·플랫폼
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "unsigned handoff importer 40 passed; release/device 집중 370 passed, 2 skipped; 실제 397bb25 artifact 17 files + 2 linux/arm64 images bounded-stream import PASS (2026-09-21)"
    cmd: "python3 -m pytest test/test_unsigned_handoff_import.py test/test_arm64_release_builder.py test/test_release_manifest.py test/test_release_signing.py test/test_release_bundle.py test/test_pinky_commissioning.py test/test_device_readback.py -q"
  LOCAL:
    state: GO
    evidence: "1093 passed, 13 skipped, 6 known harness warnings (2026-09-21 Windows, uncommitted)"
    cmd: "python3 -m pytest test -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "Ubuntu 24.04.5 raspi base URL/SHA는 고정했으나 native ARM64 host 다운로드 검증, native Jazzy/ROSY payload 실행, 완성 이미지·SBOM·서명 전"
  DEVICE:
    state: HOLD
    blocker: "Ubuntu native product image의 SD write/readback, Pi 5 boot, ROS graph, 장치 ACL, deadman 실기 증거 없음"
  FIELD:
    state: N/A
adrs: [D-22, D-26, D-30, D-33, D-36, D-46, D-53, D-124, D-144, D-145, D-146, D-161, D-164, D-165, D-179]
plans:
  - docs/plans/2026-09-01-rosy-os-v1-image-release-design.md
  - docs/plans/2026-09-08-release-delivery-design.md
  - docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-21-pinky-device-commissioning-design.md
  - docs/plans/2026-09-21-native-arm64-release-builder-design.md
  - docs/plans/2026-09-21-native-arm64-release-builder.md
  - docs/plans/2026-09-21-pinky-connection-evidence-design.md
  - docs/plans/2026-09-21-pinky-connection-evidence.md
  - docs/plans/2026-09-21-hardware-mapping-g5-design.md
  - docs/plans/2026-09-21-hardware-mapping-g5.md
  - docs/plans/2026-09-21-unsigned-handoff-import-design.md
  - docs/plans/2026-09-21-unsigned-handoff-import.md
  - docs/plans/2026-09-21-ubuntu-native-ros-runtime-design.md
  - docs/plans/2026-09-21-ubuntu-native-ros-runtime.md
  - docs/plans/2026-09-22-pinky-pro-flashable-image-design.md
  - docs/plans/2026-09-22-pinky-pro-flashable-image.md
  - docs/plans/2026-09-23-core-dev-overlay-design.md
  - docs/plans/2026-09-23-core-dev-overlay.md
---
## 지금 상태

- D-161 제품 기준선은 Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy다.
  `rosy-runtime.target`은 CORE만 기본 시작하고 I/O/navigation은 승인 후 명시적으로 시작한다.
  Compose는 개발·CI 호환 경로일 뿐 제품 이미지 의존성이 아니다.
- D-164 제품 배포 파일은 ISO가 아니라 Raspberry Pi Imager로 직접 기록하는 서명된
  `rosy-os-pinky-pro-<release-id>-arm64.img.xz`다. `.img`는 build workspace 밖으로
  배포하지 않고 장치별 값은 write 후 one-shot bundle로만 넣는다.
- Device readback은 identity, activation/manifest digest, 서명 상태, core health, `cmd_vel` publisher 수를 secret 없는 JSON으로 수집하고 불일치 시 `device_runtime=HOLD`다.
- Pinky 커미셔닝 세션은 G0-G5 순서를 강제한다. G0-G2는 서명 stage/manifest,
  install/readback 원문에서 유도하며 G3-G5는 물리 측정 전 템플릿 상태로는 통과하지 않는다.
- binfmt 등록 후 ARM64 core/io 개발 후보 빌드와 import 확인까지 했다. 발행 가능한 artifact는 아니다.
- `arm64_release_builder.py`는 native Linux `aarch64`, ARM64 Docker daemon, clean full revision, digest-pinned ROS base만 허용하고 core/io의 linux/arm64·revision label·image ID를 검증한 뒤 비밀 없는 unsigned payload를 원자적으로 만든다. OCI archive는 검사된 immutable image ID에서 저장하며 서명은 기존 offline packager만 수행한다.
- `verify-from-windows.ps1`는 exact host의 bounded SSH와 API/dashboard를 확인하고 성공·실패 모두 no-overwrite JSON evidence로 남긴다. 이 증거는 연결성만 증명하며 G0나 DEVICE를 승격하지 않는다.
- `import_unsigned_payload.py`는 D-145 archive를 서명 전에 checksum, 안전한 archive 경계, release identity, payload hash, CORE/IO `linux/arm64`까지 검증하고 `signed: false` handoff만 원자적으로 노출한다.
- `6f6c515`의 전체 host 회귀가 통과했다. 이 증거는 장치/물리 인수를 대신하지 않는다.
- 서명된 native release는 manifest와 payload를 검증한 뒤 `current`를 원자 교체하고,
  health 실패나 전원 중단 journal이 남으면 `previous`로 복구한다. 이 경로는 network와
  Docker를 요구하지 않는다.
- Windows SD writer는 검증된 기록 뒤 DPAPI Wi-Fi 자격을 stdin으로 bundle 생성기에
  전달하고 선택한 물리 디스크의 boot 파티션에만 one-shot bundle을 원자 복사한다.
  Ubuntu first boot는 hostname, DDS 신원, mode 0600 NetworkManager/Fleet bootstrap과
  hardware serial binding을 적용한 뒤에만 CORE gate를 연다.
- D-179 벤치 오버레이는 `deploy/robot/dev/core_dev_overlay.py`와 Windows 동기화 스크립트로
  호스트에서 검사된다. readback은 오버레이가 남아 있으면 `device_runtime=HOLD`다.
  제품 `current`, 설치기, GitHub 설치 경로는 그대로다. 로봇에서 한 줄을 바꾼 증거는 아직 없다.

## 다음 gate

1. native ARM64 Ubuntu 24.04 host에서 고정 base image를 내려받아 SHA-256을 확인하고 native ROSY payload를 실제 빌드한다(ARTIFACT).
2. full Ubuntu image customizer로 검증된 payload와 immutable first-boot overlay를
   base image에 설치하고 SBOM·서명·read-only mount 검증을 완료한다(ARTIFACT).
3. [첫 장치 런북](../docs/deployment/pinky-pro-first-device-runbook.md)의 G0-G5를
   Ubuntu SD에서 실행하고 session/raw evidence를 보존한다(DEVICE).

## 현재 유효한 금지사항

- CORE 안에 `nmcli`, `reboot`, systemd/compose 제어를 넣지 않는다. 호스트 권한은 Host Agent만 가진다(D-161).
- D-161 제품 이미지에 Docker/Compose를 설치하거나 제품 boot dependency로 두지 않는다.
- release 이미지는 x86 QEMU 결과로 발행하지 않는다.
- 로봇 identity에 기본값을 두지 않는다(D-33).
