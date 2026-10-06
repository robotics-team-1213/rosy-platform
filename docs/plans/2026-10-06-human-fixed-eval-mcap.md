# Human-reviewed fixed evaluation and MCAP provenance implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` only after D-475 is accepted and implementation is authorized. Work in a new topic worktree; this document grants no deployment or gate change.

**Goal:** Produce a separately reviewed, source-proven evaluation version for the existing 225 Pinky frames, then compare the current shadow model against it without mixing evaluation masks into training.

**Architecture:** Reuse the existing Review app and immutable store. Add an MCAP source identity and a verifier that hashes and decodes the same captured bag bytes, reserve evaluation sessions before import, and publish only fully approved indexed masks. Preserve the existing video path and historical evaluation versions. Resolve the historical-version admission question before using D-464's human-label training builder.

**Tech Stack:** Python 3.12, `mcap`/`mcap-ros2-support`, OpenCV, SQLite Review state, immutable store, pytest.

---

## Starting evidence and decision boundary

- D-475 is **Proposed** and records the user's “ADR 초안부터” choice. Implementation, human review, and gate switch need their own authorization. D-464 and D-379 still govern current jobs.
- The model-PC store held 126 frames in `pinky-heldout-20261001` and 99 distinct frames in `rosy26-heldout-20261005`; `rosy26-heldout-wall-role-20261006` repeats the latter 99. Read-only inspection on 2026-10-06 found all three versions lack `capture_group`, `source_video_sha256`, and `video_frame` on every row. Recheck the live store before implementation because this inventory can change.
- `training/review_dataset.py::_eval_inventory` calls this incomplete and `build_dataset` returns HOLD. `review_eval_companion.py` captures D-379 lineage but explicitly reports `eval_decoded_pixels_unverified`; a companion is not an invented video identity or pixel proof.
- Current Review workspace has 38 pending frames, including 18 drafts from two non-evaluation sessions. None is approved. Its training masks must remain separate from the proposed evaluation workspace.
- The user's circular-line rule for the reviewed scene is: the white ring is `lane_line`; its center island is not `drivable`. Document the visual distinction in the evaluation guide without converting model output into ground truth.

## Task 1: Freeze a source and overlap inventory

**2026-10-06 read-only result:** The model PC's three historical manifests contain 324 rows but 225 distinct images (126 Pinky, 99 rosy26); the second rosy26 version repeats the same 99. All source MCAP metadata and bag hashes were inventoried in the model-PC scratch receipt (SHA-256 `17c250ed86788cc786faac1162535e952820cb30173a6f266782eceec685d00d`). None of the 324 saved JPEGs equals the directly decoded MCAP pixels. The 99 rosy26 JPEGs uniquely match OpenCV quality-95 re-encodes of MCAP camera images. The 126 Pinky JPEGs uniquely match quality-95 re-encodes of source MP4 frames, and each MP4 sidecar `log_ns` plus header stamp uniquely resolves to a source MCAP message (MCAP-link receipt SHA-256 `86794734d224c0e475a0a58c607372f90dba2b68a3dcd18179124e91f3a3860b`). Pinky's original `labels.jsonl` bytes referenced by the manifests were not found. Thus historical source lineage is evidenced, but exact raw-pixel equivalence and original Pinky label provenance are unproved. D-464 remains HOLD; a fresh lossless MCAP image review and a non-destructive historical-version admission decision are required before human-label training. The receipt files remain off Git on the model PC. Focused package test: 20 passed, 1 skipped, 0 NEW against `known_failures.py`.

**Lossless review candidate:** The model PC scratch area now has 225 PNGs decoded from the identified MCAP messages and a source-link receipt (SHA-256 `8d91b11031cf27fda2e05eb519ca87aed4134f8845bb85bff1cbac4733d90fcb`). A separate pass verified all PNG byte hashes, decoded pixel hashes, dimensions, and the 100/26/99 per-session counts. These are unlabeled candidates outside the immutable store; no evaluation version or approval was created.

**Files:** `learning/training/perception/dataset/extract.py`, `training/review_eval_package.py`, `test/test_review_eval_package.py`; output receipt under the model-PC data root, never in Git.

1. Read the three current eval manifests and their content hashes, source MCAP `metadata.yaml`, every bag filename and SHA, the original D-379 label JSONL, and the exact extracted image bytes. Fail the audit when any source is absent; do not infer a missing hash from a session name.
2. Record 225 distinct `(session, image)` rows, 3 source sessions, and the duplicated rosy26 version explicitly. Check whether the source MCAP image decoded pixels can reproduce each saved eval image. Report exact matches, known re-encodes, and unknowns separately.
3. Run the existing `test_review_eval_package.py` and `test/known_failures.py` against the saved pytest output. This task publishes no evaluation version.

**Gate:** If any historical version lacks provable origin, keep D-464 human-label admission on HOLD and take the evidence to the D-475 decision review. Do not remove old versions or relax `_active_eval` as a shortcut.

## Task 2: Reserve evaluation sources before import

**Files:** `learning/training/perception/store.py`, `dataset/build.py`, `training/learning_cycle.py`, `training/recording_job.py`, `model/intake.py`, and focused tests for each entry point.

