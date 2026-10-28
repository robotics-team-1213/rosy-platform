# Selected-frame cadence in independent OMX SIM truth

The successful teacher run from commit `a3a75e6fd2`, native suffix `3a2891da44b8`, records the unchanged 10Hz camera at 5fps with original source timestamps. The old proof validator rejected it solely because its fixed-rig check required 10fps. The original evidence and rejected model-PC run remain preserved; no source manifest or frame timestamps were changed.

The contract now admits exactly 5fps and 10fps recordings. Existing source-row cadence checks, source hashes, pinned camera/world geometry, historical state/action correspondence, accepted/terminal command evidence, gripper freshness and independent task-success recalculation remain mandatory. This changes the accepted recorded cadence, without adding a schema field or an execution authority.

## Regression evidence

All logs are under the external root `C:/DevTemp/learning-execution-20261023/`.

- Commit `da9a1818b9`, `truth-cadence-red/run-1.txt`: one expected 5fps round-trip failure, 19 passed.
- Commit `6760840ded`, `truth-cadence-green/run-1.txt`: 67 passed, zero new failures. The tests cover 5fps and 10fps proof round trips with original bytes, rejection of 5fps frames relabeled as 10fps, and rejection of another valid recorded rate outside this fixed-rig contract.
- Independent read-only contract review through `6760840ded` found no Important findings. Review does not replace runtime evidence.

## Actual source verification

The producer source remains `a3a75e6fd2`; the independent model-PC validation source is `6760840ded`. These are distinct identities. The validator first rechecked the fetched archive receipt and SHA-256, then rebuilt task truth from the original execution evidence and exported/re-read every RGB frame using the actual pinned LeRobot environment.

`sampled-teacher-truth-model-cadence/run.txt` exited zero, and `out/result.json` reports PASS: all 1,587 frames verified, all 377 recorded commands represented, and 723 training examples whose full four-target chunks fit the 0.035rad action head. The original teacher trial itself exited zero with PASS and cleanup true. Evidence includes 135 verified bounded contact-hold commands. The model environment was not modified; the required SciPy wheel was scoped to that validation run's output directory.

This validates one assisted-SIM teacher episode and its learning intake. Collection of the full independently split cohort, training/reload, independent learned-policy trials, Hub delivery and physical acceptance remain unfinished. No label approval, operating authority or learned-policy success is inferred from this result.

CE: no additional lesson beyond the existing bounded-ACT lesson. The contract line, negative cadence regressions and source-specific runtime evidence express this compatibility correction directly.
