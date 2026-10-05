---
title: 네이티브 Pilot 프록시가 X-Rosy-Camera-* 증명 헤더를 버려 카메라 보기가 영구히 실패했다
date: 2026-10-05
category: runtime-errors
module: middleware/ui/pilot/android (PilotProxy.kt trusted loopback proxy) + shared/web evidence.js camera pair fetch; Lenovo field tablet WebView against the real robot
problem_type: integration_issue
component: service_layer
severity: high
symptoms:
  - "Pilot camera preview permanently showed 'camera frame unavailable' against the real robot on the Lenovo field tablet"
  - "every JPEG frame pull failed validation in shared/web evidence.js fetchCameraPair() because the X-Rosy-Camera-* provenance headers never arrived"
  - "GET /api/v1/vision/front/stream (multipart/x-mixed-replace) fell into the fully-buffered proxy path instead of the streaming pass-through, stalling the drive-screen camera"
  - "after the fix and reinstall, WebView CDP on hardware confirmed the x-rosy-camera headers arrive and the camera renders 320x240 frames"
root_cause: logic_error
resolution_type: code_fix
framework_version: Android WebView native shell (Pilot app on Lenovo TB-J606F field tablet)
related_components: [web_common, testing_framework]
tags: [pilot, android, webview, proxy, camera, mjpeg, x-rosy-camera, mockwebserver]
---

# 네이티브 Pilot 프록시가 X-Rosy-Camera-* 증명 헤더를 버려 번들 카메라 보기가 영구히 실패했다

## Problem

Rosy Pilot 네이티브 Android 앱의 전용 루프백 프록시 `PilotProxy`(NanoWSD + OkHttp)가 CORE 응답을 재구성할 때 `X-Rosy-Camera-*` 증명 헤더 다섯 개를 전부 버렸고, 번들 웹 화면의 프레임 반입 검증(`shared/web/evidence.js`의 `fetchCameraPair`)이 매 풀마다 예외를 던져 카메라 보기("카메라 보기")가 영구히 사용 불가 상태로 굳었다. 같은 자리에서 발견한 두 번째 결함은 드라이버 MJPEG 스트림(D-368, `multipart/x-mixed-replace`)이 완전 버퍼 경로로 빠져 운전 화면 카메라가 수 분간 멈추는 것이었다.

## Symptoms

- Lenovo 현장 태블릿(TB-J606F)의 Pilot 앱에서 카메라 보기가 실제 로봇 rosy-pinky-8kcn(CORE release 2026.10.04-034, HTTPS :8080) 상대로 계속 "camera frame unavailable" 상태였다.
- 로봇 쪽은 건강했다. `/api/v1/vision/front/status`는 200, 프레임은 fresh 320x240, journal은 깨끗했다 — 로봇 vision 자체의 문제가 아니었다.
- PC에서 CORE에 직접 `GET /api/v1/vision/front/frame`을 보내면 다섯 증명 헤더(`X-Rosy-Camera-Source/Sequence/Captured-At/Frame-Id/Variant`, `middleware/core/api_web/core_api_web/api/v1/vision.py:86-90`)가 모두 실렸지만, 태블릿 WebView 안(=프록시 경유)에서는 200과 JPEG 본문만 오고 헤더가 전부 사라졌다.

## What Didn't Work

- **로봇 쪽 로그·저널 점검** — 깨끗했다. vision이 정상이라는 확인만 되고 원인 후보는 좁혀지지 않았다. 수상은 네이티브 앱으로 옮겨졌다.
- **`uiautomator` 덤프** — WebView 내부 DOM은 보이지 않는다. 네이티브 뷰 계층만 덤프되어 카메라 보기 안의 실제 상태와 에러 문구를 읽을 수 없어 막다길이었다.
- **`logcat`** — 앱이 웹 콘솔을 로그로 남기지 않아 페이지 안의 JavaScript 예외가 밖으로 새어 나오지 않았다.
- **PC에서 CORE 직접 호출** — 응답은 정상(헤더 5개 모두 존재)이었다. 재현 경로가 프록시 경유일 때만 실패한다는 점만 확인됐다. "PC에서는 200인데 태블릿 클라이언트만 실패하는" 이 분열은 이 저장소의 반복 패턴이다(session history — 2026-10-01 Fleet 콘솔 카메라 시험에서도 같은 분리가 원인 고립의 출발점이었다).

막힌 세 갈래를 뚫은 것은 WebView inspection이었다. `/proc/net/unix`에 잡힌 `webview_devtools_remote_<pid>` abstract 소켓을 `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`로 노출하고, `http://127.0.0.1:9222/json/list`에서 페이지 목록을 얻은 뒤 WebSocket으로 CDP `Runtime.evaluate`를 실행했다. 살아 있는 페이지 안에서 프레임을 당겨 보니 200 + JPEG인데 `X-Rosy-Camera-*`가 전부 없었다 — 결함이 헤더 손실로 고립됐다. 이 레시피는 태블릿 Chrome 디버깅에서 이미 확립되어 있던 것의 WebView 재적용이다(session history). 단, 이 비교는 페이지 안에서 back-to-back(~70 ms) 요청으로 해야 한다. 외부의 느린 status→frame 클라이언트는 시퀀스 경합으로 409 `CAMERA_FRAME_ADVANCED`(vision.py:63-67)를 받기 때문이다(당시 실측 프레임 주기 ≈500 ms). 이 409는 계약상 정상 동작이지 이 버그가 아니다.

