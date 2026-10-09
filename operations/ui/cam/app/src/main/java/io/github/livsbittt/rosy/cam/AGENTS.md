<!-- Parent: ../../../../../../../../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# cam (Kotlin package `io.github.livsbittt.rosy.cam`)

**Parent context:** `../../../../../../../../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

All Rosy Cam app code: capture, encode, and push latest-only JPEG frames to the site Vision receiver, plus pairing, settings and the Compose UI. The app knows only the site link; it never talks to Fleet or to a robot.

## Key Files

| File | Description |
|------|-------------|
| `MainActivity.kt` | Compose host; routes between pairing, settings and stream screens |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `camera/` | CameraX capture (`CameraController`), NV21 to JPEG (`Nv21`, `JpegEncoder`), `AdaptiveJpegQuality`, `FpsLimiter`, `CaptureClock`, lens probing/selection/switch |
| `health/` | `DeviceHealth` and `DeviceHealthMonitor` (battery/thermal), `HealthText` |
| `link/` | `OverheadLink` WebSocket client, 20-byte `FrameHeader`, `Protocol`, `Backoff`, `LatestOnlyPolicy`, `RateMeter`, `SiteResolver`, `PinnedTrust` (pinned site CA), `FailureClass`/`NetworkFailure` (D-391) |
| `pairing/` | D-341 `rosy-pair/1`: `Pairing`, `PairingClient` state machine, `PairingHttp` transport, `PairingMessages`, `PairingSession`, `PairingViewModel` |
| `service/` | `StreamService` foreground service, `CameraSessionPlan` |
| `settings/` | `PairingUri` (`rosyov://`), DataStore `SettingsStore`, `SiteLink*` records/prefs, mDNS discovery (`NsdSiteBrowser`, `OverheadServerDiscovery`, `OverheadServiceRecord`) |
| `ui/` | Compose screens (`StreamScreen`, `PairingScreen`, `SettingsScreen`), `RosyTheme`, `ProblemGuide`, `LensAdvice`, `CornerGuide`, `WifiState`, `LanNetworks` |

## For AI Agents

### Working In This Directory

- Keep frames latest-only: `LatestOnlyPolicy` drops stale frames instead of queueing. Do not add a send queue.
- `FirstContactTrust` (pairing) must never be reused for the frame link, which trusts the pinned site CA via `PinnedTrust` (D-341 3, 8, 9).
- Keep wire constants (`rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`) identical to `operations/vision/rosy_vision/protocol.py`; change both against the shared vectors.
- Put non-Android logic in plain Kotlin classes so tests run on the JVM.

### Testing Requirements

Matching tests live in `app/src/test/java/io/github/livsbittt/rosy/cam/<subpackage>/` (`camera`, `health`, `link`, `pairing`, `service`, `settings`, `ui`); `Vectors.kt` loads shared vectors. Run from `operations/ui/cam`: `.\gradlew.bat :app:testDebugUnitTest`.

### Common Patterns

Each subpackage has `<Name>Test.kt` beside the class's name; vector-driven tests (`ProtocolTest`, `PairingVectorsTest`, `DiscoveryVectorsTest`, `FailureClassTest`, `SiteLinkTest`) read the shared JSON instead of duplicating cases.

## Dependencies

### Internal

- Peer receiver `operations/vision/rosy_vision` (wire format), `core_common` pairing/failure/site-link readers (shared vectors)

### External

- CameraX, Compose, OkHttp, DataStore, Android `NsdManager`
