# D-310 CORE ARM64 image comparison — 2026-09-27

## Fixed inputs

| Image | Clean source revision | OCI manifest |
|---|---|---|
| Pre-move CORE closure fix | `b0609dc68ed727a1ed15e57e7c3e029001ab0a8f` | `sha256:4eeccfd3105bee2e5b4ecf7326af292b8d3eb41dcc372b6d1915207d2fba4e29` |
| D-310 combined source candidate | `a72d04061f7059d47660a5306f9ad314a5c04404` | `sha256:ff04a462970db63f50fffa6f89c02243e3bd2556d044260021b5c5dc797b7c45` |

Both builds used the same pinned ARM64 ROS Jazzy base image and Docker build inputs except the source revisions above. The first fixes the missing CORE package closure before the folder move. The second includes the eight-package source move and that closure fix. They are local OCI evidence, not signed or deployed images.

## Actual image readback

| Check | Pre-move fix | Combined candidate |
|---|---|---|
| ARM64 CORE Docker build | exit 0 | exit 0 |
| Final image probe (`core.main`, `core.node`, API app, installed dashboard/web assets and `/dashboard` route) | pass | pass |
| Installed overlay ament package set | `core, core_api_web, core_common, core_events, core_features, dashboard, interfaces, pinky_pro, web_common` | exact same 9 packages |
| `ros2 pkg prefix pinky_pro` | `/opt/rosy_ws/install` | `/opt/rosy_ws/install` |
| Installed `lib/core/core` | executable | executable |
| Installed `share/pinky_pro/config/profile.yaml` SHA-256 | `4742621476b7d52e141ba62219a917837b6856c987c02c78ecad5ca74be006e0` | same |
| Installed `share/pinky_pro/config/capabilities.yaml` SHA-256 | `3ec6d3f807f979b0bc4dbddce04396116574789b472dee2c9d9a106dfc105627` | same |

This supports **CORE ARTIFACT equivalence for these two source revisions**. The package set contains neither Pinky hardware drivers nor the OMX adapter. The manifest digests differ as expected for distinct source revisions; digest equality is not the equivalence criterion.

Raw logs: `X:\DevTemp\rosy-d310-core-closure-fix-b060.log`, `rosy-d310-core-inventory-b060.log`, `rosy-d310-core-profile-readback-b060.log`, `rosy-d310-core-combined-a72d.log`, `rosy-d310-core-combined-inventory-a72d.log`, and `rosy-d310-core-profile-readback-a72d.log`.

## Remaining D-310 gates

- The IO pre-move and combined ARM64 image install closures must be compared separately. The first IO attempt stopped during large apt installation, so no baseline was asserted from it.
- Native payload still needs a clean checkout of the candidate SHA on a real aarch64/Jazzy builder, with source revision, full installed ament inventory, required packages, share files, and executable readback.
- SOURCE/LOCAL and CORE image evidence do not establish whole-image `ARTIFACT_EQUIVALENT`, DEVICE stop/readback, or FIELD acceptance. D-310 remains Proposed, and the product folder move remains out of local `main`.