1. Write a failing test that reserves `20261001T130842Z_rosy-pinky-8kcn`, `20261001T131825Z_rosy-pinky-9dfk`, and `20261005T134540Z_rosy_26` with their asserted capture groups. Verify training build, automatic-label job, and intake reject matching session or group before an eval version exists.
2. Add one store-owned, append-only reservation reader/writer with a bounded exact schema. Reject duplicate/conflicting identities and edits to existing reservations. Do not add a second per-command list.
3. Re-run each focused test and `known_failures.py`; commit only this reservation slice. Review `--exclude-eval` callers so a missing reservation read fails closed.

**Gate:** A reservation is an exclusion claim, not evidence that the bag or labels are correct. Removing one requires a separate recorded decision.

## Task 3: Prove MCAP frame identity from captured bytes

**Files:** `learning/training/perception/dataset/extract.py`, a small source-proof module beside it, `test/test_dataset_extract.py`, and a focused new MCAP proof test.

1. Write failing fixtures for sorted numeric bag order, metadata order disagreement, bag/metadata hash mismatch, missing message, two messages with one `log_ns`, changed decoded pixels, and a `.compact` bag without equivalence proof.
2. Reuse `extract.py::_mcap_files` ordering and the installed MCAP decoder. Capture each bag once while hashing its bytes; decode that exact captured snapshot. Bind `(bag SHA list, topic, log_ns, channel ID, message ordinal)` and the camera header stamp to the image digest. Record decoder package/version for compressed messages.
3. Pass only when every selected row resolves to one message and its decoded pixels match the frozen source image. Re-run the focused tests and `known_failures.py`, then commit this proof primitive. Do not manufacture `source_video_sha256` or `video_frame` for MCAP rows.

## Task 4: Extend the Review app in a separate evaluation workspace

**Files:** `dataset/review_ingest.py`, `dataset/review_evidence.py`, the Review app's source-display code, `test/test_review_cycle.py`, `test/test_review_app.py`.

1. Write failing tests for `source_kind: mcap` imports, duplicate `log_ns` disambiguation, replayed import, and refusal to merge an MCAP row with a video/legacy row solely because image pixels match.
2. Extend the existing import and identity schema; preserve the current `video` branch and its prior decisions byte-for-byte. Route MCAP rows around video-only legacy linking. Require a separately configured Review state directory and a frozen class file for evaluation.
3. Put the exact source identity and evidence status in the UI. Start with geometry-only hints; leave unsupported pixels at 255. Do not use learned-model output as an evaluation draft. Run focused Review tests and `known_failures.py`, then commit.

**Human rule:** Full-frame and background review are required. The circular white stripe is `lane_line`; a center island is `floor` when visibly outside the road. Unclear or occluded pixels stay 255 until resolved; a mask with 255 cannot be approved for publication.

## Task 5: Build a separate immutable human evaluation version

**Files:** `dataset/build.py` or a narrow companion builder in `dataset/`, `training/review_eval_companion.py`, `training/review_dataset.py`, `test/test_d379_evalset.py`, `test/test_review_dataset.py`.

1. Write a failing test for a fully approved indexed mask with pinned current Review authority, exact source image/mask bytes, class SHA, source proof, and no 255. Add refusal cases for pending/excluded/stale approval, class mismatch, missing source proof, and training/eval session overlap.
2. Publish `<existing-name>-human/<content-sha>/` using the store's atomic content-addressed path. Record `human_reviewed_eval`, per-frame approval digest, revision, and `source_kind: mcap`; preserve all older eval versions.
3. Extend the evaluation companion verifier to verify the new MCAP lineage independently. Keep historical D-379 companion semantics and a failing test for a new eval version without its MCAP companion. Re-run focused tests and `known_failures.py`, then commit.

**Historical-version gate:** D-464 currently checks **every** store eval version. The Task 1 audit must establish how the three old versions gain complete source/group/frame inventory and the pixel proof required by `review_dataset.py`. If exact proof is impossible, D-475 must decide a non-destructive historical-version policy before human-label training can be admitted. This plan does not silently exempt them.

## Task 6: Review and evaluate real frames on the model PC

1. Revalidate the signed model-PC code SHA, GPU environment fingerprint, bag hashes, current store inventory, and Review service before processing. Use the D-446 job lock and the model PC, not the Windows development PC, for decoding and evaluation work.
2. Import the 225 existing eval frames into the separate workspace only after the three sessions and groups are reserved. A human checks all masks and approves the exact sealed revisions. No automatic approval or copying of the 18 training drafts.
3. Build the human eval version and run the current shadow model's intake against that exact version. Preserve the old-version intake reports as distinct comparisons; report per-class support, IoU, false lane boundaries, drivable center/trajectory error, runtime, and model revision.
4. Keep the model shadow-only. A separate approved gate change may select the new eval version after its champion baseline and junction steering gate are defined. Real motion still requires an on-site observer with immediate E-stop access and a clear area.

## Verification and landing sequence

Use the topic worktree only. For each code slice, run its focused pytest to RED then GREEN, save output under `X:/DevTemp/`, and run `python test/known_failures.py <run.txt>`. Before landing, merge `main` into the topic branch and repeat affected tests; shared `main` accepts only `git merge --ff-only`. Push only under the existing user authorization and after fetch, generated-doc check, pre-push gate, and exact-SHA CI readback. Local tests and a published eval manifest do not prove human label quality, model-PC runtime, device state, or field driving.
