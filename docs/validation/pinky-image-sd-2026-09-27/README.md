# Pinky Pro image 2026.09.26-023 and SD handoff

## Image and signature

- Native ARM64 [GitHub Actions run 36249680735](https://github.com/livsbittt/rosy-os/actions/runs/36249680735) completed successfully from source `e511afe3fc442e1bb38adb3c54351870c5a63480`. The run passed the unsigned image build, `xz --test`, `sha256sum --check`, and artifact upload.
- The downloaded ZIP is 2,574,767,191 bytes with SHA-256 `8bb9a68c7892fbadc37eefb6c423d5a7e9259e7509dd9af7ecdb9335faf61c2f`, matching the Actions artifact record. The image is `rosy-os-pinky-pro-2026.09.26-023-arm64.img.xz`, SHA-256 `c5bc26c6e8be6e98c60e173867794e442926082fce5e28398786b625fba3d88f`.
- The offline signer verified all 15 unsigned files and signed both the outer release and embedded factory release. `verify-image-release.py` then verified the signature, manifest identity, and image hash with `rosy-release-2026-01.pem`.
- The image build imported `libcamera` and Picamera2 and ran `rpicam-still --version` inside the ARM64 rootfs. It added `dtoverlay=ov5647`. These are image checks, not camera capture on a Pinky.

## Remaining media and device gates

- The previously verified 32GB card for `rosy-pinky-pagt` (robot 20, release `2026.09.26-018`) was absent from the Windows disk inventory at the last check. The signed `023` image has **not** been written to that card. The existing release receipt is held outside the repository under `X:\DevTemp\rosy-card-2026.09.26-018`.
- Reinsert and identify the card by serial, capacity, partition layout and existing provision identity; create a new reviewed plan using the verified earlier receipt; write `023`; and require full media readback plus a new receipt. The card is not accepted from image checks alone.
- After booting that card on Pinky, record its boot ID, release, CORE/I/O/camera service states, OV5647 enumeration, an actual `rpicam-still` JPEG, Picamera2 frame, ROS `camera/front` and `camera/preview/compressed` frames, and authenticated web preview. D-288 remains Proposed until the physical capture passes.
