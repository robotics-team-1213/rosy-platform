# Pilot current candidate and installed tablet identity — 2026-10-07

Local `main` candidate: `744d4d0c6efe87a490ddf91964409bd2764b0d68`. Built the Pilot Android debug APK in an isolated worktree, with Gradle output and cache on X:. `:app:testDebugUnitTest :app:assembleDebug` succeeded: **93 JVM tests, 0 failures/errors/skips**. The build log has two Kotlin nullability warnings in test source.

| Artifact or readback | SHA-256 |
|---|---|
| Current candidate `build/app/outputs/apk/debug/app-debug.apk` | `659ac8c08ec258e2f1e7905f57564e9255d69e88631a995a5ef4efe8bab3900d` |
| `gradle.txt` | `7e3ef1089e881f6ace84bb0838910f52c97c22b070c936a64932714cb47cb1b4` |
| Read-only ADB pull of installed Lenovo Pilot `base.apk` | `1c6216992abfbf053f77ebf667f98e3528c7dcaeac909b0f7b43dd5cd5cf2d44` |
| `asset-diff.json` (installed versus current candidate) | `a33fd998e7dfadef77e9fb3e8555382ea7185e28c0939cd43ad78a9e415e774a` |
| `prior-candidate-assets.json` (earlier emulator candidate versus current) | `5e2a61ba6e7251f9f03a0f932bc782c161887cc92e1e3830880e4bd81ed0fa98` |

The installed app still reports version `0.1.0`, last updated 2026-10-06 22:54 local device time. Its APK hash matches the earlier [tablet readback](../uiux-pilot-tablet-2026-10-07/result.md). Eight of 50 bundled `assets/pilot/` and `assets/common/` files differ from the current candidate, including Pilot layout and shared components. The current candidate's 50 bundled UI assets are **identical** to the [earlier emulator width candidate](../uiux-pilot-empty-copy-2026-10-07/result.md); Android main/debug source and Gradle build files have no diff between that candidate branch and this local `main`. Those emulator captures therefore still describe the current candidate's empty-lobby UI, but they do not prove its behavior on the Lenovo.

Raw artifacts: `X:/DevTemp/projects/rosy-platform/2026-10-07--pilot-current-apk/`. The tablet was read only; no APK was installed, no robot was selected, and no motion command was sent. **DEVICE G2 and operator G3 remain HOLD** until this candidate's identity is verified after installation and the declared discovery, pairing, failure, reconnect, and operator tasks are observed on the device. This local build has no CI or site release evidence.
