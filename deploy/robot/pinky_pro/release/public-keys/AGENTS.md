<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# public-keys

## Purpose

Committed Ed25519 **public** trust anchors for signed releases. No production key is selected yet.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Pilot trust-anchor status and offline private-key boundary |
| `rosy-release-2026-01.pem` | Ed25519 public key embedded in Pinky Pro pilot images |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- The selected pilot public key is `rosy-release-2026-01.pem`; production ownership
  and rotation still require a separate release decision.
- Never generate a shared signing key in CI or on a robot. Never commit a private key.
- `ROSY_RELEASE_KEY_ID` lives in the GitHub `release` environment (approval required).

### Testing Requirements

Release signing tests live in `../../../test/test_release_signing.py`, not here.

### Common Patterns

One public PEM per key id. Empty directory plus README until a key is chosen.

## Dependencies

### Internal

- `../signing.py`, `docs/deployment/release-signing-key.md`

### External

- OpenSSL 3 Ed25519

<!-- MANUAL: -->
