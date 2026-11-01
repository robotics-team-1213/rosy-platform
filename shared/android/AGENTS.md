<!-- Parent: ../AGENTS.md -->

# android

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-31

## Purpose

Kotlin sources that every ROSY Android app compiles in place (D-939). No Gradle module, no published library: each app adds the folder with `sourceSets.main.java.srcDir`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `peer/` | Peer approval building blocks (D-456, D-483): `PeerProof` signatures, `PeerTls` first-contact CA pinning, `AndroidPeerIdentity` Keystore key per app |

## For AI Agents

### Working In This Directory

- A change here ships in Rosy Pilot and Rosy Cam together. Build and unit-test both apps.
- App-specific sessions and vaults stay in the app. Put only what both apps use unchanged here.
- `AndroidPeerIdentity(context, app)` derives the Keystore alias, marker file and client id prefix from `app`. Changing that derivation drops every existing pairing.
- Never copy a file from here into an app. `test/architecture/test_app_shared_sources.py` fails on redeclared types and on renamed copies across apps.

### Testing Requirements

```bash
python -m pytest test/architecture/test_app_shared_sources.py -q
```

Then each app's `:app:testDebugUnitTest` (`PeerCryptoTest`, `CameraProofTest` cover this code with each app's golden vectors).
