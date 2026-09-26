# Pinky camera capture acceptance snapshot (2026-09-26)

## Scope

Read-only SSH to the ROSY SD Pinky and local Chromium capture. The device address,
credentials, login code, and media are intentionally absent from this public record.

## Device readback

- Kernel `6.8.0-1064-raspi`; boot config has `camera_auto_detect=0` and `dtoverlay=ov5647`.
- `/sys/bus/i2c/drivers/ov5647/11-0036` exists. Boot log says `rp1-cfe` found
  `ov5647@36` and is using `ov5647 11-0036` for capture. This proves sensor probe,
  not an independently saved image on the current SD.
- Active CORE release is `2026.09.26-017`; `rosy-core` is active and `rosy-io`
  is inactive. Running OpenAPI description is v1.33 and exposes only the front
  status/JPEG endpoints, not the v1.37 evidence endpoints.
- `rpicam-hello`, `rpicam-still`, `libcamera-hello`, `libcamera-still`, and the
  `picamera2` Python import are unavailable on this SD. No `captures/` directory
  exists yet. D-288's source-built image has not been deployed.
- The second Pinky responds to ICMP, but the configured native `rosy` SSH key
  was rejected; its sensor and userspace state were not read in this session.

## Local browser readback

With a synthetic JPEG and actual headless Chromium `MediaRecorder`, capture
produced a JPEG, a WebM whose header starts `1a 45 df a3`, and a JSON operation
manifest containing an accepted manual-drive action. The camera panel's viewer
storage options and unavailable-frame controls also passed in Chromium:

```text
ROSY_RUN_BROWSER_TESTS=1 python -m pytest \
  test/test_camera_capture_browser.py \
  test/test_role_menu_panels_browser.py::test_console_camera_preview_stops_on_hidden_document_and_unmount -q
2 passed
```

## Remaining acceptance

Build and verify the native ARM64 image, boot a new SD on Pinky, capture a real
JPEG with the product userspace, then test live dashboard screenshot, video,
operation JSON, and the selected PC/robot SD destinations. The current kernel
probe and local browser test do not establish those gates.
