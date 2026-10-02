# cam

Rosy Cam (D-377 id `cam`; 천장 카메라 앱): the Android phone app that streams ceiling-camera JPEG frames to Rosy Vision over `rosy-overhead/1`. Kotlin + CameraX + OkHttp. Not a ROS package (`COLCON_IGNORE`); Gradle only.

Moved out of `src/site/overhead/android` on 2026-09-30 (D-374 stage 1), then renamed from `src/site/ceiling_camera` the same day (D-377). History before the split lives in `src/site/vision/logs.md`.

## Key Files

| File | Description |
|------|-------------|
| `settings.gradle.kts` | `rootProject.name = "rosy-cam"`, one module `:app` |
| `app/build.gradle.kts` | `namespace`/`applicationId` `io.github.livsbittt.rosy.cam`; JVM test system properties for the shared vectors and D-370 icon SVGs |
| `app/src/main/AndroidManifest.xml` | Registers the `rosyov://` pairing link (never changes, D-374 3항) |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `app/` | Gradle module `:app`: manifest, resources, code, tests (see `app/AGENTS.md`) |
| `app/src/main/java/io/github/livsbittt/rosy/cam/` (see its `AGENTS.md`) | `camera/` (CameraX capture, JPEG), `link/` (`OverheadLink` WebSocket client, frame header, protocol), `settings/` (pairing URI, DataStore `cam_settings`, mDNS discovery), `pairing/` (D-341 `rosy-pair/1` console-approved pairing: code, shapes, `PairingClient` state machine, HTTPS transport, `PairingSession`), `service/` (foreground stream service), `ui/` (Compose screens), `health/` |
| `app/src/test/java/io/github/livsbittt/rosy/cam/` | JVM unit tests (no emulator) |

## For AI Agents

### Working In This Directory

- Wire names follow the wire, not the app (D-374 3항, D-377 4항): keep `OverheadLink`, `OverheadServiceRecord`, `OverheadServerDiscovery`, `rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`, `rosyov://` and the `rosy.overhead.vectors` test property unchanged.
- Shared vectors: `test/fixtures/protocol/overhead-ingest.v1.json` (also read by `src/site/vision/test/test_protocol.py`) `test/fixtures/protocol/discovery-txt.v1.json`, and the D-391 `failure-classes.v1.json` / `site-link.v1.json` (also read by `core_common` `failure_class.py` / `site_link.py`), and the D-341 `pairing.v1.json` (property `rosy.pairing.vectors`; also read by `core_common` `pairing.py`). Do not edit one side only.
- Pairing trust (D-341 3, 8, 9): `FirstContactTrust` records the first leaf unvalidated and then accepts only that leaf, for the pairing calls only. Never reuse it for the frame link, which trusts the pinned site CA (`PinnedTrustManager`).
- The launcher icon is a copy of `src/hmi/web_common/icons/cam.svg` (D-370 3항); `LauncherIconParityTest` checks it.
- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.

### Testing Requirements

```powershell
$env:JAVA_HOME='X:\java\jdk-21.0.8'; $env:GRADLE_USER_HOME='X:\DevCaches\gradle'
cd src/site/cam; .\gradlew.bat testDebugUnitTest assembleDebug; .\gradlew.bat --stop
```

Host contract tests (no JDK): `python -m pytest test/architecture/test_app_roles.py src/hmi/web_common/test/test_surface_icons.py -q`. CI: `.github/workflows/android.yml`.
