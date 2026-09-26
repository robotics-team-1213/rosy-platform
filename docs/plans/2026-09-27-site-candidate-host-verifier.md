# Site Candidate Host Verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the Ubuntu site operator prove that the transferred candidate files and the loaded Fleet, Vision, and proxy images match the candidate manifest before enabling the site systemd unit.

**Architecture:** Add a standard-library Python verifier to the packaged site deployment files. It will check the release manifest, deployment-file hashes, image archive and SBOM hashes, and the loaded image IDs and `linux/amd64` identities. It will report integrity/consistency only; the existing runbook must continue to say that these unsigned hashes do not authenticate the publisher.

**Tech Stack:** Python 3.12 standard library, Docker CLI, pytest, Docker Buildx/Scout candidate builder.

---

### Task 1: Define host-verification behavior in tests

**Files:**
- Create: `test/test_site_candidate_verifier.py`
- Test: `deploy/site/verify_candidate.py`

**Steps:**
1. Write a passing-candidate fixture with a manifest, three image records, archive, SBOMs, deployment files, and a fake Docker inspect runner.
2. Add separate cases for changed deployment bytes, archive, SBOM, wrong/missing image ID, wrong platform, and a manifest path that escapes the candidate directory.
3. Run `python -m pytest test/test_site_candidate_verifier.py -q` and confirm collection fails because the verifier does not exist.

### Task 2: Implement the verifier and package it

**Files:**
- Create: `deploy/site/verify_candidate.py`
- Modify: `deploy/site/build_candidate.py`
- Test: `test/test_site_candidate.py`

**Steps:**
1. Implement `verify_candidate(candidate_dir, runner=...)` with bounded manifest validation, safe in-bundle path resolution, SHA-256 checks, exact `fleet`/`vision`/`proxy` records, and Docker inspect checks for image ID, OS, and architecture.
2. Add a CLI that exits nonzero on any mismatch and prints only a concise pass/fail summary without credentials.
3. Add the verifier to `DEPLOY_FILES` and candidate-packaging expectations.
4. Run both focused test files and confirm all pass.

### Task 3: Put verification before host activation

**Files:**
- Modify: `deploy/site/README.md`
- Test: `test/test_site_candidate.py`

**Steps:**
1. Document the exact command to run after `docker image load` and before `systemctl enable --now`.
2. State that the manifest is not signed and hash verification detects mismatch/corruption but not malicious replacement of the bundle and manifest together.
3. State that this verifier does not prove TLS trust, host identity, GPU availability, reboot persistence, phone/CORE connectivity, or field acceptance.
4. Run `docker compose --env-file deploy/site/.env.example -f deploy/site/compose.yaml config --quiet` and the focused tests.

### Task 4: Verify the packaged artifact and integrate

**Files:**
- Candidate: `X:\\DevTemp\\rosy-site-candidate-<commit>` (outside the checkout)

**Steps:**
1. Commit the implementation in this worktree, then build a clean `linux/amd64` candidate from that commit.
2. Run the packaged verifier against the built images and verify all reported hashes/IDs match `release.json`.
3. Run the candidate builder tests and relevant Fleet/overhead regressions.
4. Fast-forward the verified commit into local `main`, preserving unrelated main work. Do not push the 168-commit-ahead main branch or claim Ubuntu/FIELD deployment from local evidence.