## Solution

수정은 branch `feat/pilot-show-code`, tip commit "fix(pilot): relay X-Rosy camera provenance headers through the native proxy"(2026-10-05) — 2026-10-05 기준 main에는 아직 착지하지 않았다(not-on-main). 고친 곳은 `middleware/ui/pilot/android/app/src/main/java/io/github/livsbittt/rosy/pilot/PilotProxy.kt` 두 군데다.

**1. `forwardRosyHeaders()` 신규 — `x-rosy-*` 헤더를 양쪽 응답 경로에 전달.** upstream 응답에서 이름이 `x-rosy-`로 시작하는(대소문자 무시) 헤더를 전부 proxied 응답에 옮긴다(PilotProxy.kt:133-138). 버퍼 바이트 경로(PilotProxy.kt:118)와 bounded 스트리밍 경로(PilotProxy.kt:107) 모두에 적용했다.

수정 전 — 프록시는 status + Content-Type + 본문(+Content-Range)만 재구성했다:

```kotlin
// 버퍼 경로: reply()는 status·mime·bytes 로만 응답을 만든다 (PilotProxy.kt:139-140)
return reply(response.code, mime, bytes).apply {
    response.header("Content-Range")?.let { addHeader("Content-Range", it) }
}   // upstream 의 나머지 헤더(X-Rosy-*)는 전부 사라진다

// 스트리밍 조건에 MJPEG 이 없어 multipart/x-mixed-replace 도 버퍼 경로로 들어왔다
if (session.uri.startsWith("/api/v1/") && (mime.startsWith("video/")
    || mime.startsWith("application/octet-stream") || mime.startsWith("application/x-tar")))
```

수정 후 — 증명 헤더 전달 + MJPEG 스트리밍 편입:

```kotlin
/** CORE가 내보내는 X-Rosy-* 증명 헤더(카메라 출처·시퀀스·변형)를 그대로 전달한다. */
private fun forwardRosyHeaders(response: okhttp3.Response, to: Response) {
    for (name in response.headers.names()) {
        if (!name.startsWith("x-rosy-", ignoreCase = true)) continue
        for (value in response.headers.values(name)) to.addHeader(name, value)
    }
}
// 버퍼 경로(PilotProxy.kt:116-119)와 스트리밍 경로(PilotProxy.kt:104-109) 모두:
//   response.header("Content-Range")?.let { addHeader("Content-Range", it) }
//   forwardRosyHeaders(response, this)

// 스트리밍 pass-through 조건(PilotProxy.kt:88)에 multipart/x-mixed-replace 추가
if (session.uri.startsWith("/api/v1/") && (mime.startsWith("video/")
    || mime.startsWith("multipart/x-mixed-replace")   // D-368 드라이버 MJPEG
    || mime.startsWith("application/octet-stream") || mime.startsWith("application/x-tar")))
```

**2. MJPEG 스트림의 bounded 스트리밍 편입.** `multipart/x-mixed-replace`가 조건에 들어가면서 `GET /api/v1/vision/front/stream`이 8 MiB `readLimited` 완전 버퍼 경로(PilotProxy.kt:112) 대신 녹화 다운로드와 같은 256 MiB 상한 `FilterInputStream` 경로(PilotProxy.kt:90-105, 이미 `recordingDownloadLargerThanHtmlCapStreamsIntact`, TrustedProxyTest.kt로 시험된 경로)로 간다.

**시험.** 새 JVM 시험 `cameraProvenanceHeadersReachTheBundledScreens`가 이 전달을 고정한다. MockWebServer가 다섯 증명 헤더 + `Content-Type: image/jpeg`를 내고, 실제 화면이 쓰는 경로 그대로 `GET /api/v1/vision/front/frame?sequence=6569&overlay=false`를 프록시 origin으로 보내 프록시 응답이 다섯 헤더를 모두 실어야 한다.

태블릿에 재설치한 뒤 CDP로 종단 확인했다: 프레임 응답이 variant "raw" + 일치하는 sequence를 싣고, 카메라 보기가 320x240 프레임을 렌더하며 에러 상태가 없다.

## Why This Works

