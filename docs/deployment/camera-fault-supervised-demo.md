# Camera fault supervised demo: implementation and site setup

This change adds the source path for a supervised demo. It does not approve
motion on a Pinky, certify any IR thresholds, or prove that a ceiling camera
covers the full operating area.

## Camera preview path

The browser authenticates to Fleet as a named site user. Fleet issues a
source-scoped `frame:read` lease that expires after 60 seconds. The browser
uses that lease in the `Authorization` header to fetch
`/api/vision/sources/{source_id}/frame` through Caddy. Caddy sends the request
directly to Vision. Fleet never receives or relays JPEG bytes. Vision serves
only its latest frame, with `Cache-Control: no-store`; missing frames return
404 and frames older than one second return 404 with `X-Frame-State: stale`.
The dashboard removes the previously displayed frame on either condition.

Configure one independent, high-entropy secret in
`ROSY_SITE_SECRETS_DIR/vision_preview_secret`. Mount it read-only into Fleet
and Vision through the supplied Compose configuration. The secret bootstrap
exports it as `ROSY_VISION_PREVIEW_SECRET`. Fleet requires
`--vision-preview-secret-env ROSY_VISION_PREVIEW_SECRET`. Do not reuse a site
user, Fleet, CORE, phone-ingress, or sighting credential. Rotate this secret
to invalidate outstanding preview leases.

The allowed source IDs come from the configured `site-cameras.yaml`; the
browser cannot request an unconfigured source. The preview is low rate and
latest-only. Camera placement, field of view, blind spots, and the claim that
it covers an entire demo area remain site acceptance items.

## Camera-fault behavior

When selected `CAMERA_LINE` evidence is missing, invalid, or stale, CORE's
line-follow policy reports a `camera_*` hold reason and produces zero
linear/angular command candidates. Fleet shows an explicit `IR_LINE` selection
only after CORE latches camera loss. Selecting it sends an operator request to
CORE; CORE refuses it unless the camera-loss latch is present and the calibrated
sensor-only safety policy is enabled. A successful mode selection starts in
`WAITING` at zero speed. Fresh IR line evidence and the command-time sensor
policy still control each later output. There is no automatic switch.

The separate ROS-free eligibility function expresses stricter per-action gates,
but live commissioning evidence for Nav2 and teleop is not yet wired to Fleet.
Those actions are not part of the camera-fault fallback UI and must not be
enabled based on the evaluator alone.

`deploy/robot/config/line_follow.yaml` keeps IR calibration disabled by
default. The CORE Fleet fallback request therefore remains rejected until the
device has an enabled, revisioned sensor-only safety policy and a matching IR
line-observer calibration. The observer emits the SHA-256 digest of its exact
`ir_black`, `ir_white`, and `ir_min_span` values with every IR observation.
After measuring endpoints, copy that digest from CORE's
`GET /api/v1/sensors/line_follow` `calibration_revision` field into the device's
CORE config at `line_follow.ir_calibration_revision`. CORE requires a fresh,
visible, confidence-qualified IR observation with that exact digest before it
accepts the explicit Fleet fallback request. Before an IR line-follow
demonstration, commission and record each IR sensor's white/black endpoints on
that specific robot and lane, verify LiDAR or near-field stop behavior, and
prove zero-command readback. Nav2 needs its own
G4/G5, map, localization, TF, odometry, and LiDAR acceptance. Teleop needs
accepted hardware, an operator role, and a live deadman. Otherwise the demo
stays at camera preview, map/status observation, and stationary control
readback.

## Acceptance boundary

Host pytest verifies policy and protocol behavior only. Site compose/Caddy
validation verifies configuration only. Neither proves camera coverage,
operator response time, Pi/ARM64 secret mounting, physical stop response,
IR calibration, or safe motion. Those remain explicit site and Pinky gates.
