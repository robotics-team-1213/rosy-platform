# Pinky Character Expression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Track the steps below; use the repository remote test runner for every pytest invocation.

**Goal:** Implement D-922's coordinated greeting, gaze, sleepy idle and rear LED behavior.

**Architecture:** A ROS-free CORE expression policy owns observation history and output intent. The bridge adapts validated detections and applies the same intent to the existing face service, local LCD hand-over and LED service. The single native LCD owner renders directional pupils using the existing character drawing code and retains all higher-priority cards and power rules.

**Tech Stack:** Python 3.12, existing pydantic detection contracts, Pillow renderer, existing ROS services and native LCD owner. No new dependency.

**Spec:** [Character design](2026-10-30-pinky-character-expression-design.md), [D-922](../adr/D-922-pinky-calm-curious-character-expression.md).

## Global Constraints

- Existing 8 face names, 320×240, no blinking; gaze ±6 px horizontally, 0 vertically, 0.4 s transition.
- Person confidence ≥0.5 and freshness ≤0.3 s; qualify continuous observations for 0.5 s.
- Greeting 1.5 s idle / 0.6 s working, global interval 5 s; re-greet only on a new return after 10 s confirmed absence and 60 s cooldown.
- Idle rest at 300 s; higher-priority cards, failure, missing observations and safety state take precedence.
- Use the D-922 RGB table and existing 5 Hz LED application; never set global LED brightness or publish motion commands.
- Committed revisions run on remote test PCs. No local pytest. Preserve exact RED and GREEN evidence.

## Review Focus

- Clock translation, stale packets, replayed sequence numbers and reconnect baselines must not cause greetings.
- Missing/duplicate/reused track IDs and mode changes must not create per-person identity or delayed greetings.
- A preempting card or safety state must cancel reactions and prevent replay on return.
- Failed/unready face and LED services must receive current intent when they recover.
- Native gaze rendering must affect pupils rather than translate the whole face, preserve cards and keep installed resources available.

## Task 1 — Local face intent hand-over

Files: `contracts/foundation/core_common/face_screen.py`, existing foundation face-screen tests and gateway `test_face_inputs.py`.

Interface: optional `expression` object with bounded numeric `gaze_x` and boolean `resting`, validated by the existing local hand-over reader. Missing/invalid optional input becomes neutral and never invalidates a good safety card. `display.face_inputs_payload` writes the matching optional object.

- [x] Add RED tests for bounded gaze, malformed values, legacy payload compatibility, stale hand-over and card precedence.
- [x] Commit and run focused remote RED tests.
- [x] Implement the smallest matching reader/writer addition; commit contract support independently of behavior.
- [x] Run focused remote GREEN tests. Keep FULL selection for the final branch because foundation changes trigger it.

## Task 2 — Expression policy and bridge

Files: new gateway `core/bridge/expression_policy.py` (placed in `core`, not `core_features`, which is at its 10,000-line unit limit) and `core/bridge/expression.py`, bridge `ros_bridge.py`, `reconcile.py`, policy tests under services/test, bridge integration tests under gateway/test and existing face-input/reconcile tests.

Interfaces: `ExpressionPolicy.observe(packet, source_now, now, known_revision)` validates and snapshots evidence; `update(mode, nav_state, now, suspended, moving)` returns face, gaze, resting and RGB intent. A small bridge controller owns this policy and routes one intent to existing outputs. The safety advisory consumer remains independent.

- [x] Add RED behavioral tests for multi-person selection, group fallback, continuous presence, early return discard, replay/loss, 300-second rest, unsafe preemption, actual-motion vs mode, RGB bounds and retries.
- [x] Commit and run remote RED.
- [x] Implement temporal state with bounded encounter memory and locking; wire the existing detection callback, state tick, hand-over and LED arbitration without adding a subscriber or timer.
- [x] Run remote GREEN for policy, bridge integration, emotion mapping, face inputs and LED priority. Check every caller before changing shared reconcile signatures.

## Task 3 — Native face rendering

Files: move reusable drawing into `middleware/robot_ui/face/emotion/character.py`; retain `make_faces.py` as asset-generator entrypoint; extract `native/face_frames.py` to respect the existing native-owner size ceiling; update native `rosy-face.py`; extend installed-renderer/native tests.

Interfaces: `character.frame(name, phase, gaze_x=None, resting=False)` preserves default asset generation; optional gaze replaces pupil offsets only. Native `FaceFrames` gets an optional renderer callback and validated expression while GIF fallback stays available.

- [x] Add RED tests showing directional pupil movement, unchanged mouth/eye placement, sleepy frame geometry and native card/power preemption.
- [x] Commit and run remote RED.
- [x] Extract the existing drawing without regenerating binary assets; render on the existing native face tick with bounded smooth gaze/rest interpolation and existing FPS budget.
- [x] Run GREEN with installed-package, asset, native-face, hand-over and policy suites.

## Task 4 — Evidence and completion

- [x] Append owning module logs and generate harness records. Keep DEVICE/FIELD gates unchanged.
- [x] Run lint and the final affected selection, including FULL when required; compare every report with known failures.
- [x] Request a fresh whole-change review of producer→policy→hand-over→renderer and LED priority; fix important findings with reproducing tests.
- [x] Record actual tested revision and results in internal records and Confluence. Distinguish implementation/host tests from device acceptance. Do not deploy, land or push without the corresponding authorization.

## Verification receipt

Final tested source `939c3f58924579c225f18a5c86e99b98c4ca0c8c`: FULL 27 invocations, 38,255 passed, 2,804 skipped, final NEW 0/known 0/flaky 2, runner exit 0. The two previously quarantined G1 timing failures passed the official unchanged-source solo rerun; original failures remain recorded. Clean main timing comparison: 12 passed, not MAIN-RED. Counts overlap across invocations. Exact report hashes and limits are in the [validation record](../validation/pinky-character-expression-2026-10-30/result.md). DEVICE/FIELD, deployment, landing and push remain unperformed.
