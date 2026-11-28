
# cam

**Parent context:** `../AGENTS.md`

Rosy Cam (D-377 id `cam`; 천장 카메라 앱): the Android phone app that streams ceiling-camera JPEG frames to Rosy Vision over `rosy-overhead/1`. Kotlin + CameraX + OkHttp. Not a ROS package (`COLCON_IGNORE`); Gradle only.

Moved out of `src/site/overhead/android` on 2026-09-30 (D-374 stage 1), then renamed from `src/site/ceiling_camera` the same day (D-377). History before the split lives in `operations/overhead/logs.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `app/` | Gradle module `:app`: manifest, resources, code, tests (see `app/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Wire names follow the wire, not the app (D-374 3항, D-377 4항): keep `OverheadLink`, `OverheadServiceRecord`, `OverheadServerDiscovery`, `rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`, `rosyov://` and the `rosy.overhead.vectors` test property unchanged.
- Shared vectors: `test/fixtures/protocol/overhead-ingest.v1.json` (also read by `operations/overhead/test/test_protocol.py`) `test/fixtures/protocol/discovery-txt.v1.json`,
- and the D-391 `failure-classes.v1.json` / `site-link.v1.json` (also read by `core_common` `failure_class.py` / `site_link.py`), and the D-341 `pairing.v1.json` (property `rosy.pairing.vectors`; also read by `core_common` `pairing.py`).
- Do not edit one side only.
- Pairing trust (D-341 3, 8, 9): `FirstContactTrust` records the first leaf unvalidated and then accepts only that leaf, for the pairing calls only. Never reuse it for the frame link, which trusts the pinned site CA (`PinnedTrustManager`).
- The launcher icon is a copy of `shared/web/icons/cam.svg` (D-370 3항); `LauncherIconParityTest` checks it.
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.

### Testing Requirements

```powershell
$env:JAVA_HOME='<JDK 21 path>'
cd operations/site_ui/cam; .\gradlew.bat testDebugUnitTest assembleDebug; .\gradlew.bat --stop
```

Host contract tests (no JDK): `python -m pytest test/architecture/test_app_roles.py shared/web/test/test_surface_icons.py -q`. CI: `.github/workflows/android.yml`.

### UI 역할과 생성 토큰

- 설치 대상·승인·촬영 원본·프레임 송신 상태를 먼저 보여주고 설치/보정 안내와 설정을 연결한다. 로봇 명령·CORE 연결·로봇 정지 조작을 추가하지 않는다.
- `RosyTheme`의 semantic 색 facade와 type/space/control 역할은 `shared/web/native-tokens.gradle`이 생성하는 `RosyTokenColors`/`RosyMetrics`를 소비한다. 일반 버튼은48dp·14sp·좌우12dp이며 도메인 영상/표식 기하는 유지한다.
- 생성 시험은 실제 Kotlin 소비자 컴파일·앱 JVM 시험 및 장치 캡처를 대신하지 않는다.
