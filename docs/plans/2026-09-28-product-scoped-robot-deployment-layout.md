# 제품별 로봇 배포 폴더 이행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pinky Pro와 OMX 배포 소스를 `deploy/robot/<product>` 아래에 정리하고, 사이트 배포는 별도로 유지한다.

**Architecture:** [D-320](../adr/D-320-product-scoped-robot-deployment-layout.md)에 따라 Pinky 전용 image/release/SD 도구와 기존 runtime 디렉터리를 제품 루트로 모으고 OMX 개발·시뮬레이션 후보도 같은 로봇 루트 아래 둔다. 저장소 소스 경로를 제품 우선으로 정리하되 현재 `/opt/rosy` 설치 경로와 runtime authority는 보존한다.

**Tech Stack:** Git path migration, Python/pytest, PowerShell contracts, Dockerfile/Compose path closure, ROS 2 Jazzy deployment metadata, documentation harness.

---

## Target tree

```text
deploy/
├─ robot/
│  ├─ pinky_pro/
│  │  ├─ image/           # signed Pi ARM64 image and native payload inputs
│  │  ├─ release/         # Pinky payload, signing, update and Host Agent tools
│  │  ├─ sd/              # Pinky image verification and per-card provisioning
│  │  ├─ config/          # Pinky profiles
│  │  ├─ native/          # Pinky native systemd runtime and host services
│  │  ├─ verify/          # Pinky device checks
│  │  └─ ...              # existing Pinky installation/development tools
│  └─ omx/                # current disabled workstation/development/ROS-SIM candidate
└─ site/                  # Fleet, Vision and Caddy site host
```

No empty future robot or OMX field-runtime directory is created. Existing installed paths remain stable: the Pinky payload continues to stage native runtime under `/opt/rosy/deploy/robot/`, SD tools under `/opt/rosy/deploy/sd/`, and release command tooling under `/opt/rosy/deploy/release/`; source paths and install paths are explicit separate mappings.

## Tasks

1. Add the D-320 decision and this plan; add D-320 to the ADR log. Preserve prior ADR history.
2. Add a failing deployment-layout contract test for the target product roots and retired top-level paths.
3. Move the existing `deploy/robot` contents beneath `deploy/robot/pinky_pro`, then move `deploy/image`, `deploy/release`, and `deploy/sd` under that product. Move the current `deploy/omx` workstation candidate to `deploy/robot/omx`.
4. Update executable code, build manifests, test path constants, test import bootstrap, GitHub workflows, current AGENTS/README/runbooks, and Harness module paths. Keep dated logs and historical ADR evidence unchanged; add a current mapping note where an old plan still describes the pre-migration layout.
5. Update `deploy/AGENTS.md` and `deploy/robot/AGENTS.md` to describe the new parent/product split. Preserve a specific OMX README/AGENT statement that it is development/ROS-SIM only.
6. Run `git diff --check`, the deployment structure contract, all host deployment/release/OMX/site contract tests, docs ADR/harness tests, and `python tools/harness/rosy_harness.py lint` and `generate`. Search active code/config/docs for stale source paths while excluding immutable dated logs and historical ADRs.
7. Confirm legacy installed paths in native image and payload staging remain unchanged. Do not claim native ARM64/Jazzy artifact equivalence or DEVICE/FIELD acceptance without those independent gates.
8. Commit the verified migration, fast-forward local main if ancestry and changed paths are safe, re-run selected contracts on the merged tree, and push only after checking the exact remote delta and preserving unrelated working-tree changes.

## Acceptance checklist

- [x] `deploy/robot/pinky_pro/{image,release,sd,native,config,verify}` exists and old source roots are absent.
- [x] `deploy/robot/omx` exists with the current disabled development/simulation contract.
- [x] `deploy/site` remains independent.
- [x] No executable/test/current-document reference points at removed source roots.
- [x] Existing `/opt/rosy` install/readback paths and ROS/product ownership decisions remain unchanged.
- [x] Required host tests and harness pass; warnings and unavailable ARM64/device gates are reported separately.
