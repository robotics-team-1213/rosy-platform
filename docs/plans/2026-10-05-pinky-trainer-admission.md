# Pinky Trainer Admission Implementation Plan

**Goal:** Implement independent D-464 trainer admission without starting a real training job or granting qualification to pending live labels.

**Architecture:** An internal owner-injected review context reconstructs the original sealed export against fresh transport authority, complete source proofs and all active evaluation versions in X scratch. Its reconstructed content must exactly match the stored dataset. The trainer consumes captured immutable dataset/eval snapshots and revalidates authority, original inputs and configuration before Job, GPU, intake and READY. No caller JSON boolean, serialized receipt or builder output grants permission.

**Tech Stack:** Existing Python Store, review_dataset/review_authority, OpenCV source decoding and pytest synthetic video fixtures.

## Implementation sequence

1. Create failing isolated tests in `learning/training/perception/test/test_review_admission.py`: synthetic verified positive stops at fake Job, missing/stale/wrong workspace/highwater/edited authority/source/eval/config rejection before Job/GPU/READY, immutable consumed snapshot and no real publication.
2. Implement `training/review_admission.py`: pinned owner context and reconstruction via read-only Store adapter; captured bytes comparison; bounded transport freshness and previous highwater required; immutable dataset/eval snapshots; final freshness recheck after slow proof capture.
3. Integrate optional owner context into `training/train_job.py`. Default CLI remains fail-closed for indexed inputs. Preserve automatic behaviour. Repeat independent verification at irreversible stage boundaries; training consumes captured dataset, intake uses captured eval/gate bytes. Keep builder admission/qualification false.
4. Run only affected admission/trainer/builder/authority tests with X scratch and compare `test/known_failures.py`. A missing test path or zero collection is not PASS.
5. Existing policy reviewer independently checks the actual candidate. Record source SHA, RED/GREEN, isolated tests and limitations in X evidence. No live labels, approvals, requests, GPU jobs, deployment, activation or motion. Local landing requires the existing explicit merge scope and passing candidate checks.

## Acceptance limits

Actual mask approvals0, incomplete fixed-eval126 rowbinding and legacy group assertions still deny construction/admission. Synthetic acceptance verifies code boundaries only. Named original extraction custodian and matching source folders remain unverified. Whole MP4 hashes prove source bytes availability, not exact input-frame mapping. D-464 governs content construction versus owner admission; no REST or external protocol is introduced.
