# ceiling_camera

Rosy Ceiling Camera (D-370 2항 `Rosy 천장 카메라`, D-374 role id `ceiling-camera`): the Android phone app that streams ceiling-camera JPEG frames to Site Vision over `rosy-overhead/1`. Kotlin + CameraX + OkHttp. Not a ROS package (`COLCON_IGNORE`); Gradle only.

Moved out of `src/site/overhead/android` on 2026-09-30 (D-374 stage 1). History before that date lives in `src/site/site_vision/logs.md`.

## Key Files

| File | Description |
|------|-------------|
| `settings.gradle.kts` | `rootProject.name = "rosy-ceiling-camera"`, one module `:app` |
| `app/build.gradle.kts` | `namespace`/`applicationId` `io.github.livsbittt.rosy.ceilingcamera`; JVM test system properties for the shared vectors and D-370 icon SVGs |
| `app/src/main/AndroidManifest.xml` | Registers the `rosyov://` pairing link (never changes, D-374 3항) |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `app/src/main/java/io/github/livsbittt/rosy/ceilingcamera/` | `camera/` (CameraX capture, JPEG), `link/` (`OverheadLink` WebSocket client, frame header, protocol), `settings/` (pairing URI, DataStore `ceiling_camera_settings`, mDNS discovery), `service/` (foreground stream service), `ui/` (Compose screens), `health/` |
| `app/src/test/java/io/github/livsbittt/rosy/ceilingcamera/` | JVM unit tests (no emulator) |

## For AI Agents

### Working In This Directory

- Wire names follow the wire, not the app (D-374 1·3항): keep `OverheadLink`, `OverheadServiceRecord`, `OverheadServerDiscovery`, `rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`, `rosyov://` and the `rosy.overhead.vectors` test property unchanged.
- Shared vectors: `test/fixtures/protocol/overhead-ingest.v1.json` (also read by `src/site/site_vision/test/test_protocol.py`) and `test/fixtures/protocol/discovery-txt.v1.json`. Do not edit one side only.
- The launcher icon is a copy of `src/hmi/web_common/icons/ceiling-camera.svg` (D-370 3항); `LauncherIconParityTest` checks it.
- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.

### Testing Requirements

```powershell
$env:JAVA_HOME='X:\java\jdk-21.0.8'; $env:GRADLE_USER_HOME='X:\DevCaches\gradle'
cd src/site/ceiling_camera; .\gradlew.bat testDebugUnitTest assembleDebug; .\gradlew.bat --stop
```

Host contract tests (no JDK): `python -m pytest test/architecture/test_app_roles.py src/hmi/web_common/test/test_surface_icons.py -q`. CI: `.github/workflows/android.yml`.
