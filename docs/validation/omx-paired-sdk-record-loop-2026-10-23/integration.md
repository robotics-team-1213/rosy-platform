# Native controller naming and committed SDK replay — 2026-10-23

This is a new integration check after the [RGB recording evidence](result.md); the preceding frozen result is unchanged.

The first landing attempt on commit `9e9c1b348ca9fe3d6527d84565be56db5c5e3e2a` stopped with a new failure in `test_guard_and_binding_construction_stay_inside_allowed_writer_symbols`. Its isolated rerun failed on the branch and passed on main `c4d6f20cbb93d505dc3acc58596094c1342074c9`. The new local manual controller used the name `GuardedMotion`, which D-442's conservative construction check interprets as the sealed motion-authority type. The controller creates no such contract token.

Production commit: `d4a03f554b2b63780f0b7772c37f8c89cdf9b366` renames that internal class and its callers to `NativeJointMotion` in two production and two test files. AST comparison after normalizing that sole identifier found equivalent code. No architecture check, allowlist or authority scope changed. Independent reviewer `review_learning_bounds` found no Important issues or control-behavior changes.

Remote committed regression: **238 passed**, including the unchanged motion-binding construction checks and all six recording/motor suites; **0 NEW**. This restores the architecture check without excluding native files from its scan.

The exact full-loop program from the preceding run was executed again on this production commit. Actual LeRobot 0.4.4 record loop, processors, writer and reload returned **PASS**: one episode, 9 RGB frames, 12 action/state dimensions, every action equal to the actual-sent value, one camera open, all four synthetic buses OFF and disconnected. Serial access stayed denied. This is synthetic hardware evidence with no physical connections, policy training or device/task acceptance.

External evidence is `C:/DevTemp/learning-execution-20261023/paired-actual-sdk-record-loop-v4/out/`, with the complete exact `actual-record-loop-program.py`, result, dataset and health records. Its sibling `paired-actual-sdk-record-loop-v4-bound-evidence.json` binds all ten files by hash and byte length. Full artifact fetch completed; program bytes equal the previous reviewed payload. Replay uses the source checkout root, `deploy/robot/omx` on `PYTHONPATH`, offline HF flags, a fresh `OUT` and the production commit in `SDK_PROBE_SOURCE_REVISION`, as specified in the preceding record.

| File | SHA256 |
|---|---|
| `actual-record-loop-program.py` | sha256: `fb53b400776ba91158f5f39254fef80d09b5295d40666cdd26349d420395998c` |
| `actual-record-loop-result.json` | sha256: `408c6128ea8a617e2c929948cf0943fc54759485c41c45b0a70757f76e18e2a5` |
| `dataset/meta/info.json` | sha256: `c95908563babbf2e8c815157671b21b21dd7898cb05bb9aa89ddcc93ca069519` |
| `dataset/videos/observation.images.front/chunk-000/file-000.mp4` | sha256: `e4773070ae043a5dbce2a652e50f315f0b56ee432627b14f893da5b99cdd30c5` |

CE: 해당 없음 — the role distinction is captured by the class name, unchanged architecture test and this integration evidence. No runtime or field gate moved. The single-arm collection watchdog failure remains unresolved in workspace evidence.
