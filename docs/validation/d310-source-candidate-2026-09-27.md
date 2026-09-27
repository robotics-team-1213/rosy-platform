# D-310 source candidate: 2026-09-27

## Scope and revision

- Candidate commit: `e8878189ba320749b335a510c648edd4b30b944e` (`feat/d310-source-candidate`).
- Base commit: `f286e298e9fa71a3954cc4975f618811c24daa6c`.
- The candidate moves eight existing ROS packages into the Pinky Pro and OMX product folders or `src/drivers/imu_bno055`. Their ROS package names, imports, and console entry points remain unchanged. It updates live path consumers, Docker COPY paths, native payload inputs, CI, harness, and layout tests.
- This is an isolated `SOURCE_CANDIDATE`. The local `main` source layout and D-310 Proposed status have not changed.

## Evidence

| Gate | Result | Scope |
|---|---|---|
| Windows root `python -m pytest test/ -q -p no:cacheprovider` | 2,715 passed, 158 skipped, 24 warnings | Candidate source; warnings are existing invalid escape and stale/uncommitted harness metadata warnings. |
| Moved package suites | Pinky 450 passed/6 skipped; OMX 48 passed/3 skipped; IMU 4 passed/10 skipped | Separate invocations prevent duplicate test basename collisions. |
| CORE/contracts/HMI and sensing suites | 1,795 passed/16 skipped; 1,660 passed/78 skipped | Separate invocations for duplicate test basenames. |
| WSL ROS 2 Jazzy `colcon build --base-paths src` | 24 packages finished | Build, install, and log roots on `X:\DevTemp\d310-colcon`. Source XML names and installed ament index names matched (24 each). |
| Installed ROS checks | Passed | `ros2 pkg prefix` for moved packages and CORE; moved share/config/launch, CORE and OMX imports checked in the installed overlay. |
| Harness | 0 errors, 19 metadata warnings | `python tools/harness/rosy_harness.py lint`; generated module indexes refreshed. |
| Path audit | No live old package path consumers found | Historical ADR/log text and explicit negative migration tests excluded. |

The earlier baseline root suite had one intermittent SD writer contract failure; its isolated rerun passed. The candidate root suite above passed in full. These are host and ROS build results, not a robot runtime or physical stop readback.

## Artifact and integration holds

- The pre-move CORE ARM64 image built, but its runtime import probe failed with `ModuleNotFoundError: No module named 'core_common'`. This predates the source move. A separate fix candidate is `fix/d310-core-baseline` at commit `c31a67696bb5a97495fe8356953a175e936da945`; its ARM64 rebuild/probe is still pending. The D-310 candidate must incorporate that fix and revalidate its combined Docker package closure before integration.
- The pre-move IO ARM64 baseline and a clean native aarch64/Jazzy payload baseline were not completed. IO apt installation was stopped after revealing a large dependency closure; no equivalent IO artifact was asserted. The available WSL host is x86_64 and does not satisfy native payload provenance requirements.
- Consequently `ARTIFACT_EQUIVALENT`, DEVICE, and FIELD remain HOLD. Do not merge this source layout into `main` under the D-310 gate or mark D-310 Accepted based on these results.

Raw Docker logs and WSL build material are under `X:\DevTemp\` (`rosy-d310-core-baseline.log`, `rosy-d310-core-import-probe.log`, `rosy-d310-io-baseline.log`, and `d310-colcon`). X: material is local evidence, not a published artifact.

## Subsequent source-only decision

The HOLD above describes this first candidate snapshot. The pre-move CORE and IO closure faults were repaired and [CORE](d310-core-artifact-comparison-2026-09-27.md) and [IO](d310-io-artifact-comparison-2026-09-27.md) ARM64 OCI comparisons later passed. The user then explicitly requested the local source merge. D-310 now accepts only the eight-package source placement; native aarch64/Jazzy payload equivalence, DEVICE, and FIELD remain HOLD.
