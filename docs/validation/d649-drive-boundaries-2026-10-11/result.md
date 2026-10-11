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

## Remaining acceptance

Latest-main merge, affected-test recheck and fast-forward integration pending. Exact remote CI and signed Site/AI/Model-PC deployment remain an active separate acceptance goal. The previous `53c557136957` candidate failed map-label browser CI and was not signed/applied. Offline Pinky robots remain intentionally offline on their existing automatic-update path; no robot motion, E-stop reset or field/ARM64 installation is claimed.
