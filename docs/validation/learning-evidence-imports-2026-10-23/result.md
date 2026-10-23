# Isolated learning evidence imports

The expanded teacher-capture landing selection exposed two import failures on main. Source commit `299549da00` reproduced both through the remote runner: two failed, four passed and two optional-dependency skips. Logs are under the external root `C:/DevTemp/learning-execution-20261023/main-import-failures/`.

- Loading `fleet_join.py` by file location failed to find `policy_output_paths`. The script now adds its resolved source directory alongside its existing contract import roots before importing that sibling.
- Actual signed, mapped perception import loaded OMX review code, which requires `omx_output_paths`. The helper was absent from the exact signed payload allowlist. Adding its exact path also makes it a required dependency whenever OMX review is included; signature and activation checks remain unchanged.

At commit `df2a11ca04`, the original parent-chain and actual signed-handoff regressions, Fleet join cases and model-code updater suite passed: 168 passed, two optional-dependency skips, zero new failures. Logs are under `import-green/` in the same external root. Independent read-only review found no Important findings. The signed handoff uses temporary keys and scoped idle/GPU fixtures; it does not install code on an operating service.

The initial landing log used incorrectly prefixed node IDs for its isolated retry and main comparison, so those exit-four attempts did not establish a main verdict. The explicit remote run above used the real test paths and reproduced both failures on main.

CE: no additional lesson. The three changed lines and existing execution regressions directly express the dependency and bootstrap requirements; the source-specific record preserves the failed landing diagnosis. No physical acceptance, deployment or GitHub push is claimed.
