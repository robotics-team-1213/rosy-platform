# D-318 Site Fleet camera preview rectification

## Intent and boundaries

Give an operator a live latest-frame preview that can correct radial lens curvature and map a selected camera quadrilateral into a rectangular output. The existing phone→Vision WSS, Vision→Fleet sighting REST, Fleet→Vision signed lease, and direct Vision JPEG read remain distinct. Processing is display-only: raw JPEG bytes and marker detection continue unchanged. No camera profile created in a browser is accepted as a field calibration or allowed to authorize robot movement.

## Design contract

- Vision decodes one latest JPEG on demand, validates the signed source-scoped settings, applies `cv2.undistort`, then `cv2.getPerspectiveTransform`/`warpPerspective`, and encodes a bounded JPEG response.
- Lens coefficients, optical center, focal lengths, four ordered normalized source corners, and output aspect ratio have explicit finite ranges. Invalid geometry is rejected before OpenCV runs. Output cannot exceed 1920×1080 pixels.
- Fleet exposes a collapsible adjustment surface with keyboard-operable numeric controls, live status, reset, and a raw/adjusted label. Drafts persist per source in browser `localStorage`; users can clear them. Request updates are debounced and use the existing lease.
- Preview lease authorization stays required. Vision remains the only component with camera bytes. Existing stale frame, no-store headers, and 5 requests/second cap remain effective.
- A profile without measured intrinsics is a visual adjustment only. No corrected-preview coordinates enter `project_frame`, Fleet sightings, autonomy, or task dispatch.

## Stages

1. **Contracts/tests:** test bounded rectification validation and signed-lease round-trip/tamper/expiry. Confirm red before implementation.
2. **Vision processing:** create a ROS-free OpenCV helper with identity, radial-distortion and projective-warp tests; wire the helper into the authenticated preview response while preserving raw-frame access.
3. **Fleet UI:** add the adjustment controls and browser-local draft behavior; issue leases containing the validated settings; test UI state, request shape, reset, keyboard operation, stale/error states, and source isolation.
4. **Documentation/evidence:** update the API reference, module docs, D-61 logs/progress/index; run focused plus required Fleet/overhead and governance suites, build the Docker image, and capture desktop/mobile output under `X:\DevTemp`.
5. **Integrate:** commit the scoped work and fast-forward/cherry-pick to local main only after fresh status, path, and ancestry checks. Do not push. Keep phone/Ubuntu/site/physical calibration and FIELD gates explicitly HOLD.

## Rollback

Revert the D-318 commit. Existing lease callers omit settings and continue receiving the raw latest JPEG. The ingest protocol, raw-frame cache, sighting worker, Fleet camera lease authorization, and robot command paths remain unchanged.

## Acceptance evidence

Local tests demonstrate known synthetic barrel distortion is reduced and a known quadrilateral becomes rectangular; invalid profiles do not mutate or poison the raw frame. Browser tests demonstrate source-scoped controls and responsive keyboard operation. A local Docker result is not phone, Ubuntu, measured-installation, DEVICE, or FIELD evidence.
