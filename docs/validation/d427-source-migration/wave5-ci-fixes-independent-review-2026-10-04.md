# Wave 5 CI compatibility corrections independent review

Verdict: APPROVE the seven additional owned source/test corrections on wave5 base bcf1010b2a1e. No concrete blocker found. This approval includes a deliberate runtime dock-pose refinement change; it is not a rename-only verdict or remote CI/device acceptance. No repository file or peer main was changed by review.

## Independent actual-API verification

Windows host OpenCV 5.0.0: dock tag, map dock marker, map scene, visual tags and CI dependencies suites, 49 passed in 6.32s, exit 0.
WSL Ubuntu /usr/bin/python3 OpenCV 4.6.0: the same four perception suites, 43 passed in 18.62s, exit 0. Used -s to avoid mounted-X FD capture behavior. PYTHONDONTWRITEBYTECODE=1 / -B, no pytest cache, distinct basetemp locations under X:/DevTemp/rosy-d427/resume/review. Actual versions were separately queried. git diff --check passed.

These are independent executions, not copies of owner results. Owner reports 52 current passes including additional CI/inventory checks and 43 legacy passes; full legacy perception and architecture/guards remain running and were not represented as complete here.

## CI source-discovery correction

colcon --packages-skip gz_sim replaces creation of a source COLCON_IGNORE. It preserves the existing intentional no-Gazebo build scope while leaving gz_sim discoverable to source inventory checks. Manifest roots, normal build/install/log locations and all other build options are unchanged. The focused regression requires the exact skip and rejects the old touch. No package-name whitelist, inventory count, failure waiver or test gate is relaxed. The folder-package-name test changes only a comment pointing to the current ownership manifest.

## ArUco API compatibility and deterministic fixtures

World builder selects generateImageMarker when available and drawMarker on actual older ArUco. Dictionary, tag ID, output dimensions, padding and pixels remain checked. Visual-tag test uses the already-existing dock_scene.marker_image dual-API helper. Map test uses ArucoDetector when available and the legacy free detectMarkers otherwise, with the same image/ID/quiet-zone/equality checks. These are actual supported API branches, not skipping the old version. No pose tolerance, render fixture, camera geometry, sampling, tag ID or assertion was weakened.

Initial actual4.6 RED evidence shows four missing-API failures plus one off-axis pose failure. The intermediate API-only result retains just that pose failure, separating the API issue from numeric refinement. Final four-suite actual4.6 run independently passed.

## Explicit corner window: behavior and causality

The only detector runtime change sets cornerRefinementWinSize=2 after the existing subpixel method selection. It preserves modern/legacy parameter creation and detector dispatch, unknown/absent tag rejection, solvePnP method, frame/extrinsic conversion, confidence and output contract. It improves corner location rather than changing pose acceptance tolerances or authorizing motion.

Independent parsing of the owner's all-seven-pose window sweep confirms:
- OpenCV4.6 window5 max errors: x5.363mm, y0.227mm, yaw1.304 degrees.
- OpenCV4.6 window2: x4.113mm, y0.237mm, yaw0.486 degrees.
- OpenCV5 window2 and window5 are identical over these seven fixtures: x4.113mm, y0.237mm, yaw0.486 degrees.

This isolates the refinement parameter as the numerical cause within the supplied fixture envelope. The smaller window keeps local corner fitting away from nearby inner marker structure in the small oblique-tag case. The modern adaptive-cap explanation is consistent with the observed identical corners; source/fixture evidence alone should not be presented as a full proof of OpenCV internal implementation across releases.

Important scope: fixed 2px is an actual production behavior change on 4.6. Modern equivalence is shown for the existing seven poses, not every tag scale, blur, lighting, lens distortion or noise condition. Reducing the half-window could change precision/robustness for larger or noisier real markers. Existing mounted/unmounted, off-axis, flipped-solution, lost-tag and fresh-process-import tests pass in both actual versions, providing bounded source/host confidence. Physical camera/dock commissioning remains NOT_RUN; do not describe this as worldwide behavior equivalence or DEVICE acceptance. Keep this compatibility/pose fix explicit in commit/proof instead of folding it into a rename-only claim.

## Ownership and remaining validation

Current HEAD remains the owned wave5 base bcf1010b2. The seven additional paths are separate from previously reviewed guide/manifest/literalguard/adoption changes. Peer shared main advancement was not integrated or edited. No new agents, real device commands, installed-directory mutation, fixture/tolerance relaxation or waiver occurred in this review.

Final proof/log additions, full legacy perception, architecture/guard outcomes, final committed SHA, enforced push gate and remote CI are subsequent evidence. Actual ARM64 native payload/SD/runtime, DEVICE and FIELD acceptance remain separate. No existing green on the prior pushed candidate substitutes for those stages.

## Reviewed worktree fingerprints

- .github/workflows/ci.yml: SHA256 1fa50f0d7603baa9cf3f3f2eab3247398f0b96e73012326114296cc014b4d60c
- test/test_ci_dependencies.py: SHA256 ef89307282f070e50c118b6d467541eb03bdb0e4f42a64ae97b150c645c7c00d
- test/architecture/test_folder_package_names.py: SHA256 8edf5d7255303595f1b5f9d4404244bda9f6d0b7b523d789bcfc63fac7dbef9f
- middleware/perception/map/map_v2_fleet/scripts/build_world.py: SHA256 8f054829b7749ed3ab32bf7fb089eb969eaf6423223fad7b8d2653fb0a46180c
- middleware/perception/test/test_visual_tags.py: SHA256 7ab812664bf31711a490e9691b7a61d96c8ebdac240d1803ba7d70f5cbe27681
- middleware/perception/test/test_map_v2_fleet_dock_marker.py: SHA256 e52dde6c25df68aacaceb06008845bf29ac187dcedd622e9f3f26ff31a3d51d3
- middleware/perception/control/sensing/dock_tag.py: SHA256 a1cf95eea7904c2a13eca10ba0ad9522f97c120b371f082c7ee0a3fa8c09e2f2