- CORE는 `GET /front/frame`의 프레임 provenance를 응답 헤더로 싣는다 — `X-Rosy-Camera-Source/Sequence/Captured-At/Frame-Id/Variant`(vision.py:86-90; `overlay=false`면 variant는 `'raw'`, vision.py:90). 본문은 JPEG일 뿐이라 헤더가 사라지면 증명이 사라진다. 카메라 메타데이터를 응답 헤더에 싣는 것은 이 플랫폼의 확립 패턴이다(session history — Fleet 콘솔 카메라 미리보기도 `X-Frame-Age-Ms` 헤더로 프레임 나이를 전달했다).
- `evidence.js`의 `fetchCameraPair`는 프레임 반입을 정확히 이 헤더들로 검증한다: 요청 URL에 status의 sequence와 overlay를 싣고(evidence.js:27), 응답에서 Sequence/Captured-At/Frame-Id를 읽어(evidence.js:30-32) variant 일치, `sequence === String(status.sequence)`, capturedAt 유한 숫자, frameId 존재를 확인한다(evidence.js:33-35). 하나라도 어기면 "원본·표시본 출처를 확인할 수 없습니다."를 던진다 — 헤더가 통째로 사라진 태블릿에서는 200 + 정상 JPEG에도 매 풀마다 예외였고, 카메라 보기는 프레임을 한 장도 받아들이지 못했다.
- 수정 전 프록시의 `reply()`는 응답을 status + MIME + 본문 길이만으로 재구성한다(PilotProxy.kt:139-140). upstream 헤더 중 `Content-Range`만 수동으로 옮겼으니 그 외 전부 — `X-Rosy-*` 포함 — 이 버려졌다. `x-rosy-` 접두사만 옮기는 규칙은 증명 헤더는 살리고, `secure()`가 이미 붙이는 자체 경직 헤더들과 hop-by-hop·위조 위험 헤더의 무조건적 반출은 계속 막는다. 새 `X-Rosy-*` 계약 헤더가 CORE에 생겨도 접두사 규칙이라 프록시 수정 없이 전달된다.
- MJPEG 스트림은 끝나지 않는 multipart 응답이다(`multipart/x-mixed-replace; boundary=frame`, vision.py의 stream 라우트; 파트마다 Sequence/Source/Captured-At 헤더가 본문 안에 실린다). content-length가 없으므로 완전 버퍼 경로는 스트림이 끝나거나 8 MiB 한도에 닿을 때까지 첫 바이트도 내보내지 못해 운전 화면 카메라가 수 분간 멈춘다. bounded 스트리밍 경로는 바이트가 도착하는 대로 흘려보내고 256 MiB 상한으로 여전히 무한 다운로드에 안전하다.

## Prevention

- **중계 응답을 재구성할 때는 계약 헤더 전달을 규칙으로 만든다.** status/Content-Type/본문만 옮기는 프록시는 upstream 계약 헤더를 조용히 버린다 — 이 버그처럼 서버와 검증 클라이언트 양쪽이 다 정상인데 중간에서만 실패한다. `x-rosy-*`처럼 증명·계약 헤더 접두사는 버퍼·스트리밍 두 경로 모두에서 명시적으로 전달하고, 그 전달을 시험로 고정한다(`cameraProvenanceHeadersReachTheBundledScreens`).
- **WebView 내용은 uiautomator로 못 읽는다.** production 빌드라도 `webview_devtools_remote_<pid>` abstract 소켓(`/proc/net/unix`에서 확인) → `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` → `http://127.0.0.1:9222/json/list` → WebSocket CDP `Runtime.evaluate`가 살아 있는 페이지 안에서 재현하는 길이다. 웹 콘솔을 logcat에 남기지 않는 앱에서는 이것이 유일한 창이다.
- **시퀀스 경합을 결함으로 오판하지 않는다.** 카메라 프레임 주기(당시 실측 ≈500 ms)보다 느린 외부 status→frame 클라이언트는 409 `CAMERA_FRAME_ADVANCED`(vision.py:63-67)를 받는다 — 계약상 정상이다. 경합 없이 검증하려면 페이지 안에서 back-to-back(~70 ms) 요청의 결과를 본다. 이 버그는 200에 헤더만 빠진 응답이었고, 그 대비가 원인 고립의 결정타였다.
- **Windows PowerShell의 `>` 리다이렉션은 바이너리를 망가뜨린다.** `adb shell screencap -p > x.png`는 훼손된 PNG를 남긴다. 화면 증거는 `adb shell screencap -p /sdcard/x.png` + `adb pull`로 얻는다. PowerShell 리다이렉션 무리의 다른 사례: `docs/solutions/workflow-issues/powershell-redirect-eats-korean-2026-09-29.md`.

## Related Issues

- `docs/solutions/workflow-issues/server-guard-tested-without-its-client.md` — 같은 결함 군의 과정 쪽 교훈: 서버/중간 계층이 단독으로 초록불인데 실제 웹 클라이언트가 헤더 계약에서 조용히 실패한다. 이 문서의 JVM MockWebServer 시험이 그 교훈이 요구하는 클라이언트 경로 재현이다.
- `docs/solutions/runtime-errors/cpu-bound-thread-starves-asyncio-ingest-loop-2026-10-01.md` — 반대쪽 카메라 체인(사이트 vision 수집)의 자매 결함: 숨은 상류 결함이 안드로이드 카메라 클라이언트를 오해를 일으키는 에러로 영구 정지시켰다.
- `docs/solutions/design-patterns/site-clients-pin-the-site-by-name-and-resolve-by-mdns-2026-10-01.md` — 다른 안드로이드 태블릿 클라이언트(Rosy Cam)의 접속·진단 패턴. (참조 경로가 D-427 이전 값이라 `ce-compound-refresh` 갱신 후보.)
