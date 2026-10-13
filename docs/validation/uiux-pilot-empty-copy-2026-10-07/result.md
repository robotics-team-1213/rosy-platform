# Pilot discovery empty-state copy — 2026-10-07

On local `main` `3ced069c9`, the current Pilot debug APK left the final `요.` alone on a third line at the declared 400dp landscape width. The revised lobby hint is `로봇이 없나요? Wi-Fi와 전원을 확인하세요.` The status line above already tells the operator that discovery searches the same Wi-Fi. No discovery or connection behavior changed.

The revised APK was built from `uiux/pilot-empty-copy` with `:app:testDebugUnitTest :app:assembleDebug`: **93 tests, 0 failures, 0 errors, 0 skipped**. APK SHA-256: `d2e869d2c4989bb4b3aab8e186651c74f0d465a74fe0f9cf5ec51787c5fd22a1`; build log SHA-256: `f546b94d9f8b58f64e7fcb48b7392051e8a405054baa7638868bf4d2b9353427`.

An isolated Android 35 emulator rendered the updated empty discovery screen at 400dp/130% text, 600dp/130% text, and 1000dp/default text. The hint stays on one line at 400dp/130%; the heading, refresh action, status, device health, and device link remain visible. Raw captures are under `X:/DevTemp/projects/rosy-platform/2026-10-07--pilot-empty-copy/`:

| Capture | SHA-256 |
|---|---|
| `pilot-400dp-final.png` | SHA-256 `e361494faecf731df9620ba997c07dd7bb324226b57cbaad1a2462edf4bdec15` |
| `pilot-600dp-final.png` | SHA-256 `0f42f222448d759900f121fab152fe7954c10813cd41d2a19d649d58c82614fe` |
| `pilot-1000dp-final.png` | SHA-256 `308ca158bd7826ec3db0816e5eb1b4f8983a7c6b7a3ac54d72084d71767b8806` |

This is **LOCAL synthetic empty-state G2 evidence only**. The Lenovo tablet still has the older installed APK; real candidate discovery, pairing, connection outcomes, operator G3, and the remaining declared Pilot states are **HOLD**.
