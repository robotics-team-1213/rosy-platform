<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# app

## Purpose

The single Gradle module `:app` of Rosy Cam (Kotlin, Jetpack Compose, CameraX, OkHttp). It captures ceiling-camera JPEG frames and pushes them to the site-PC Rosy Vision receiver over `rosy-overhead/1`. Fleet never sees frames, only derived poses from Vision (D-257, D-261). Gradle wrapper, settings and version catalog live one level up in `operations/ui/cam/`.

## Key Files

| File | Description |
|------|-------------|
| `build.gradle.kts` | `namespace`/`applicationId` `io.github.livsbittt.rosy.cam`, minSdk 26, compile/target 35, Java/JVM 17, Compose + `buildConfig`. Test task passes the shared-vector paths as JVM system properties (`rosy.overhead.vectors`, `rosy.discovery.vectors`, `rosy.failure.vectors`, `rosy.sitelink.vectors`, `rosy.pairing.vectors`) |
| `src/main/AndroidManifest.xml` | Activity, foreground stream service, `rosyov://` pairing link |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/main/java/io/github/livsbittt/rosy/cam/` | App code (see its `AGENTS.md`) |
| `src/main/res/` | `drawable/` launcher foreground/monochrome and `ic_stat_camera` vector icons, `mipmap-anydpi-v26/` adaptive icons, `values/` (`strings.xml`, `ic_launcher_background.xml`), `xml/network_security_config.xml` (cleartext allowed app-wide because the site-PC address is arbitrary LAN, D-261 5) |
| `src/test/java/io/github/livsbittt/rosy/cam/` | JVM unit tests, mirrors the main package layout; `Vectors.kt` loads the shared JSON vectors |

## For AI Agents

### Working In This Directory

- Wire names stay as they are (`OverheadLink`, `rosy-overhead/1`, `rosyov://`, `rosy.overhead.vectors`); see `../AGENTS.md` (D-374 3항, D-377 4항).
- Changing a shared vector means changing both sides: Kotlin tests here and the Python readers (`operations/vision/test`, `core_common`). Vector files live in `test/fixtures/protocol/` at the repo root; `build.gradle.kts` resolves them with `rootProject.file("../../../test/fixtures/protocol/...")`, so keep the module at this depth.
- `network_security_config.xml` permits cleartext app-wide (documented in its comment); do not rely on it for new endpoints, and never operate over public networks.
- The launcher icon is a copy of `src/hmi/web_common/icons/cam.svg`; `ui/LauncherIconParityTest` fails if they drift.

### Testing Requirements

```powershell
$env:JAVA_HOME='X:\java\jdk-21.0.8'; $env:GRADLE_USER_HOME='X:\DevCaches\gradle'
cd operations/ui/cam; .\gradlew.bat :app:testDebugUnitTest; .\gradlew.bat --stop
```

Unit tests need no emulator or device. A green unit run is not device or field acceptance.

### Common Patterns

- Pure logic (backoff, header, lens choice, failure classes) is kept free of Android types so it runs on the JVM; Android-bound classes (`CameraController`, `StreamService`, `NsdSiteBrowser`) stay thin.

## Dependencies

### Internal

- Shared JSON vectors in `test/fixtures/protocol/`; `src/hmi/web_common/icons/cam.svg`

### External

- CameraX, Jetpack Compose, OkHttp, DataStore (versions in `../gradle/`), Android SDK 35
