# Pinky deployment fast path implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Avoid full ARM64 image builds when a Pinky source change needs only a native payload or no device artifact, without skipping signing, compatibility, or device readback gates.

**Architecture:** Add a fail-closed release-impact selector that compares a deployed source revision with a candidate revision and classifies changed paths as no Pinky artifact, native payload, flashable image, or manual review. Wire the selector into the Pinky commissioning runbook and add D-325 to make the artifact choice explicit. Keep existing ARM64 workflows, offline signing, payload compatibility checks, and physical acceptance unchanged.

**Tech Stack:** Python standard library, Git, pytest, Markdown, ROSY documentation harness.

---

## Decision options

1. **Always build a flashable image.** Simple, but recent evidence shows about 27 minutes of ARM64 build time even for changes that do not require an image.
2. **Always build a native payload for an existing robot.** Recent payload workflow took about 5 minutes, but this can miss base OS, boot, hardware dependency, or native host-service changes.
3. **Select the smallest artifact from a closed path policy (recommended).** Docs, tests, simulator-only, and separate Site/OMX paths produce no Pinky artifact; ROS source changes select the existing native-payload workflow; image/base-system changes select the flashable-image workflow; unclassified Pinky paths produce HOLD for review. Mixed changes select the strongest required artifact. Existing package compatibility, signing, install, and readback requirements remain mandatory.

The selector is advisory and fails closed. It does not approve a release or install. Compare the candidate against the installed image/source revision; a first install or unknown installed baseline requires the flashable image path. The payload path still checks ROS package versions against the target image before transfer.

## Tasks

### Task 1: Add classifier tests

**Files:**
- Create: `test/test_pinky_release_impact.py`
- Create: `deploy/robot/pinky_pro/release/artifact_impact.py`

**Steps:**
1. Write tests for docs-only/no-artifact, ROS-source/native-payload, OS/image, mixed-impact precedence, simulator/Site/OMX exclusion, unknown-path HOLD, and a real `git diff` between two temporary commits.
2. Run the focused tests and confirm they fail because the selector does not exist.
3. Implement a pure path classifier plus a CLI that reads changed paths from `git diff --name-only --no-renames <base>...<head>`.
4. Run focused tests; JSON output must include selected impact, base/head, changed paths, and per-path reason.

### Task 2: Record D-325 and the execution guidance

**Files:**
- Create: `docs/adr/D-325-pinky-deployment-artifact-selection.md`
- Create: `docs/deployment/pinky-release-artifact-selection.md`
- Create: this plan
- Modify: `docs/reference/ROSY ADR Log.md`
- Modify: `docs/plans/AGENTS.md`
- Modify: `docs/deployment/pinky-pro-first-device-runbook.md` (link to selector and preserve first-install image requirement)
- Modify: `deploy/robot/pinky_pro/release/AGENTS.md`
- Modify: `deploy/progress.md`, `docs/progress.md`, `deploy/logs.md`, `docs/logs.md`

**Steps:**
1. Record D-325 as the scoped artifact-selection rule; do not alter D-225 accepted safety or device gates.
2. Add a short decision table and selector command before the first-device build instructions.
3. Make the payload workflow the normal path for compatible existing devices; reserve full image builds for fresh/unknown baselines or image-layer changes. Keep the selector instructions in a short dedicated runbook.
4. State explicitly that selecting `none` means no robot artifact, not that tests or site deployments are unnecessary.
5. Append dated harness logs and update ADR/plans registries.

### Task 3: Verify and commit

**Commands:**
- `python -m pytest test/test_pinky_release_impact.py test/test_native_payload_workflow.py test/test_image_pipeline.py -q`
- `python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q`
- `python tools/harness/rosy_harness.py lint`
- `python tools/harness/rosy_harness.py generate`
- `git diff --check`

Review the diff to confirm no signing, ARM64, package-compatibility, robot identity, or physical readback gate was removed. Do not dispatch a release workflow or deploy a device in this implementation task.
