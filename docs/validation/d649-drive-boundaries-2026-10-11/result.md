# D-649 Drive responsibility migration

## Implemented source

Branch `refactor/role-folder-boundaries`. Plan `0872890a0`, implementation `8e44a94d8`, move-registry fixture `affac5740`, source guards/guides `177e7faff`.

Moved 80 files: seven complete Base behavior packages to `middleware/control/drive/behaviors` and four legacy ROS entry modules to `middleware/control/drive/runtime`. `moves.json` verifies each before/after Git blob is byte-identical. Existing Python/ROS distribution and import identities, entry points, locks, clocks, maps, data and final command authority remain unchanged.

CORE common Safety/Command, calibration-session lease and camera-fault action eligibility remain CORE. Sensor/localization observation composition remains Perception. Namespace and compatibility initializer repetition is explicitly distinguished from actual behavior source ownership in D-649 and the folder guides.

## Verification

- Independent Safety SOURCE review approved the exact move and installation closure; four moved Safety bodies and public dotted anchors preserved.
- Initial CORE/services/architecture/installed package selection on `8e44a94d8`: 4,498 passed, 13 skipped, five subtests passed; three source-guard failures corrected (two old source paths and XML filename classification). These failures were checked as NEW and were not added to known failures.
- Focused corrected guards plus independent sdist/wheel/installed-package proof on `177e7faff`: 117 passed, zero NEW. Includes source archive extraction outside repository geometry, wheel import from isolated installation, original metadata, one installed implementation and moved development-overlay contents.
- Perception on `8e44a94d8`: 3,028 passed, 112 skipped, 62 subtests passed, zero NEW; isolated distribution proof includes four moved entry modules and original provider/map resource identity.
- Release/model/harness/mover selection: 264 passed with one move-registry fixture failure. After listing the seven new independently reviewed move units, mover suite on `affac5740`: 23 passed, zero NEW.
- Local lint: zero errors; staleness/history warnings retain existing gate states. Pytest ran only through the committed-HEAD remote runner. One initial invocation named a nonexistent test path and collected nothing; it provides no acceptance evidence and was replaced by the actual model release tests.

## Integration and deployment acceptance

Latest-main merge and affected-test recheck completed through `tools/land.py --tests auto`, three rounds, final source `5da31e05cb8965ad40a7c44b4094470d4f138461`. Final round: 8,342 passed / 263 skipped / 30 subtests and Perception 3,028 passed / 112 skipped / 62 subtests; zero NEW in both logs. Image context and exact closure fixes on `33125bf1c` separately passed 45 checks and received independent source approval. Main fast-forward integration and publication completed; pre-push reused the landing records and passed the additional 208 checks.

The first exact CI run `38126423478` failed only the Fleet header browser group: a shared tooltip intercepted a normal inbox click (1 failed / 1,566 passed in that group). The other 13 groups, including ROS colcon/build/node boot, passed. Unsigned site build `38126423462` succeeded but was not signed/applied; staged model sequence 21 has no READY marker. The previous `53c557136957` candidate failed map-label browser CI and was likewise not applied.

Shared tooltip repair `edd25738b1` preserves coordinate-based hover, normal underlying clicks, keyboard focus and peer activation dismissal. Independent source and narrow 811-line size review approved it after the overlapping-described-control regression was strengthened. Exact committed-source remote browser and architecture checks: 56 passed, zero NEW. This evidence does not elevate the pending full CI or runtime gates.

Final source `2891e10061233b1067fd315cdcbad78bdb1b5d46` passed full CI `38128614393` (all 14 test groups and ci-result), unsigned Site build and Android. Signed Site, model sequence 22 and AI deployment completed with exact installed source/process/API readback and map/model/Review data continuity; see [deployment.md](deployment.md). Later documentation commits record that accepted runtime source rather than asserting that those commits are installed.

Offline Pinky robots remain intentionally offline on their existing automatic-update path; no robot motion, E-stop reset or field/ARM64 installation is claimed.
