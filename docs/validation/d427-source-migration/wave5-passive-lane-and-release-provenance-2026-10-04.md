# D-427 wave 5: passive lane observation and release provenance follow-up (2026-10-04)

This dated follow-up supplements the frozen named-gate record. Earlier NOT_RUN and failure results remain historical evidence.

## Passive lane camera observation: PASS at host AMD64 scope

The stock `map_v2_fleet_lane.launch.py` at source `1722ca6ec6d7` ran in an isolated AMD64 Docker image. Native Docker exit was 0 after 130.83 seconds. Model `rosy` produced 10 odometry samples and 10 advancing clock observations. Four 320x180 rgb8 frames had consistent step/buffer layout and increasing positive timestamps. Two CAMERA_LINE observations were visible with confidence 1.0 and finite error; the initial non-visible observation remains recorded. Legacy observations did not carry a quality field, so quality.valid and labelled model accuracy are not independently established.

CORE and line_observer were present. The helper published no commands; 16 received simulated Twist messages were zero and none sampled was nonzero. This proves passive observation, not closed-loop lane following, route completion, physical safety, ARM execution, device or field acceptance. Cleanup removed only the exact owned container and left no owned processes. Independent review approved this scope after checking raw outputs, hashes, node/image predicates and 13 negative observer cases.

The container had no network, ports or devices, a read-only root, all capabilities dropped and no-new-privileges. The only added read-write bind mounts were the owned X runtime and fresh X-backed .gz/.rosy directories; the image root remained read-only. Previous failed WSL/container preparations remain preserved.

Evidence under `X:/DevTemp/rosy-d427/resume/`: `docker-gazebo-lane-passive/runtime/{runtime-result.json,lane-result.json,container-inspect.json,lane-launch.txt,lane-model-list.txt,owned-container-cleanup.txt,observer-negative-evidence.json}` and `wave5-passive-lane-actual-independent-review.md`.

## Release ID provenance: existing 035 preserved; next ID provisional

A fresh read-only current-link/manifest query found the primary robot's active directory labelled `2026.10.04-035` with source `81eb173682bd`. The independently signed local 035 candidate has source `1722ca6ec6d7`; manifest, checksum-list and signature bytes differ. These are distinct payloads sharing an ID. Neither was overwritten, relabelled or activated by this follow-up.

The updater's current_release also named 035, but its last successful result named the older 033. Neither that old result nor the current-link readback proves a healthy running 035 process or acceptance of the local candidate. GitHub regular payload releases 035 and 036 were absent at observation time. The secondary robot's current ID was not checked. The next candidate is provisionally `2026.10.04-036`, subject to fresh robot-directory/tag checks and actual robot-use coordination before publication. It must be built and signed from the final verified source; the preserved local 035 is not renamed in place.

Private read-only evidence remains in `wave5-current035-active-metadata-readonly.json`, `wave5-current-canary-readonly-summary.json` and `wave5-release-id-active-collision-current.json`. Public evidence contains no actual addresses, accounts or credentials.

## Full browser result at frozen b657: FAIL preserved

Actual opt-in headless Chromium across all 19 browser files at `b657e806a553` terminated with native exit 1: 314 passed, 1 failed in 2352.15 seconds. The failure occurred in `_open` while waiting for entry-shell data-ready, before the pairing-timeout assertions ran. It does not establish a pairing timeout defect or a passing full browser gate. Follow-up investigation runs the entry module separately without changing production source or existing assertions.

Raw output and classifier are sealed in `browser-journal-final-gates/{pytest.txt,result.json,sealed-terminal.json,known-failures-terminal.txt}`. This source is separate from the signed 1722/035 artifacts. Push, new-source CI, ARM/native+SD and publication remain outstanding.

The separate unchanged entry module follow-up at b657 had 14 passed in 120.32 seconds, native exit 0 (outer 124.62 seconds). This does not replace the full-browser FAIL or establish its initialization root cause.
