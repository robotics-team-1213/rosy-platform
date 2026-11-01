---
title: After the arm boards and cameras are re-plugged, a by-id path may name another device, either device, or a different node
date: 2026-10-31
category: runtime-errors
module: deploy/robot/omx (omx_devices.py, 99-rosy-realsense.rules), middleware/devices/omx/adapter (camera_source.py), ~/.config/rosy role env files
problem_type: runtime_error
component: development_workflow
symptoms:
  - "rosy-omx-camera@top logged 'selected camera is unavailable' every second after the top camera was swapped for a RealSense D435"
  - "two Innomaker U20CAM wrist cameras both reported serial SN0001; the shared by-id name pointed at the newer one, so arm_a's wrist role would open arm_b's camera on restart"
  - "the D435's by-id ...-video-index0 pointed at the colour node in one boot and the Z16 depth node after a replug"
  - "observer arm_a and the arm S session pointed at OpenRB boards no longer plugged in; arm_b's configured board answered with IDs 1-6 (a leader)"
root_cause: config_error
resolution_type: tooling_addition
severity: high
tags: [omx, camera, usb, udev, realsense, innomaker, device-identity, by-id, by-path]
applies_when: "any time boards, cameras or hubs on the control PC are moved, swapped or added, before an observer, camera role or session is trusted"
---

# Device identity on the control PC after re-wiring

## Problem

On 2026-10-31 the site PC came back from a power loss with the arms' boards moved, a RealSense D435 added as the top camera, and the old top camera re-used as a side camera.

Every observer, camera role and session config named its device by a `/dev/serial/by-id` or `/dev/v4l/by-id|by-path` path written by hand. Nothing reported that those paths no longer meant the right device. Three different failures hid behind "the path exists":

1. **A path names a device that is gone.** Boards and cameras moved, so the paths of arm_a, the arm S session, the top role and the front role led nowhere. Services only logged `selected camera is unavailable`.
2. **A by-id name can name either of two cameras.** The two Innomaker U20CAM-720P wrist cameras report the same USB serial (`SN0001`). udev makes one `usb-Innomaker_…_SN0001-video-index0` link for both, and it points at whichever enumerated last.
3. **A by-id name can name a different node of the same device.** The D435 exposes colour (interface 03), depth Z16 and IR (interface 00). All of their nodes share one by-id base name, and `…-video-index0` moved from colour to depth after a replug. udev's index is per interface, so two interfaces collide on the same link.

## Root cause

A by-id path is only as unique as the vendor/serial pair behind it, and only as stable as udev's per-interface index. Hand-written role files assumed both were unique and stable.

Nothing checked a role's path against what is actually plugged in, or against the kind of device the role needs.

## Solution

- **Arm boards: classify by what answers, and find the side by LED.**
  - A PING-only scan tells a follower (motor IDs 11–16) from a leader (IDs 1–6) without moving anything.
  - Left vs right was found by toggling the motors' LED register (address 65, no torque, no motion) and differencing the top camera's redness over four on/off cycles. A single-frame difference picked up auto-exposure noise across the whole image (133,790 px); the minimum over cycles left one blob per board.
  - Result: `2B162C9B…` is the right arm (arm_a), x≈494; `7F31D1FE…` is the left arm (arm_b), x≈173.
- **Twin cameras (same serial): select by USB port.**
  - The wrist roles use `/dev/v4l/by-path/…usb-0:3.3:1.0…` and `…usb-0:1.3:1.0…`.
  - A by-path name changes when the cable moves to another port, so keep the wrist cameras on their ports. Port 1.3 matched the 10-29 manifest's `wrist_b`, which confirmed the side read from the images.
- **One device with several nodes: name each node by USB interface.**
  - `deploy/robot/omx/99-rosy-realsense.rules` (pending landing with the depth-stream branch; installed on the site PC under `/etc/udev/rules.d/`) adds `/dev/v4l/by-id/rosy-realsense-d435-{color,depth,ir}` from `ATTRS{idProduct}=="0b07"`, `ENV{ID_USB_INTERFACE_NUM}` and `ATTR{index}`.
  - These names stayed on the right nodes across a port change and a USB re-authorize.
  - The links live in `/dev/v4l/by-id`, so `camera_source.selected_device` accepts them.
- **Check it in code, not by eye.**
  - `deploy/robot/omx/omx_devices.py scan` (pending landing) reports any role whose device is not plugged in, any observer whose board does not answer as a follower, and any by-id name shared by several capture nodes (with the right fix for each case). It also reports any role whose USB link is slower than `ROSY_CAMERA_MIN_USB_MBPS`, which defaults to 5000 for a `Z16` depth role.
  - Exit status 1 means problems were found.
  - A board held by a running observer is reported as busy, never as the wrong kind.
- **A new view needs a manifest role.** The side camera could not be registered for Fleet until the workcell observation contract allowed `role: side`, and depth until it gained `stream: depth`. Both are pending landing at this writing.

## Prevention

After anything is plugged, unplugged or moved on the control PC:

1. Run `omx_devices.py scan --session-config <record-config.json>`.
2. Update the role env files and the site's `~/.config/rosy/workcell-observations/observations.yaml` until it exits 0.
3. Only then start observers, sessions or a calibration.

Never select a RealSense node, or a camera whose serial another camera shares, by its kernel by-id name.

### Image-space site settings go stale with the camera (2026-11-01)

A new or moved top camera also invalidates every per-site value given in its pixels or colours: `surface_px` and `surface_lab` in the cell configs.

On 2026-11-01 the left arm's `belt` and `board` polygons were slivers near x≈520, left over from the camera before the RealSense. `cell_objects.foreground` drops everything outside the polygon, so the mask was empty. A planned leg that placed onto one of three containers on the pallet read clear.

- `cell_corridor.check` now fails closed: corridor pixels outside `surface_px` count as `off_surface`. On that frame the old polygon gave 10,844 px off the surface and a refusal.
- With this camera's three surface colours (table Lab 175/125/161, pallet 86/134/86, belt 61/129/101) the same leg was refused at the occupied slot. With `--stack` it passed.
- After a camera change, redraw `surface_px` and resample `surface_lab` per site together with the remap.
- An all-empty foreground on a frame that shows objects means the site settings are stale. It never means the path is clear.
- The black arm links read as the black belt, so the other arm is not foreground. Its position must come from its joint state.

## Not resolved here

The D435 gave colour but no depth on USB 2.0 when plugged directly into a PC port (no frames; UVC control errors -32 and -110). Behind a hub it had given depth at the same USB 2.0 speed.

The suspected cause is bus power for the depth projector. It is unmeasured. The fix still to try is a USB 3 cable into a SuperSpeed port.

Record: Confluence "2026-10-31 OMX 셀 팔·카메라 재배선 문제 상황" (SP 15269960).
