# Pinky Integrated Result Dashboard Design

Date: 2026-09-22

Status: selected implementation direction. This dashboard visualizes ROS-SIM
evidence and does not promote the result to physical-device acceptance.

## Goal

Make one integrated Gazebo run independently reviewable by a person who did not
watch the simulation. The evidence must show the actual driven path, the Pinky
envelope and wall geometry, an exact-run camera frame, every acceptance gate,
the Nav2 terminal result, and the known limitations.

## Chosen architecture

The authoritative artifact remains `result.json`. The collector adds bounded
route points, reference-wall geometry, and a browser-compatible camera still.
A ROS-free renderer reads that JSON and writes one self-contained `dashboard.html`
with the result data embedded. The generated page therefore works offline and
cannot silently load a different run.

This historical evidence surface stays separate from the live CORE dashboard.
The live dashboard controls a robot and displays current state; the result
dashboard reviews an immutable past run. Mixing the two would make it too easy
to mistake current telemetry for the accepted run.

## Evidence additions

- `trajectory.points_xy`: odometry points retained at a bounded spatial
  interval and capped to a finite count.
- `geometry.reference_walls`: the exact wall boxes used by the clearance audit.
- `camera.evidence_file`: a BMP written from one real `/camera/front` message
  from the accepted run, with encoding and frame metadata retained.
- Existing world and wall SHA-256 values remain the source-identity authority.

The camera artifact is written atomically next to the JSON. Unsupported image
encodings do not fabricate a frame; the JSON records the reason and the run can
still fail through its existing camera gates.

## Dashboard composition

The visual direction is an industrial test-cell console: dark graphite canvas,
high-contrast safety green for PASS, amber for HOLD, and precise monospaced
measurements. It contains:

1. A verdict rail separating `ROS-SIM PASS`, raster-fidelity HOLD, and physical
   Pinky `NOT_TESTED`.
2. A scaled SVG floor plan with measured walls, actual odometry path, start/end,
   and Nav2 goal markers.
3. The exact-run camera still with lane, stop-line, and crosswalk readbacks.
4. Clearance, route, map, Nav2, authority, and final-zero measurements.
5. A complete gate matrix rather than one opaque score.
6. Source hashes and run ID for traceability.
7. A prioritized improvement panel that does not hide open gates.

At narrow widths, the map and camera stack vertically. All status meaning is
carried by text and shape as well as color.

## Rendering and failure behavior

`pinky_acceptance_dashboard.py` accepts a result JSON, template path, optional
camera file, and output path. It validates the schema and required run identity,
escapes the JSON before embedding it in a script element, and writes the output
atomically. It never changes the result verdict.

If trajectory points, walls, or a camera artifact are missing, the dashboard
renders an explicit unavailable state. A malformed result stops rendering with
a non-zero exit rather than producing a plausible-looking page.

## Verification

- ROS-free unit tests cover trajectory downsampling, BMP encoding, schema
  validation, escaping, and atomic dashboard generation.
- `gz_sim` package tests protect installation of the renderer and web template.
- A fresh integrated Gazebo run produces the enhanced result and camera asset.
- Chromium verifies the map path, camera, gates, HOLD/NOT_TESTED labels,
  responsive layout, and absence of browser console errors.
- The final screenshot is stored beside the result and dashboard.
