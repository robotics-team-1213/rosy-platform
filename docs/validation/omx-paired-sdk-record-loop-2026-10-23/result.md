# Paired native SDK recording loop — 2026-10-23

This follows the [typed dispatch and synthetic-bus record](../omx-paired-recording-2026-10-23/result.md). It runs the actual LeRobot 0.4.4 `record.__wrapped__`, `record_loop`, processor aggregation, dataset writer and dataset reload with the production native guard. Only hardware factories and keyboard input are replaced. It does not establish physical acceptance or learned-policy quality.

Production commit: `625329a2e07e8db2fbe7b69b334b7e25e4fa43c3`. The earlier native recording implementation remains commit `74c4cc61ab45f7048d24395f15eafffc21a8987f`; the follow-up adds strict RGB admission. Independent reviewer `review_learning_bounds` found no Important issues in both production changes.

## A real-loop finding that stub dispatch missed

The first full-loop probe patched an SDK utility rather than its already-exported factory. Its serial deny hook stopped the execution before a port could open; that failure is excluded from product compatibility claims.

The corrected synthetic-hardware probe used `dataset.video=false`, expecting still-image storage. The official SDK recorder instead produced one episode with 9 frames and 12 actions but **no image feature**. Its `aggregate_pipeline_dataset_features()` explicitly drops image features when `use_videos` is false; this differs from directly calling `LeRobotDataset.create(use_videos=False)`. The earlier dispatch sentinel did not execute this aggregation. Native config admission accepted that setting, despite requiring a camera, so a caller could prepare a recording without RGB learning input.

The follow-up validator accepts the omitted SDK default or boolean `true` and rejects false, null, numeric and string values before device access. Test commit `8a1738ed4c` returned **8 expected failures** before the fix. The fixed six-suite regression returned **231 passed, no skips, 0 NEW**. The test-only RED and green provide mutation evidence for the new admission boundary. Earlier seven guard mutations remain recorded in the preceding validation entry.

## Actual video-enabled loop

The MODEL-only bounded `remote_sim.py` execution used the production commit above, the separate LeRobot 0.4.4 environment, and OUT-only `dynamixel-sdk==3.8.4`, `pyserial==3.5`, `scipy==1.15.3`. `serial.Serial` was denied throughout. Four source-pinned synthetic bus fixtures, one 128×128 RGB camera and headless keyboard events replaced hardware; the actual native guard, SDK record loop, processors and writer ran.

Observed **PASS**:

- One episode, **9 frames**, **12 action and state dimensions**, one parent camera open.
- Actual camera video encoded and reloaded as `observation.images.front`, tensor shape `(3,128,128)`.
- Every reloaded action matched the captured actual-sent action; desired and actual actions differed, so the comparison exercised command labeling.
- All four buses closed with torque OFF and the camera disconnected after recording.
- Hub upload disabled and offline mode set; no physical connection, policy training or physical task-success claim.

External evidence: `C:/DevTemp/learning-execution-20261023/paired-actual-sdk-record-loop-v3/out/`. The sibling `paired-actual-sdk-record-loop-v3-bound-evidence.json` binds the remote result and all ten program/dataset/health files by SHA256 and byte length. The saved `actual-record-loop-program.py` is the full exact payload; `inner.sh` is only the generic remote wrapper. Run the saved program from the source checkout root with `deploy/robot/omx` on `PYTHONPATH`, `HF_HUB_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, an empty `OUT` and `SDK_PROBE_SOURCE_REVISION` set to the production commit. It derives synthetic config, blocks serial access and runs one bounded episode. Preserve a failed output rather than reusing its directory.

| File relative to OUT | SHA256 |
|---|---|
| `actual-record-loop-program.py` | `fb53b400776ba91158f5f39254fef80d09b5295d40666cdd26349d420395998c` |
| `actual-record-loop-result.json` | `6a991cc5571c2b64e6fb825dd61092d5aed22bd4cf4d075ad0ae0eeeac648643` |
| `dataset/meta/info.json` | `c95908563babbf2e8c815157671b21b21dd7898cb05bb9aa89ddcc93ca069519` |
| `dataset/data/chunk-000/file-000.parquet` | `1ba7187794e4f50d17253fcc6d61512d7a6c2f474d22f421a197b0316f5b853f` |
| `dataset/videos/observation.images.front/chunk-000/file-000.mp4` | `e4773070ae043a5dbce2a652e50f315f0b56ee432627b14f893da5b99cdd30c5` |

The failed first and image-free second probes remain in `paired-actual-sdk-record-loop` and `paired-actual-sdk-record-loop-v2`; no failed dataset is admitted for learning. The latter's metadata SHA256 is `ea846a48696f1299a235befe62a400a49a614e1af5f364cb26e173150b0d6e3e`. Headless `pynput` warnings are expected with injected keyboard events; they are not physical keyboard/stop acceptance.

CE: 해당 없음 — the SDK aggregation distinction is preserved in the guard comment, regression and this evidence record; those artifacts recover the decision. The separate single-arm collection state delay remains unresolved and is not a solved lesson. Actual calibration, stop, timing under device load, human demonstrations and independent policy evaluation remain required.
