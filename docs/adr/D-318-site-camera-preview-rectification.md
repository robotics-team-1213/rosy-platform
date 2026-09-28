## D-318 Site Fleet camera preview supports measured lens and plane rectification

**Status:** Accepted (2026-09-28)

**Context:** The site camera app sends latest-only JPEG frames to Vision over the authenticated `rosy-overhead/1` WebSocket. Fleet obtains a short-lived source-scoped lease and reads the latest JPEG directly from Vision. The current preview presents the raw camera image. A curved lens can produce radial distortion, and an oblique camera can make a rectangular floor appear trapezoidal. `CameraMap` homography projects marker coordinates to site-map meters; it does not rectify the displayed image. Those are separate corrections and must not be conflated.

**Decision:**

1. Vision owns CPU image processing because it already receives JPEG frames and ships headless OpenCV. Fleet owns operator interaction and displays the result using the existing direct Vision preview path. Fleet never relays JPEGs and the browser never connects to ROS/DDS.
2. The preview request may carry a bounded, signed, source-scoped rectification profile in its existing short-lived Vision lease. Vision applies radial/tangential lens undistortion followed by a four-corner perspective warp only when serving that preview. Raw latest frames remain unchanged for ArUco processing, freshness, and any derived sightings.
3. Fleet provides accessible corner and lens controls, output aspect selection, a reset action, and per-source browser-local draft persistence. It labels the output as a preview adjustment, shows the current frame age, and does not claim a site calibration revision. A field-measured profile is required before the adjusted image or sighting coordinates can be treated as calibrated evidence.
4. Invalid, crossed, degenerate, out-of-range, or stale inputs fail closed to an explicit preview error or the unmodified source image; they never alter navigation, task acceptance, or `cmd_vel`. Image dimensions and JPEG output are bounded, and preview processing remains subject to the existing per-viewer rate limit.

**Alternatives:** Browser-only CSS transforms cannot correct radial lens distortion. Relaying camera bytes through Fleet violates D-275/D-293 and duplicates Vision's latest-frame authority. Changing the ArUco homography would mix display geometry with world-coordinate projection and could silently alter sightings.

**Consequences:** The browser's draft settings are convenient operator adjustments, not canonical site configuration. A later measured commissioning flow may promote reviewed intrinsics/extrinsics to a versioned site profile and bind it to map/sighting revisions. It must preserve the raw-image and final-command boundaries.

**Implementation and verification:** [D-318 design and execution plan](../plans/2026-09-28-site-camera-preview-rectification.md). Synthetic images and local Docker/browser checks prove SOURCE/LOCAL behavior only. Phone, Ubuntu/TLS, installed camera placement, measured calibration error, DEVICE, and FIELD acceptance remain separate gates.

**References:** [D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-293](D-293-site-fleet-intent-api-contracts.md), [D-313](D-313-supervised-camera-fault-demo.md).
