# Guarded paired OMX native recording — 2026-10-23

The main recording producer previously rejected an explicit two-arm configuration before a native recorder could run. This slice accepts four distinct configured devices, one parent camera owner, and 12 ordered actual-sent actions. It retains passive calibration, fixed-origin seeding, 1 degree/second motion, freshness/following/effort/thermal checks and all-bus cleanup. No physical devices were connected.

- Production commit: `74c4cc61ab45f7048d24395f15eafffc21a8987f`.
- Admission RED commit: `4945057f34b70f6dbd10272b82abfd7d5380cfa5`; valid paired input was rejected as `expected omx_follower`, and child-camera rejection occurred for the wrong reason.
- Independent safety review: `review_learning_bounds`; six-file production fingerprint `8905c95bc29cf277eb781046dc8a406d8b911664cda8dd6c269fbda4afb850dc`, no Important findings. Runtime verification is separate.

## Remote regression

`python tools/remote/remote_pytest.py --log-dir <scratch>/paired-recording-unit-green -- test/test_omx_record_config.py test/test_omx_record_session.py test/test_omx_guarded_native.py test/test_omx_bimanual_native.py test/test_omx_motor_health.py test/test_omx_joint_tune.py`

Observed: **221 passed**, no skips; `test/known_failures.py` reported **0 NEW**. Tests use register-memory buses and cameras. They cover paired preparation before enabling either arm, actual-sent action labels, interrupts, per-bus cleanup despite a failed bus, seeded readback, freshness, sustained effort, thermal faults and logging failure containment. They do not establish real SDK record-loop or device behavior.

Seven mutations independently changed fixed-origin seed tolerance, following-error bound, all-bus OFF attempts, actual action labels, concrete child normalization, parent-only camera admission and distinct device admission. Each altered file was read back and hashed before the selected test returned an assertion failure; original bytes were restored in `finally`. The restored complete suite returned **221 passed**. Evidence is `paired-recording-mutation-proof-v2/out/{mutation-program.py,mutation-result.json,restored-green.txt}` under the external evidence root's parent. Each mutation has its own failed pytest log. The first `paired-recording-mutation-proof` job failed shell quoting before Python; it is preserved and excluded from the mutation result.

## Actual SDK configuration dispatch

The MODEL-only bounded `remote_sim.py` job used the production commit above with LeRobot **0.4.4**, plus OUT-only `dynamixel-sdk==3.8.4`, `pyserial==3.5` and `scipy==1.15.3`. Synthetic device identities passed the actual recorder validator. Each mode ran in a fresh interpreter through:

`Session.command -> bimanual_native.main -> draccus concrete OMX decode -> official typed entry sentinel`.

Both **record and teleoperate PASS**. The original config bytes were preserved; derived parent choice tags remained and concrete child tags were removed. The sentinel received the official typed config and both concrete follower/leader child types. `serial.Serial` was blocked. `run_native` and the real record/teleoperate loop were replaced with the typed dispatch sentinel: **0 hardware connections, no dataset written, no physical acceptance**.

The earlier raw helper invocation bypassed `Session.command` and failed on concrete child `type` tags. This was an entry-path mismatch in the probe, not evidence that the canonical producer needed a new decoder. Its failed artifacts remain preserved.

Evidence root outside Git: `C:/DevTemp/learning-execution-20261023/paired-recording-canonical-sdk/out/`. `sdk-probe-program.py` contains the complete exact configuration probe; `inner.sh` is only the generic wrapper, not the probe payload. The receipt files are `sdk-probe-result-record.json` and `sdk-probe-result-teleoperate.json`. Replay the preserved program with `--mode record` and `--mode teleoperate`, source checkout on `PYTHONPATH`, `OUT` an empty scratch directory and `SDK_PROBE_SOURCE_REVISION` the production commit. Each mode uses synthetic config only; the deployment host and device authority remain unchanged.

| File | SHA256 |
|---|---|
| `sdk-probe-program.py` | `093b871bacf665f8d793f909e29ed924b3919779b6d6f79a59d41b7a0a751727` |
| `sdk-probe-result-record.json` | `f57b58855d8654ad54e94f68df3bd173e8ebe1bef84f929359cca9cc02181ce5` |
| `sdk-probe-result-teleoperate.json` | `00cdbf15478da4c112f40be04a78b8dc0a00d1fd7941b263edc2efb902c91350` |

## Limits and CE gate

This is producer configuration and synthetic-bus evidence. Actual native SDK recording loops, physical calibration/stop, camera timing, genuine demonstrations and independent learned-policy task success remain unverified. Hub authentication/upload remains deferred by the user. No runtime profile was enabled and no field gate moved.

CE: 해당 없음 — integration and dispatch decisions are recoverable from the implementation, tests and this record; the existing verification lesson applies to the wrong-entry probe. The separate single-arm collection `joint_state_stale` remains unresolved and is recorded in workspace evidence, not as a solved lesson.
