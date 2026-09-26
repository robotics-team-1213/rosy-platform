# Site Candidate Signing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Authenticate the publisher of every Ubuntu site candidate before host activation while keeping signing private keys off build and site hosts.

**Architecture:** The normal builder continues producing a candidate with `release.json`. An offline operator signs the exact manifest bytes with Ed25519 and a separate site key; the key ID is domain-bound into the signature. The Ubuntu host has a reviewed verifier, signing module, public key, and key ID installed outside the candidate. It verifies signature and bundle contents before Docker loads images, then verifies loaded image IDs before systemd activation.

**Tech Stack:** Python 3 standard library, OpenSSL 3 Ed25519, Docker CLI, pytest.

---

### Task 1: Specify and test the detached signature envelope

**Files:**
- Create: `deploy/site/candidate_signing.py`
- Create: `test/test_site_candidate_signing.py`

1. Define a strict versioned JSON envelope with key ID and base64 signature.
2. Sign `domain separator + key ID + exact release.json bytes` with OpenSSL Ed25519.
3. Verify the signature against an explicit trusted key ID and public-key path; reject malformed, missing, wrong-key, and modified-manifest inputs.
4. Use only ephemeral test keys under `X:\DevTemp` for cryptographic tests.

### Task 2: Require signature before candidate consistency checks

**Files:**
- Modify: `deploy/site/verify_candidate.py`
- Modify: `test/test_site_candidate_verifier.py`

1. Verify the detached signature before parsing trusted manifest values.
2. Require explicit `--trusted-key-id` and `--trusted-public-key` CLI inputs; add a signature-only mode for pre-load checks.
3. Keep unsigned content verification private to the signer; public host verification must fail closed without a trusted signature.
4. Preserve existing hash, SBOM, archive, image ID, platform, and safe-path checks.

### Task 3: Add the offline signing command and package it

**Files:**
- Create: `deploy/site/sign_candidate.py`
- Modify: `deploy/site/build_candidate.py`
- Modify: `test/test_site_candidate.py`
- Modify: `deploy/site/README.md`

1. Verify unsigned candidate contents before signing, then write the detached signature without overwriting an existing one.
2. Add signer/verifier modules to the packaged deployment-file inventory and test expectations.
3. Document the separated build, offline-sign, transfer, trusted-host-key provision, and host-verify steps. State that the site key is separate from Pinky runtime release keys and must be enrolled independently.

### Task 4: Record the trust decision and verify the packaged path

**Files:**
- Create: `docs/adr/D-301-site-candidate-signatures.md`
- Modify: `docs/reference/ROSY ADR Log.md`
- Modify: this implementation plan

Run the focused candidate/signature tests, document-placement contract, and Compose config check. Build one clean `linux/amd64` candidate from the signed-verifier source, sign it only with an ephemeral LOCAL test key under `X:\DevTemp`, and verify the packaged candidate using that key. Do not create or commit a production private key, enroll a host trust anchor, deploy, or infer field acceptance from this LOCAL proof.

## Execution checkpoint (2026-09-27)

- Tasks 1–3 implemented; D-301 accepted for the source contract. Added exact-manifest-byte reuse between signature verification and parsing, plus a second content check immediately before the offline signer writes the signature.
- Focused tests: 27 passed (`test_site_candidate.py`, `test_site_candidate_verifier.py`, `test_site_candidate_signing.py`). Tests used a fresh `X:\DevTemp` basetemp and throwaway keys.
- Completed verification: document-placement + harness contract checks (84 passed), harness lint (0 errors, 19 repository evidence-freshness warnings), Compose config validation, changed-file flake8, and the clean packaged Docker build/sign/verify loop.
- Packaged LOCAL candidate: source commit `3b983c31ee0579208229e9f768be8c7acd340cd2`; archive SHA-256 `30d0c64e7398517394cefb4ee52e8d532ca28ef62233670dfbc8db6bce9126c8`; all three `linux/amd64` image IDs matched after `docker image load`. A throwaway test key under `X:\DevTemp` signed it; the private key is not part of the candidate or repository.
- No site production key, target Ubuntu trust enrollment, remote activation, robot command, or field test was performed.
