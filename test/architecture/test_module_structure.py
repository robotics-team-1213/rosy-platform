"""D-168: ROS package structure standard (P2 layout, P3/P4 coupling, P6 size).

Every exception list below is checked by set equality (P5): a new violation
fails, and so does an entry whose violation has since disappeared. Update the
list in the same change that creates or removes the violation.

Honest holes, not oversights:
- Launch coupling is found only through literal
  ``get_package_share_directory("x")`` / ``FindPackageShare("x")`` calls,
  ``$(find-pkg-share x)``, ``package://x/…`` URIs, and, inside launch files,
  ``package="x"`` and ``<node pkg="x">``. A package name built at runtime is
  invisible here.
- Packages are found under every ``colcon_roots`` entry and placed relative to
  their root: ``learning/envs/isaac`` (``isaac_sim``, D-427 wave 1) is domain ``envs``.
- Dynamic imports (``importlib.import_module``, entry points) are invisible.
  The one intended case is core loading ``rosy.sensor_provider`` (D-126).
- P6 budgets are per code type (D-362): 600 for production ``.py``/``.cpp``/``.hpp``/``.sh``
  across ``src/`` packages and the ``deploy``/``tools``/``learning``/``operations/site_devices`` roots, 800 for web
  assets (``.js``/``.html``/``.css``) inside ``src/`` packages, zero growth allowance above
  1000. Test code and data files are exempt. Line counts are physical lines, blank
  lines and comments included.
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

#: ``envs`` is the first folder under the ``learning`` colcon root (D-427 wave 1);
#: ``apps``, ``vision`` and ``processes`` are under the ``operations`` root (D-427 wave 3b).
DOMAINS = {"contracts", "runtime", "drivers", "products", "hmi", "site", "sim", "envs",
           "apps", "vision", "processes", "fleet", "ui", "web", "core", "simulation",
           "foundation", "ros_idl", "perception"}

#: P2 library/contract tier: no process of their own (runtime gates N/A).
LIBRARY_PACKAGES = {"core_common", "core_events", "core_features", "core_api_web", "web_common"}

#: P4: core contracts every domain may consume.
CORE_CONTRACTS = {"interfaces", "core_common", "web_common"}

#: P2(d) exceptions: packages without their own test/test_*.py.
KNOWN_WITHOUT_OWN_TESTS = {
    "navigation": "launch/params contracts live in the repository test/ suite",
}

#: P3/P4 exceptions as (source package, target package).
KNOWN_UNDECLARED = {
    ("navigation", "control"): "hardware.launch.py includes control/line_follow.launch.py",
}

#: P4 core-row exceptions: back-edges against the one-way core chain.
KNOWN_CHAIN_BACK_EDGES = {
}
KNOWN_DIRECTION = {
    ("control", "imu_bno055"): "runtime/sensing -> drivers/imu_bno055; declared exec_depend. Legacy launches start the IMU driver; the long-term fix is bringup assembly, not a sensing launch",
    ("rosy_vision", "games"): "Rosy Vision reuses the ROS-free four-point homography helper for camera calibration",
    ("bringup", "control"): "products/bringup -> runtime/sensing: bringup_robot.launch.py starts control's ir_adc_node for the rosy-io graph (enable_ir, D-344 §12) — bringup assembling the robot graph is the direction the imu_bno055 row names",
}

#: P6 budgets.
FILE_BUDGET = 600
PACKAGE_BUDGET = 10_000
REGROWTH_ALLOWANCE = 150

#: P6 per-type budgets and coverage (D-362), docs/plans/2026-09-30-file-size-budget-and-refactor-queue.md
FILE_BUDGET_WEB = 800
WEB_SUFFIXES = {".js", ".html", ".css"}
OPS_SUFFIXES = {".py", ".sh"}
OPS_ROOTS = ("deploy", "tools", "learning",  # learning: moved perception tooling (D-427 wave 1)
             "operations/site_devices")  # site device firmware (D-427 wave 3b)
HARD_TIER = 1_000  # a file above this gets zero growth allowance
#: P6 subpackages counted as their own size unit (path relative to the colcon root): their lines
#: leave the package total and the unit always carries a verdict with the package +150 allowance.
#: docs/plans/2026-10-07-line-follow-recovery-subpackage.md (incl. its 2026-10-08 junction section),
#: docs/plans/2026-10-08-line-follow-arc-subpackage.md,
#: docs/plans/2026-10-09-core-localization-size-unit.md
#: Add a unit only by a dated docs/plans split plan with independent review, in the same change as
#: the parent package's re-judge. A unit is an existing Python subpackage of a PACKAGES member.
SIZE_UNITS = ("core/services/core_features/line_follow/recovery",
              "core/services/core_features/line_follow/recovery/junction",
              "core/services/core_features/line_follow/arc",
              "core/services/core_features/localization",
              "fleet/fleet/traffic",
              "perception/control/sensing/perception")

CONTROL_SPLIT = "docs/plans/2026-09-22-control-package-split-design.md"

#: P6 verdicts: path (relative to src/) or package name -> (lines at verdict, verdict).
SIZE_VERDICTS = {
    "core/gateway/core/services.py": (
        603,
        "accept: independently judged at 603 (2026-10-09, read-only critic agent) for D-541 step 1: "
        "D-541 adds only the trip_lease import, field, build_trip_lease call and kwarg; lease logic and "
        "wiring live in core/trip_lease.py (fleet_loss_wiring pattern). services.py stays CORE composition. "
        "On next growth, split: move the pure config parsers (_battery/_power/_traffic_policy_config, "
        "_simulation_docking, _seeded_dock_database) to core/*_wiring.py, re-exporting _battery_config for "
        "tests. Budget and allowance unchanged",
    ),
    "fleet/fleet/server/trip_runner.py": (
        686,
        "split: measured at 686 on 2026-10-08 after the named seam was applied (D-517 split, behaviour-preserving): "
        "lap helpers are in server/trip_laps.py, halts and restart halts in server/trip_halts.py, the traffic "
        "hold-back and the tick's pinned/step block in lane_traffic.TrafficService (holds/watch/period). What "
        "remains is one state machine: start/cancel/tick/_step*/replan and the CORE junction protocol. Re-judge "
        "after the next growth. Previously judged at 847 on 2026-10-08 (independent re-judge, critic agent): D-517 M1a gave the trip loop "
        "three more jobs on top of the D-494 state machine: repeat-lap bookkeeping, robot halts and post-restart "
        "halts, and traffic glue. Move the lap helpers to server/trip_laps.py, the halt helpers to "
        "server/trip_halts.py, and the traffic hold-back and pinned/step block into lane_traffic.TrafficService; "
        "trip_runner keeps start/cancel/tick/_step*/replan. Recorded in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md; re-judge after the move. Previously accepted "
        "at 604 (bend diagnostic)",
    ),
    "fleet/fleet/traffic": (
        1509,
        "split: measured at 1509 on 2026-10-09. D-551 adds traffic/trip_advice.py "
        "(display-only signal advice) and D-525 rev 3 extends signal_phase.py and "
        "lane_traffic.py. The named lane-traffic seam in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md remains the next split. "
        "+150 allowance measured from 1509. "
        "Previously measured at 1242 on 2026-10-09 after moving the three fleet.traffic YAML parsers "
        "from cli.py into traffic/config.py without changing their validation or exits. D-525 S1 signal "
        "phase and lane hold code remains in this traffic owner; the named lane-traffic seam in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md remains the next split review. "
        "Previously re-judged at 1095 on 2026-10-09: main added signal_phase.py and the D-517 block edits. "
        "+150 allowance measured from 1242. "
        "Previously measured at 867 on 2026-10-08 when the lane traffic seam was applied (pure move, no shim, no "
        "behaviour change): blocks.py 425, lane_traffic.py 369, trip_authority.py 69, __init__.py 4, out of "
        "the fleet package count. Only server/trip_runner.py imports it; it imports routing.graph, "
        "routing.execute.arc_id, server.trip_ports and localization.map_pose, never trip_runner. Later "
        "D-517 convoy and grant code goes here. Re-judge after D-517 M4 per "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md, and decide then whether "
        "server/traffic_reservations.py moves in or retires.",
    ),
    "fleet/fleet/server/web/map-view.js": (
        831,
        "split: measured at 831 on 2026-10-08 after the named camera backdrop seam was applied "
        "(behaviour-preserving): the camera picture path (cameraMapCalibration, the top-down cache, "
        "drawCameraTopDown, warpOnto, setCameraFrame, frameTurn, turnedUrl, bindCamera) is in "
        "web/camera-backdrop.js, which map-view feeds its draw hook, calibrations and toPx; the D-517 10 "
        "traffic drawing is in web/traffic-view.js (polling and toggle stay here). Still over the web "
        "ceiling 800 with one job left, map drawing and its polling; re-judge after the next growth. "
        "Previously judged at 903 on 2026-10-08 (independent re-judge, critic agent): the D-513 7 camera turn "
        "and the D-515 top-down camera warp made map-view.js own two jobs, map drawing (grid, robots, "
        "formation, mediation, metre site view) and the camera picture path. Move cameraMapCalibration, "
        "drawCameraTopDown, warpOnto, setCameraFrame, frameTurn, turnedUrl and bindCamera to a new "
        "web/camera-backdrop.js beside camera-warp.js; map-view keeps a draw hook and the toPx projection "
        "it passes in. Recorded in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md. Re-judge "
        "after the move or if the file grows again",
    ),
    "web/components.css": (
        814,
        "accept: shared token-based component styles remain one web_common responsibility; "
        "D-461 adds opt-in workspace primitives without another palette or runtime owner. "
        "Splitting loading and deployment is a separate task. The 600-line ceiling and growth "
        "allowance remain unchanged; re-judge when another component family expands this file",
    ),
    "ui/pilot/styles.css": (
        811,
        "split: Pilot lobby, connection and drive responsive layouts share this surface stylesheet; "
        "D-447 concurrent baseline work restores the existing 44px target floor on narrow screens. "
        "Retain that correction; group the screen-specific rules into separately loaded assets "
        "under docs/plans/2026-10-04-ui-release-and-live-refinement.md with installed and native "
        "asset parity checks. Owner pilot; follow-up after device acceptance. Web ceiling and "
        "growth allowance remain unchanged",
    ),
    "dashboard": (
        10_668,
        "split: re-judged at 10668 on 2026-10-08 (independent re-judge, critic agent): +195 since 10473 is "
        "navigation-map UI in the existing map owner (map.js 534, panels/console/map.js 207: "
        "trusted-localization and safe-stop goal gating, path/route evidence, map identity, mobile stage); "
        "every asset under 800, no transport or command path. Next growth: move pathEvidence/setPath/"
        "canMapClick/mapIdMismatch out of createFieldMap in map.js into a sibling goal-gate module. "
        "Previously D-447(b) adds a focused shared state-stream store to the already separated task "
        "panels; package total crosses 10k on integration, while individual asset ceilings and "
        "the +150 package allowance stay unchanged. The stream, REST fallback and scope teardown "
        "remain one owner (five Node regressions pass). Group robot role resources by their "
        "surface owner and identify remaining reusable assets for the existing shared/web owner "
        "under docs/plans/2026-10-04-ui-release-and-live-refinement.md; do not split transport or "
        "duplicate its socket. Re-judged at 10473 after the dashboard development entry and "
        "temporary SSH credential view joined the same robot UI owner; the planned role-resource "
        "split still applies. Owner hmi; source-boundary follow-up after device acceptance",
    ),
    "fleet": (
        48_118,
        "split: re-judged at 48118 on 2026-10-09 after merging D-546 6 (Fleet answers a robot's pose request: localization/pose_request.py, service hook, transport call; no command or stop path) with D-555; +150 allowance unchanged. Previously re-judged at 47953 on 2026-10-09 (independent re-judge, critic agent): D-555 enrolled-robot hub pairing"
        " adds +317 production lines over main 47636: server/enrollment.py +173 (hub link issue/revoke on the existing "
        "register row, TLS fence and enrolled client), web/enrollment.js +57, cli.py +31 (hub digest load at startup), "
        "hub/hub.py +25 (SHA-256 digest HELLO check beside the old token path), enrollment_routes.py +17, swarm/transpo"
        "rt.py +10, enrollment_store.py +9, console_builders.py +3. No new package owner and no duplication. The only n"
        "ew robot call is the credential PUT/GET/DELETE /api/v1/fleet/link through the existing TLS-bound enrolled clie"
        "nt, gated on the robot's fleet_link_provisioning capability; it adds no drive, goal or E-Stop path. Next growt"
        "h: D-555 hub-link code leaves enrollment.py (956, hard tier 1000) for its own module, and the queues.js move n"
        "amed below still precedes D-540 (d). The site-map web/server split in docs/plans/2026-10-07-fleet-site-map-web"
        "-server-seam.md stays next; +150 allowance unchanged, measured from 47953. Previously "
        "re-judged at 47636 on 2026-10-09 (independent re-judge, critic agent): D-540 3 (+183 over "
        "main 47453) puts stuck decisions and the replan confirm inline in the queue rows (roster.js +102, "
        "new web/trip-replan.js 92 calling the existing confirm-replan/cancel routes), one rail scroll and "
        "collapsed robot cards; the old #stuck-panel and roster-toggle are removed, not left beside. No new "
        "robot command path or package owner. site-map.js trip-confirm stays until D-540 step (e) removes it. "
        "Next growth (D-540 step (d) trip controls on the card): first move attentionItems/attentionKey/"
        "openDecisionKey/syncRows/fillQueues/setTriageHead and the line-stuck button helpers to "
        "web/queues.js; roster.js keeps the card. +150 allowance unchanged, measured from 47636. Previously "
        "re-judged at 47327 on 2026-10-09 (author's record; NEEDS the independent re-judge with "
        "the D-550 10 Safety-Review): D-550 10 goal lease adds +211 production lines over main 47116: "
        "the safety-tagged fleet/server/goal_lease.py (123, lease table, per-source renewal gates, send, "
        "cancel), +24 cli floor check, +24 background_workers renew loop and attempt check, +13 app "
        "presence route and wiring, +13 transport, +10 trip_runner, +4 signals.js presence; console.py "
        "net -1. No new package owner; the only new robot call is the lease renewal of a goal Fleet "
        "already sent. The site-map web/server split in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md stays next; +150 allowance unchanged, "
        "measured from 47327. "
        "Previously re-judged at 47012 on 2026-10-09: D-526 adds the safety-tagged tether watch "
        "(server/tether_watch.py, tether_routes.py, trail-view colour) and its tests. It stops a "
        "tethered robot only through the existing per-robot CORE E-Stop and adds no command path "
        "or package owner. The site-map split stays next; +150 allowance unchanged, measured "
        "from 47012. Previously re-judged at 46701 on 2026-10-09: D-536 adds a read-only guide "
        "(fleet/guide/situation.py, fleet/server/guide_service.py, web/guide-layer.js) "
        "over the map snapshot Fleet already holds. It does not call the network or emit a command. "
        "Main measured 46507 before D-523's 194-line ask parser. No new robot command path or package owner. "
        "The site-map web/server split in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md stays next; "
        "+150 allowance unchanged, measured from 46701. "
        "Previously re-judged at 46295 on 2026-10-09: D-523 adds fleet/ai/decision_pipeline.py "
        "(194 lines), parsers that return an identity fact or an allowlisted choice and do not "
        "call the network or emit a command. Main measured 46083 after the traffic-config move; "
        "D-525 S1 virtual signals and D-524 Service Control stay in the existing site, traffic, "
        "and host-control owners. No new robot command path or package owner. The site-map "
        "web/server split in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md stays next; "
        "+150 allowance unchanged, measured from 46295. "
        "Previously re-judged at 45723 on 2026-10-08 (independent re-judge, critic agent): 45571 was 46434 - 863 "
        "by arithmetic; measured 45699 after the traffic move because main's D-520 1-2 arc handshake and the "
        "CORE-approaching busy fix (91b15708b) landed beside D-517 M3, each in its existing owner; then +24 "
        "console web (site-path summary, settings close). No new owner or robot command path. The site-map "
        "web/server split in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md stays next; +150 "
        "allowance unchanged, measured from 45723. "
        "Previously 45571 = 46434 - 863 after the pure move of routing/blocks.py, server/lane_traffic.py and "
        "server/trip_authority.py into the fleet/fleet/traffic size unit (lane traffic seam, "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md); no new judgement, the +150 allowance is "
        "still measured from the 46434 base. "
        "Re-judged at 46434 on 2026-10-08 (independent re-judge, critic agent): D-517 M3 lane convoy "
        "(blocks.py follow/_front_on/shared grants, lane_traffic.py convoy block, trip_laps/trip_routes/trip_runner "
        "convoy gates, site-map convoy view) adds no owner or robot command path; trip_runner 747 within 686+150. "
        "Traffic growth is steady per D-517 step, so the lane-traffic seam is named in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md and is the next split; the +150 allowance is "
        "unchanged. "
        "Previously re-judged at 46317 on 2026-10-08 (independent re-judge, architect agent): D-520 1-2 Fleet "
        "side (+97 over main) adds no module, owner, service or robot command path: exit_segment (circle fit "
        "of the next lane arc, CORE curvature/length range) is pure routing math in routing/execute.py "
        "beside turn_target; trip_runner sends it in the existing LaneJunctionPort instruction and reads "
        "CORE's line_follow.arc for carried/stopped/unarmed (768 within 686+150); trip_ports adds two "
        "TripConfig site knobs and arc_newer; TripCaps adds lane_arc; site-map-model.js +4 labels. Moving "
        "code inside fleet does not lower the package count; B2 stays unscheduled. The +150 allowance is "
        "unchanged. Previously re-judged at 46107 on 2026-10-08 (independent re-judge, critic agent): the "
        "D-507 addendum"
        " bend pass (+129 over main 2fa5d896f) adds no module, owner, service or robot command path: bend"
        " geometry (bend_geometry, next_bend, straight_approach, bend_fields, shared _pose_tol) sits in "
        "server/trip_ports.py beside junction_fields; trip_runner._step_bend sends the bend through the "
        "existing LaneJunctionPort instruction; trip_laps.carry_on and the replan-confirmed lap clear "
        "bends_done so each lap drives its bends again; site_map.py validates the bend place kind "
        "(exit_yaw, radius_m) and TripCaps gains lane_bend. The D-517 M1a seam holds (trip_runner 729 "
        "within 686+150); the +150 allowance is unchanged. Previously "
        "re-judged at 45942 on 2026-10-08 (independent re-judge, critic agent): D-517 M1a's trip runner "
        "split (server/trip_laps.py, trip_halts.py, traffic glue in lane_traffic.TrafficService), the D-517 "
        "M1b traffic map layer, the feat/fleet-map-trail web/trail-view.js and the D-512 tether display stay "
        "with their existing Fleet server and web owners, as named in "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md. No new package owner; the +150 allowance is "
        "unchanged. Previously re-judged at 45423 on 2026-10-08 (independent re-judge, critic agent): D-517 M1a adds "
        "server/lane_traffic.py (block table, computed and shown, never sent); lane_traffic.py is the single "
        "writer of lane-trip grants and traffic_reservations.py stays only as the Gazebo segment record. "
        "Per-robot and repeat-lap trips stay with the server/routing owners; no new package owner. The "
        "trip-runner seam is named in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md; +150 "
        "allowance unchanged. Previously re-judged at 44806 on 2026-10-08 (independent re-judge, critic agent): D-519 password "
        "login (server/password_session.py, site_users.py, web/shared/password-login.js/.css, page and "
        "app/cli wiring) stays with the site-auth owner beside site_auth.py and development_session.py, "
        "now the console auth seam in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md. D-507 4 "
        "chord turn stays in routing/execute.py and trip_runner.py. D-517 M0 routing/blocks.py is pure "
        "block arithmetic on routing.graph and stays in Fleet routing (D-12); D-517 M1 must name one grant "
        "writer between it and server/traffic_reservations.py, and re-judge then. No new package owner; "
        "the +150 allowance is unchanged. "
        "Previously re-judged at 43809 on 2026-10-08: "
        "map-bound bend candidate diagnostics in trip_ports "
        "and trip_runner, with fake-port tests, stay in Fleet's existing trip owner. No robot command "
        "or new service. The site-map web/server split plan and +150 allowance remain unchanged. "
        "Previously re-judged at 43623 on 2026-10-08: main's 43217 verdict plus D-472 + Addendum 2026-10-08 "
        "LED identity (server/identity.py orchestrator and binding store, tracking/console route wiring), "
        "independently judged to stay with the existing Fleet server owner as its own module (critic agent, "
        "2026-10-08); no new owner, the site-map web/server split plan and +150 allowance remain unchanged. "
        "Previously re-judged at 43217 on 2026-10-08 (independent re-judge, critic agent): D-507 junction "
        "expectation and site floor binding (server/trip_ports.py, trip_runner.py) stay with the routing/trip "
        "server owner, and the D-513 7 / D-515 camera turn and top-down warp (web/map-view.js, camera-warp.js) "
        "get the camera-backdrop seam now named in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md. "
        "No new package owner; the +150 allowance is unchanged. "
        "Previously re-judged at 42945 on 2026-10-08: D-511 M0 lane compliance (fleet/localization/"
        "lane_compliance.py observe-only judgement, server/lane_compliance_service.py worker, "
        "cli/app/roster wiring) stays with the existing Fleet localization and server owners; no "
        "new owner, the site-map web/server split plan and +150 allowance remain unchanged. "
        "Previously re-judged at 42546 on 2026-10-08: D-509 display readback and D-513 start place "
        "and camera rotation stay with the Fleet server and site-map web owners. "
        "Previously re-judged at 42376 on 2026-10-07: D-499 link status uses the existing "
        "Fleet gather and display owner; D-493 stale-age rows use that same snapshot. The "
        "site-map web/server split plan and +150 allowance remain unchanged. "
        "Previously re-judged at 42184 on 2026-10-07: D-407 episode recording and routes, D-493 "
        "stale-state age, D-501 shared console tabs, camera map inspection and development console "
        "entry remain with their existing Fleet server and web owners. Keep the site-map web/server "
        "split in docs/plans/2026-10-07-fleet-site-map-web-server-seam.md and the +150 allowance. "
        "Previously independently re-judged at 41764 on 2026-10-07 (code-reviewer agent; judged at 41719 before "
        "the review fixes). Since 41014 the package grew 750 lines: main's own +112 (within the allowance) "
        "and the D-494 6 teach slice +638 — fleet/routing/teach.py 129 (pure point keeping, RDP, end "
        "candidates, edge append), server/teach_service.py 216, server/teach_routes.py 91, "
        "web/site-map-teach.js 119, site-map-model.js +35, site-map.html +27, site-map.js +7, app.py +4, "
        "site_map_store.py +4 (record_event), site_map_routes.py +4 net (shared invalid_errors), "
        "static_routes.py +1, site-map.css +1. Inside the server owner of "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md and the site-map web owner; no new owner. "
        "+150 allowance unchanged. "
        "split: independently re-judged at 41014 on 2026-10-07 (security-reviewer agent). Two components "
        "already judged on different bases, now combined after merging main. (1) main's D-494 M2 "
        "contracts 1-3, judged at 39679 (localization/map_pose.py, server/map_pose_service.py, "
        "console_view.py TripCaps, the app.py trip-caps closure). (2) The branch's D-494 5 trip loop, "
        "judged at 40348 on the 38952 base (+1396): fleet/server/trip_runner.py (at its 600 cap; the next"
        " change splits it), trip_ports.py, trip_guard.py (TRIP_ROBOT_BUSY guard; every operator stop "
        "ends the trip after the stop is sent), routing/execute.py, trip_routes.py, the site-map trip "
        "panel. Replacing duplicate types with main's MapPose/TripCaps took trip_ports.py down 36 lines, "
        "so the total (41014) is below the sum of the parts (41039). Inside the server owner of "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md and the site-map web owner; no new "
        "owner. +150 allowance unchanged. "
        "split: independently re-judged at 40348 on 2026-10-07 (D-494 5 safety re-review: the "
        "security-reviewer agent judged the growth justified). Since 40110 the package grew 238 lines, "
        "all review-driven: fleet/server/trip_guard.py +117 (every operator stop — cancel, cancel-all, "
        "estop, line-follow OFF, stuck ABORT/MANUAL — ends the trip after the stop is sent; "
        "TRIP_ROBOT_BUSY on goal/formation/stuck motion), trip_ports.py +61 and routing/execute.py +35 "
        "(moved out so trip_runner.py stays at 599 of its 600 cap; its next change splits it), "
        "console_view.py +14, console_routes.py +11, app.py +5, stuck_resolver_loop.py +2, console.py -6."
        " Inside the server owner of docs/plans/2026-10-07-fleet-site-map-web-server-seam.md; no new "
        "owner. +150 allowance unchanged. "
        "Previously independently re-judged at 40110 on 2026-10-07 (D-494 5 review: the reviewer judged "
        "the growth justified). Since 38952 the package grew 1158 production and web lines for the "
        "server trip loop: fleet/server/trip_runner.py 600 (start checks, state machine, CORE "
        "junction protocol, halts, 0.5 s loop), trip_ports.py 171 (ports, fleet.trip config), "
        "routing/execute.py 82 (pure executability rules), trip_routes.py +32 net, site_map_store.py "
        "+35, app.py, cli.py, transport.py, the TRIP_ROBOT_BUSY guard (console.py +6 inside its 1198 "
        "verdict, task_dispatch_routes.py, lane_route_routes.py), and the site-map trip panel "
        "(site-map.js, site-map-model.js, site-map.html). The loop is new server files beside the "
        "routing package, inside the server owner of "
        "docs/plans/2026-10-07-fleet-site-map-web-server-seam.md; the panel stays in the site-map web "
        "owner. No new owner. +150 allowance unchanged. "
        "Main: independently re-judged at 39679 on 2026-10-07 (security-reviewer agent). Since 38952 the"
        " package grew 727 production and web lines. D-494 M2 contracts +634: localization/map_pose.py "
        "+377 (pure map-pose tracker beside trust.py and arbiter.py in fleet/localization), "
        "server/map_pose_service.py +154 (trip-only service beside localization_service.py), "
        "console_view.py +33 (TripCaps), app.py +32 (incl. the trip-caps closure moved out of "
        "console.py), cli.py +18, console.py +10, trip_routes.py +6, ingest_routes.py +4. Site-map, Cell "
        "and D-493 map-first web +93 net: site-map.js +58, cell.js +17, map-view.js +15, console.js +13, "
        "site-map.css +9, cell.css +7, site-map-model.js +5, site-map.html +3, start-point-view.js +1, "
        "less index.html -16, styles.css -12, roster.js -5, connection-view.js -2. Tests are exempt. No "
        "new owner: the map pose sits in the existing localization owner, trip caps in the capability "
        "display. The first web/server seam stays docs/plans/2026-10-07-fleet-site-map-web-server-seam.md"
        " (owner fleet), and map_pose_service.py joins the B2 server-subpackage obligation beside "
        "localization_service.py. The split is not done here. +150 allowance unchanged. Previously "
        "independently re-judged at 38952 on 2026-10-07. "
        "Since 37182 the package grew 1770 "
        "production and web lines in the existing site-map owners: site-map.js +238, site_map_store.py +198, "
        "routing/graph.py +168, site-map-model.js +153, site_map.py +151, routing/trip.py +149, "
        "routing/planner.py +140, trip_routes.py +113, site_map_routes.py +92, routing/cost.py +82, "
        "site-map.html +78, routing/snap.py +61, site-map.css +43. Tests are exempt. No new owner. "
        "The first web/server seam is docs/plans/2026-10-07-fleet-site-map-web-server-seam.md "
        "(owner fleet): site-map page assets stay the web owner, and the site-map routes, store, and "
        "routing package stay the server owner. The split is not done here. +150 allowance unchanged. "
        "Previously independently re-judged at 37182 on 2026-10-07 after the 2026-10-06 Fleet UI/UX series (Cell actions, "
        "states, failures and E-stop card in cell.js/css/html +167; console/install/formation feedback +69) "
        "and D-484 field_boundary sighting sources (sightings, sightings_config, vision-view +43) added 293 "
        "lines. Each change sits in its existing page or server owner; no new owner appeared. "
        "+150 allowance unchanged. "
        "Previously re-judged at 36645 on 2026-10-06 after integrated map camera display, "
        "lamp identity routing, and transport evidence added 201 lines; the camera binding "
        "moved from console.js into its map view to keep the web file below 800 lines. "
        "The existing B2 server/UI split plan and +150 growth allowance remain in force. "
        "Previously independently re-judged at 36444 on 2026-10-05 for Fleet CAP-001 support: "
        "101 production/web lines from this patch and 109 from integrated main above 36234. "
        "Transport, formation lifecycle, console gather/dispatch and UI readiness keep their "
        "existing owners. Retain B2/server/UI split obligations and every threshold, including "
        "package +150; see docs/validation/fleet-navigation-support-2026-10-05.md. "
        "split: independently re-judged at 36234 on 2026-10-05, after moving profile dispatch "
        "to canonical learning contracts. Since measured35878: evidence bundle106, receiver97, "
        "trusted discovery88, reservations33, segment store23, styles16, roster-8, setup1. "
        "Receiver, transport, reservation and UI owners stay separate; retain B2 server/UI "
        "split obligations and all 600/800, 1000 zero-growth and package150 allowances. "
        "See docs/validation/line-release-2026-10-05/result.md. "
        "D-426 T4 re-judged at 35878 — segment grants/definitions add 272 "
        "(traffic_reservations.py + segment_store.py) with a dedicated contract suite; "
        "no command owner changes; the release path still requires fresh exit "
        "observation plus a terminal result. "
        "split: independently re-judged at measured35606 on 2026-10-05 after enrolled "
        "TLS transport and required feature-builder extraction; CLI586 removes its stale "
        "file verdict. Previous35137 + concurrent80 + TLS364 + builder25. Retain the "
        "B2/UI queue and all thresholds/allowances; see docs/validation/"
        "d456-enrolled-tls-integration-2026-10-05/README.md. "
        "Independently re-judged after concurrent start-point integration at "
        "35137 on 2026-10-05: 314 lines above34823 (134 reference backend,172 UI,8 "
        "composition/static), plus earlier31 route extraction above34792; reference "
        "coordinates never initialize pose or issue motion. Retain the B2/UI split "
        "queue, all file thresholds and package150 allowance; see docs/validation/"
        "d456-main-start-point-integration-2026-10-05/README.md. "
        "D-456 independently re-judged at measured 34792 on 2026-10-05: "
        "camera peer owners add 926 lines (756 backend, 135 web, 35 existing wiring); "
        "bounded sibling modules keep app589 and console1159 unchanged. Retain "
        "the Fleet server/UI split queue and all file/package growth allowances; "
        "see docs/validation/d456-fleet-camera-peer-review-2026-10-05/README.md. "
        "D-463 independently re-judged at measured 33866 on 2026-10-05: lane "
        "math is a bounded sibling module, routes retain the existing dispatcher and "
        "console retains its gather/trust accessor. Existing B2/UI split queue and "
        "+150 package allowance stay unchanged; see docs/validation/"
        "d463-route-independent-review-2026-10-05/README.md. "
        "D-457 re-judged at 33657 after integration with main 754c20ee3; bounded "
        "display-only calibration, tracking routes/matcher and UI coordinates add 1188 to Fleet. "
        "The composition root stays below 600 after main's extraction; no command owner changes. "
        "split: independently re-judged 2026-10-04 at measured 32469 after main 387b19841: "
        "307 since the previous 32162 consists of prior integration 7, D-455 meet/resolver "
        "181, central read projection/routes/CLI 123, app/worker extraction -11 and web 7; "
        "the incoming cross-module capture tool is correctly placed under root tools, outside Fleet; it remains UX HOLD, not accepted screen evidence. "
        "Retain B2 server subpackage and UI resource migration obligations, owner boundaries, "
        "600 production/800 web limits, 1000 zero-growth tier and +150 package allowance. "
        "Source accounting and independent review are recorded in "
        "docs/validation/network-peer-discovery-2026-10-04/main-integration-checkpoint.md. "
        "Previously re-judged 2026-10-04 at 32162 after integrating main 2ad047602 with D-452: "
        "incoming main counts 31786, including focused meet subpackage 653 and existing "
        "resolver/loop/transport wiring 135 beyond its 30998 verdict; the approved "
        "Cell checkpoint/editor delta 377 and D-452 delta 376 both retain their owners. "
        "The integrated package adds no new command publisher or large file; app.py is 599. "
        "Independent count/owner review retains B2 subpackage and UI migration obligations, "
        "600 production/800 web limits, 1000 zero-growth tier and +150 package allowance. "
        "Previously re-judged 2026-10-04 at 30997 for D-452 after independent source review: "
        "the +376 lines comprise focused catalogue/directory/routes owners 170, bounded wiring 24, "
        "peer-picker owner 128, existing presentation wiring 51 and Cell return link 3. "
        "app.py is 599; new metadata owners do not publish commands or replace enrollment. "
        "Expiry/conflict/auth/lifetime and three-width browser regressions exercise these seams. "
        "Keep the flat-server subpackage migration obligation, 600 production/800 web file limits, "
        "1000-line zero-growth tier and +150 package allowance unchanged; implementation and "
        "evidence are in docs/plans/2026-10-04-network-peer-discovery.md. "
        "Previously re-judged 2026-10-04 at 30998 for manual sheet checkpoints: the existing SQLite Job owner "
        "keeps transactional barriers and extracts bounded checkpoint validation and read projection modules. "
        "The Console adds explicit handling and read-only wait instructions; no access-confirmation provider, "
        "ROS publisher or device command owner is added. Store remains 959 lines below its 974 growth ceiling; "
        "schema aggregation stays 1319. Independent process and guard reviews retain the split plan and +150 allowance. "
        "re-judged 2026-10-04 at 30621 after main integration for D-450: bounded Cell document store/routes and Console "
        "assets reuse existing proposal and execution owners; app composition remains below 600 lines. "
        "Independent review preserves the subpackage/UI migration plan and existing +150 allowance. "
        "server HTTP boundary, console, signals and the mission-control stores are separate owners "
        "today; re-judged 2026-10-03 at 28001 for D-413 internal Cell producer authentication: bounded "
        "schema, environment credential registry and evidence service are separate modules; goal completion "
        "retains its existing journal owner and atomically fences the verified terminal event. No new HTTP "
        "or device owner is added. Existing split verdict and +150 growth allowance remain unchanged; "
        "today; group them into subpackages rather than one flat server/ tree (B2); owner fleet, unscheduled "
        "(re-judged 2026-09-29 at 11164 after mission_store joined the server tree; re-judged 2026-09-30 at "
        "12419 after the D-361 enrollment register, roster and service joined as their own modules, and "
        "at 12574 after the D-361 review fixes; re-judged 2026-09-30 at 13187 after main's goal-evidence "
        "contracts and stores merged in; re-judged 2026-09-30 at 14260 after D-357/D-358 feedback "
        "contracts, dispatcher, stateless adapter and bounded outbox modules/tests were added; re-judged "
        "at 14616 after atomic candidate fencing and linked-successor regression tests; re-judged at 15000 "
        "after the injected outbox consumer, trusted post-action Vision reader, and deadline/egress fence "
        "coverage joined; re-judged 2026-09-30 at 18967 under D-362 — the package total now counts web "
        "assets (server/web console js/css/html); re-judged 2026-09-30 at 19243 after D-362 P0-1 "
        "executed the app.py router split (app.py 1556 -> 476 plus mission/task_dispatch/intent/"
        "console/ingest/static route modules and site_auth) — the flat server/ tree still wants the "
        "B2 subpackage regroup; re-judged 2026-10-01 at 20399: the same-host OMX phase receipt "
        "projection joined the existing Fleet mission journal and read-only status surface (19468), and the "
        "D-375 console map-fit overlay joined as its own modules (server/site_lanes.py, web/map-fit.js pure, "
        "web/map-fit-view.js DOM, each under the D-362 budget); verdict unchanged; re-judged "
        "2026-10-01 at 20655 after the D-359 theme/palette, D-375 map-fit view and D-391/D-370 "
        "site-link fixes landed in console and transport, then at 21476 when D-341 camera pairing "
        "joined as its own modules (server/pairing.py state, pairing_store.py digests, "
        "pairing_routes.py) plus tests (21871 once merged with main's other console work); app.py only "
        "gained the install call; verdict unchanged; re-judged again when the pairing security "
        "fixes and the console camera-approval section (web/camera-pairing.js under the D-362 "
        "web budget, its node and host tests) joined; verdict unchanged; re-judged "
        "2026-10-01 at 23166 (main had reached 22797 with D-392 work) after the robot-address drift "
        "audit joined as its own modules (server/address_drift.py pure classifier, web/address-drift.js "
        "pure copy) plus its route in ingest_routes.py and tests, then at 23237 after the "
        "review fix made move-address re-pair with the screen code (enrollment.py) and dropped bulk "
        "move; verdict unchanged. "
        "Re-judged 2026-10-01 at 23543 when the D-395 localization arbiter joined as its own pure "
        "subpackage (fleet/localization: cues.py, arbiter.py); verdict unchanged. "
        "Re-judged 2026-10-01 at 24204 when D-395 Phase 2 lane C joined: the service loop as its own "
        "server module (server/localization_service.py), its pure monitor/ladder and pose trust in "
        "fleet/localization (service_logic.py, trust.py), the client routes in transport.py and a pure "
        "web/localization-badge.js, plus tests; verdict unchanged. "
        "Re-judged 2026-10-02 at 24403 when D-395 P2-7 joined (the ladder sends missions from "
        "server/localization_service.py, the pre-mission traffic hold in console.py, pure "
        "MISSION_LIMITS/square_target in fleet/localization, the mission client in transport.py) on "
        "top of main's D-405/D-406 console work; verdict unchanged. "
        "Re-judged 2026-10-02 at 24565 when the service learned "
        "to stay quiet during a CORE mission (server/localization_service.py, the mission-status "
        "client in transport.py); verdict unchanged. "
        "Re-judged 2026-10-02 at 24945 when D-410 split the console into two documents "
        "(web/install.html + web/install.js entry now own device enrollment and camera "
        "calibration; index.html/console.js shed the install wiring); verdict unchanged. "
        "Re-judged 2026-10-02 at 25653 after D-407 line-stuck mediation web module and "
        "the operate/install split settled; verdict unchanged. "
        "Re-judged 2026-10-02 at 25494 (from 24587 on base 7e577452) when the D-407 Fleet side joined "
        "as its own modules: server/line_stuck.py (stuck board + answer record), two routes in "
        "console_routes.py, web/line-stuck.js (panel), the decision client in transport.py, and "
        "tests (~175 prod + ~370 web + ~360 test lines); console.py did not grow. A parallel D-395 "
        "branch reported 25011 against the older 24565 pin, so merging both needs one more re-judge; "
        "neither adds a new owner to the flat server/ tree beyond its own module; verdict unchanged. "
        "Split remains unscheduled (docs/plans/2026-09-30-er2-mission-feedback-loop.md). "
        "Re-judged 2026-10-02 at 26340 after D-413 Task 4 added a separately owned ordered Cell Job "
        "journal, proposal finalization and service/operator admission path (docs/plans/"
        "2026-10-02-platform-architecture-v02-migration.md); these remain Fleet-owned durable records, "
        "while device dispatch and manipulation ownership stay in later tasks. This re-judgment resets "
        "the package growth baseline; the existing +150 allowance still blocks silent growth. "
        "Re-judged 2026-10-02 at 27134 (main d5b3bd10 at 26498) when D-421 cancel-all joined as its "
        "own modules: server/cancel_all.py (fanout, per-robot verdict, dispatch-overlap fence) and "
        "server/cancel_all_store.py (durable window record and attempt tags read by the CORE event "
        "projection in task_results.py), one route, the hub swarm-cancel scatter and ~35 console.js "
        "lines; console.py did not grow and task_store.py stays under its 1060 ceiling. "
        "Re-judged 2026-10-02 at 27303 after durable Mission goal-success proof and CellJob startup "
        "fencing: completion requires the matching persisted Action outcome, transfer submission "
        "atomically marks ownership DISPATCHING, and gateway startup holds obsolete authority. "
        "These remain Fleet journal/admission responsibilities under the D-413 migration plan; "
        "CellJob dispatch/reconciliation composition remains open. Full Fleet regression 1425 "
        "passed/7 skipped; split verdict and the +150 growth allowance remain unchanged. "
        "Main briefly carried a parallel opt-in CellJob dispatcher (27684); the 2026-10-03 C4b merge kept "
        "the StepJobDispatcher design and removed it. Re-judged 2026-10-02 at 27870 (C4b G3/G5, D-403 §3/§5/§7): the production Cell Job compiler "
        "adapter (server/cell_compiler.py), the per-kind step dispatch table (server/step_action_kinds.py) "
        "and the step-ledger dispatcher (server/step_dispatcher.py) joined as their own modules, the "
        "deployment_profile gate in app.py; verdict unchanged. Re-judged 2026-10-03 at 28160 (C4b 1b): "
        "the Cell Job claim lifecycle (HELD phase, latch hook), GetAction readback with backoff and the "
        "operator recovery routes (server/cell_job_routes.py); verdict unchanged. Re-judged 2026-10-03 at "
        "28340 (C4b 1c): restart/stop/404 exits, release_before_send, receipt notes, bounded round-robin "
        "ticks and the identity cache, all inside the existing ledger/dispatcher modules; verdict unchanged. "
        "Re-judged 2026-10-03 at 28734 on merging main: main's parallel Cell dispatcher/readback/goal mixins were "
        "removed and its public Cell goal ingress (registry, routes, service) kept and rewired to the "
        "stored item_at_pose predicate; verdict unchanged. Re-judged 2026-10-03 at 29017 for D-425 "
        "Task 3: both Console documents and their existing panels bind cancellation, timers, handlers "
        "and frame subscriptions to web_common page scopes. No Fleet backend or command policy is "
        "added. UI assets temporarily still count under fleet; Task 9 in "
        "docs/plans/2026-10-03-app-ownership-shared-transport-and-layout-migration.md moves their "
        "source ownership into ui/console with installed-resource acceptance. The server subpackage "
        "split remains open and the existing +150 package allowance stays unchanged"
        " Re-judged 2026-10-04 at 29264 after independently reviewed D-443 signal supervision "
        "and D-442 U3 named-operator owner recovery: isolated HTTP routes reuse the existing "
        "bounded UDS transport; OMX retains HOLD, local-stop and journal fencing. No new motion "
        "publisher or owner. Existing split plan, budgets and +150 allowance remain unchanged."
        "; re-judged 2026-10-04 at 29657 for D-438 phase 1: the stuck resolver is two new focused "
        "modules (stuck_resolver.py pure core, stuck_resolver_loop.py async loop) and the shared gather "
        "lives with the console routes it serves. Re-judged at 30063 after integrating the migrated "
        "main: the incoming package was 29806; preserved signal routes/supervision/UI add 182, local "
        "stop transport and owner recovery add 94, expiry worker adds 13, named-operator dispatch "
        "adds 5 and console wiring adds 2, while shared app/console composition removes 39. These "
        "are existing focused safety owners, not a duplicate command path. Independently counted "
        "both parents and the union; the B2 server grouping remains open and +150 is unchanged. "
        "Re-judged 2026-10-06 at 36889 after D-473 added the development-session connection gate to the Fleet CLI and the console auto-session bootstrap (244 lines above 36645, all in cli.py and console.js, see their verdicts). No new command or motion owner; the B2 server/UI split and the +150 allowance stay unchanged",
    ),
    "fleet/fleet/cli.py": (
        705,
        "accept: measured at 705 after moving fleet.traffic zone, signal and authority YAML parsers "
        "to traffic/config.py. The CLI keeps entrypoint and session argument wiring; extract its "
        "connection-mode/session parsing on further growth. Previously measured at 608 after D-473. "
        "The 600-line ceiling and allowance are unchanged",
    ),
    "ui/face/emotion/info_screen.py": (
        602,
        "accept: the LCD info-screen renderer crossed 600 lines (measured 602) when the 2026-10-06 "
        "driving battery alert contrast fix added 4 lines. It keeps one role, payload to panel image, "
        "with per-state renderers that share the font, alarm and fit helpers. Owner face/emotion. "
        "Follow-up split: move the boot/AP-QR renderers (boot_lines, ap_qr, _draw_qr, render_boot) into "
        "their own module when the file next grows. Budgets and allowance unchanged",
    ),
    "fleet/fleet/server/web/console.js": (
        832,
        "accept: D-473 added the development-session auto-session bootstrap to the console page (measured 832 against the 800 web ceiling). It belongs to the existing console page-scope owner and adds no second transport; follow-up split: move the auth/session bootstrap out of console.js into its own web asset with installed-resource parity checks. Budgets and allowance unchanged",
    ),
    "fleet/fleet/server/cell_job_store.py": (
        824,
        "accept: one owner (2026-10-02, C4b G3) for the ordered step ledger: Job, step, claim phase and "
        "event rows change in one SQLite transaction (submit promotes claims, outcomes return or pin "
        "them, hold and replay checks share the event key). Split the read model (_get/next_job) out "
        "if a second step kind (D-420 Pinky multi-step) adds more than its kind-table entry. "
        "Re-judged 2026-10-03 at 824 (C4b 1b): the claim lifecycle (HELD, site-stop hook), readback "
        "from HOLD and operator resume/cancel joined because each changes Job, step and claim rows in "
        "one transaction. Split: move resume/cancel/hold_for_site_stop into a recovery module when "
        "D-420 v2 adds the CANCELLED status (schema change), before any further growth",
    ),
    "fleet/fleet/server/proposal_store.py": (
        730,
        "accept: one owner (the durable non-executable candidate ledger — proposal create, the fenced ER2 "
        "feedback replan candidate, recoverable resolution and the model tool-call result journal share one "
        "SQLite file, one schema/migration block and BEGIN IMMEDIATE transactions that must commit "
        "together with the Mission draft in finalize_resolution), ROS-free, host-testable (X5). Crossed "
        "600 on 2026-10-01 (557 -> 730) when atomic candidate fencing (3a19b560) and the canonical model "
        "tool-call journal (1e519cca) joined; the journal (fleet_model_tool_call_results, "
        "begin/complete/mark_unknown) is the only separable seam, so revisit it as a split if the store "
        "grows past 800",
    ),
    "fleet/fleet/server/enrollment.py": (
        956,
        "accept: re-judged 2026-10-09 at 956 (independent re-judge, critic agent; was 932 author's record) when "
        "D-555 hub link issue/revoke joined: it reuses the same register row, TLS fence and enrolled "
        "client, so it stays with that state machine. The next D-555 growth first moves the hub link "
        "(link_hub, unlink_hub, _hub_*, _clear_robot_link) into its own module (e.g. enrollment_hub.py); past HARD_TIER (1000) it must. Before: one owner (D-361 robot enrollment — exchange, binding, pinned-address gate, unenroll and "
        "pending logout share one state machine over the register), ROS-free, host-testable (X5); "
        "re-judged 2026-10-01 at 664 when move-address became a screen-code re-pairing on the same "
        "exchange and binding check",
    ),
    "vision/rosy_vision/ingest.py": (
        671,
        "accept: one owner (the rosy-overhead/1 receive endpoint — handshake, per-source connection "
        "lifecycle, latest-frame store and the direct preview/proposal reads share one connection map); "
        "crossed 600 on 2026-10-01 when D-341 paired-credential admission and revoke closing joined the "
        "same handshake and connection map (the digest store and sync thread live in pairing_sync.py). "
        "ROS-free, host-testable (X5)",
    ),
    "fleet/fleet/server/mission_store.py": (
        887,
        "accept: one owner (the Fleet Mission SQLite ledger — missions, attempts, progress snapshots, "
        "fenced device phase snapshots, and their transitions in one transactional store), ROS-free, "
        "host-testable; correlated task evidence stays in task_store/task_results (X5). Re-judged "
        "2026-10-01 at 887 after idempotent per-attempt phase projection joined the Mission event transaction",
    ),
    "foundation/core_common/protocol/schemas.py": (
        1_344,
        "accept: independently re-judged at 1344 (2026-10-09, read-only safety reviewer) for D-531 P1: "
        "one RouteContext import and two optional LineFollowStatus fields; the bounded model and "
        "validation live in protocol/route_context.py. No new runtime owner or envelope version, and "
        "the zero-growth allowance remains. "
        "Previously independently re-judged at 1341 (2026-10-09, read-only critic agent) for D-541 step 1: "
        "+1 line, one import of TripLeaseFields from core_common/protocol/trip_lease.py, which holds the "
        "lease models and the absent-key serializer; StateSnapshot is defined here, so the base-class swap "
        "is the only hook. Additive, no envelope version change. Zero-growth allowance remains. "
        "Previously independently re-judged at 1340 (2026-10-08, read-only critic agent) for D-520 step 1: "
        "+2 lines, one re-export import and the optional LineFollowStatus.arc field (default None). The "
        "arc record models live in core_common/protocol/line_arc.py and the field cannot move because "
        "LineFollowStatus is defined here. Additive, no envelope version change. Zero-growth allowance "
        "remains. "
        "Previously independently re-judged at 1338 on 2026-10-08 (critic agent, read-only) for "
        "D-507 7: one optional LineFollowStatus.lane_return_containment Literal['contained', "
        "'unknown'] field (default None) with its two-line comment beside the D-407 stuck and D-494 "
        "junction fields; written only by line_follow/recovery/lane_return_decision.py, documented in "
        "the API & Protocol Reference and D-507. Additive, no envelope version change or runtime "
        "owner. Zero-growth allowance remains. "
        "accept: independently re-judged at 1335 on 2026-10-07 (code-reviewer agent, read-only) for "
        "D-494 4 / D-495: one LineJunctionStatus model and a defaulted LineFollowStatus.junction field "
        "(always present, state idle) beside LineStuckStatus; additive, no envelope version change or "
        "runtime owner. Zero-growth allowance remains. "
        "accept: re-judged at 1322 on 2026-10-07 for D-494 2: one optional StateSnapshot.odom_pose "
        "field; the OdomPose model lives in protocol/localization.py and joins the existing import "
        "line. No envelope version change or runtime owner. Zero-growth allowance remains. "
        "accept: re-judged at 1321 on 2026-10-06: six lines add the bounded display-only "
        "LampIdentifyRequest to the existing public schema owner; no new protocol version or "
        "runtime owner. Zero-growth allowance remains. D-457 re-judged at 1315 after "
        "current schema extraction: one bounded OverheadDetectionsPayload re-export; model lives in "
        "overhead_detections.py, display-only, no version pin or runtime ownership change. "
        "accept: re-judged 2026-10-04 at 1319 after main's model extractions: Cell request models live in protocol/cell_app.py; only "
        "two public re-export lines join the canonical schema entrypoint. Zero-growth allowance unchanged. "
        "the D-18 single contract source — every envelope, event and capability model in one "
        "importable place; re-judged 2026-10-03 at 1240 for the D-413 public CellGoalEvidenceSubmission "
        "re-export, then at 1245 after combining main's D-422 body-stop fields with that one-line export. "
        "Re-judged 2026-10-03 at 1324 after retaining D-418 models and two bounded D-432 access-contract re-exports; models live in access.py. "
        "re-export. Bounded Cell models live in protocol/cell_goal_evidence.py, with no runtime ownership "
        "or new version pin; the existing zero-growth allowance remains unchanged. "
        "importable place; per-domain schema files would fork the version pin that "
        "test_protocol_version_alignment guards. Re-judged 2026-09-30 at 1000 lines after the bounded "
        "Mission feedback scope/context/tool-result contracts were added; re-judged 2026-09-30 at 1001 "
        "under the D-362 zero-allowance tier; re-judged 2026-09-30 at 1002 when the pilot branch added "
        "LineFollowStatus.clearance_m (D-344 §11, one field); re-judged 2026-10-01 at 1067 for the "
        "bounded UDS v2 phase receipt and read-only Mission phase progress schemas, which remain in the "
        "single contract source guarded by protocol alignment. The hard-tier zero-growth rule prevents "
        "silent expansion. ROS-free, host-testable (X5); re-judged 2026-10-01 at 1092 for the calibration-session RobotActivity/ActivityOwner models on robot state (still accept); re-judged 2026-10-01 at 1095 for the D-395 StateSnapshot.localization field and its import — the models live in protocol/localization.py (still accept)"
        " Re-judged 2026-10-01 at 1119 lines: D-400 SafetyPolicyStatus joins the state contract; "
        "the single contract source still outweighs a split (same verdict)."
        " Re-judged 2026-10-01 at 1137 lines: the typed shadow sub-blocks (ShadowRecordRef, "
        "ShadowEvalStats) joined SafetyPolicyStatus; same verdict."
        " Re-judged 2026-10-02 at 1153 lines: D-407 LineStuckStatus (the typed stuck block on "
        "LineFollowStatus, v1.74) joined; the logic stays in line_follow/stuck_recovery.py; same verdict."
        " Re-judged 2026-10-02 at 1239 for D-413 Task 4's additive FleetCellTransferGrant, "
        "CellTransferPayload, and CellTransferPose wire contracts; the single protocol source remains "
        "authoritative and this establishes a new zero-growth baseline."
        " Re-judged 2026-10-02 at 1244 for D-422's three optional LineFollowStatus fields "
        "(body_gap_m, stop_gap_m, clearance_source); the logic stays in line_follow/body_stop.py; "
        "same verdict."
        " Re-judged 2026-10-03 at 1321 after merging main: the D-418 robot SSH access models (host keys, "
        "managed keys, temporary password status with lock_pending; API v1.89) on top of D-422; same verdict."
        " Re-judged 2026-10-04 at 1322: bounded lane selection/readback models were split into "
        "protocol/lane_perception.py; one re-export preserves the single public schema import point.",
    ),
    "fleet/fleet/server/app.py": (
        756,
        "accept: re-judged at 756 on 2026-10-08: Service Control (D-524) adds one route install; "
        "the allowlist and helper stay in host_control.py. +150 allowance measured from 756. "
        "Previously: one existing composition/lifespan owner wires bounded route siblings; "
        "camera identity/approval and calibrated reference persistence remain in their "
        "dedicated modules. Independent review confirmed both mounts and cleanup, "
        "no CORE/pose initialization/motion/grant authority change. Keep the600 threshold "
        "and normal150 regrowth allowance; see docs/validation/"
        "d456-main-start-point-integration-2026-10-05/README.md",
    ),
    "fleet/fleet/server/task_store.py": (
        1060,
        "accept: keep SQLite task, history, lease, reservation, and dispatch-claim transactions together; "
        "correlated CORE event projection lives in task_results.py. Re-judged 2026-09-29 at 1014 lines after "
        "durable dispatch resource claims moved into the same store owner (docs/plans/"
        "2026-09-29-fleet-mission-control-arbitration-implementation.md); re-judged 2026-09-30 at 1060 "
        "under the D-362 zero-allowance tier — verdict unchanged",
    ),
    "perception/control/safety/node.py": (
        795,
        "accept: legacy comparison-graph publisher pinned by test_module_separation; no new work (X3)",
    ),
    "fleet/fleet/swarm/session.py": (
        616,
        "accept: independently reviewed on 2026-10-05: one formation lifecycle owns planning, "
        "arming, relay opening, stop and rollback. Sixteen CAP-001/reservation lines retain "
        "that lifecycle; transport and assignment policy stay separate. Capability and ARMING "
        "regressions are host-testable. Retain the normal +150 allowance and every threshold; "
        "see docs/validation/fleet-navigation-support-2026-10-05.md",
    ),
    "fleet/fleet/server/console.py": (
        1248,
        "accept: re-judged at 1248 on 2026-10-09 after merging D-526 with the degraded-link row: "
        "a late robot answer is shown as degraded, not offline (online stays false), and D-526 adds an "
        "alarm_sources hook so the tether watch can raise TETHER_STOP_FAILED; neither changes a goal, stop "
        "or admission path. Previously 1243 (degraded link) and 1234 (D-526). D-526 adds an alarm_sources hook so the "
        "tether watch can raise TETHER_STOP_FAILED beside the held-robot alarm; five lines, "
        "no goal, stop, or admission path changed. The zero growth allowance remains. "
        "Previously re-judged at 1229 on 2026-10-09: D-535 records link_reason beside the "
        "existing link class on a gathered robot row. No goal, stop, or admission path "
        "changed. The zero growth allowance remains. Previously re-judged at 1225 on "
        "2026-10-07: D-499 adds a read-only link class "
        "to each gathered robot row using the existing address-status snapshot; provider "
        "failure falls back to an empty status map. No goal, stop, or admission path changed. "
        "The zero growth allowance remains. Previously re-judged at 1202: D-493 records each gathered state observation "
        "time in this owner's robot row for the stale-state display; keep zero growth allowance. "
        "Previously independently re-judged at 1198 on 2026-10-05: CAP-001 presentation cache "
        "and live dispatch fences add 39 lines beside this owner's mutable roster and goal "
        "bookkeeping; transport still owns capability interpretation. Client replacement and "
        "formation races are host-tested. Retain zero growth allowance; see "
        "docs/validation/fleet-navigation-support-2026-10-05.md. "
        "accept: re-judged at measured 1159 on 2026-10-05 for D-463: the fresh map "
        "pose accessor reads this owner's gather/trust tables; lane geometry stays "
        "in lane_route.py. Zero growth allowance stays; independent source review "
        "and 11 host route tests recorded in docs/validation/"
        "d463-route-independent-review-2026-10-05/README.md. "
        "One owner (FleetConsole gather/scatter), host-testable (X5). Re-judged 2026-09-30 at 1013: "
        "D-361 roster mutation and pinned-address holds change the gather/traffic tables in place, so they "
        "stay with their owner; the roster policy itself lives in roster.py; re-judged 2026-09-30 at 1021 "
        "under the D-362 zero-allowance tier — verdict unchanged; re-judged 2026-10-01 at 1063 for D-395 "
        "P2-2: untrusted poses change the same gather/traffic tables (_seen, _queued) in place, so the "
        "LOCALIZATION_UNTRUSTED queue reason stays with its owner while the trust rules live in "
        "fleet/localization/trust.py — verdict unchanged; re-judged at 1076 when the lane C review queued an "
        "unlocalized mover instead of dispatching it (same queue table) — verdict unchanged; re-judged "
        "2026-10-02 at 1096 for D-395 P2-7: the pre-mission traffic hold cancels and queues goals in "
        "the same _goals/_claims/_queued tables (hold_for_localization) — verdict unchanged; re-judged "
        "2026-10-02 at 1111 when the P2-7 review made the hold also cancel crossing yields "
        "(_yielding) and stop a formation near the mover — same tables, verdict unchanged; re-judged "
        "2026-10-02 at 1138 for D-395 S2 Finding 1: the lapsed-robot null grace (_loc_null_since) is "
        "kept beside _seen/_trusted, which it updates in the same gather — verdict unchanged. "
        "Re-judged 2026-10-04 at 1154: D-447 selects a fresh hub snapshot before REST in the "
        "same gather owner and records source provenance; test_server_gather_source.py checks "
        "fresh/stale/disconnected fallback. Re-judged 2026-10-05 at 1159 for D-463: "
        "trusted_map_pose is another fresh read in the same gather owner (map-frame "
        "LOCALIZED check feeding the lane route); verdict unchanged. "
        "The zero-growth allowance remains unchanged.",
    ),
    "perception/control/sensing/perception/lane.py": (
        765,
        "accept: one concern (lane/IR line detection), ROS-free pure functions and trackers, host-testable (X5); "
        "the ground-geometry lane keeper already lives apart in lane_keep.py (D-364)",
    ),
    "core/gateway/core/bridge/ros_bridge.py": (
        799,
        "accept: one CORE ROS executor integration point for publishers, subscriptions, lifecycle wiring, and "
        "service/action clients; extracted policy and callback logic lives in core/bridge modules, and "
        "timer/bridge behavior is covered by test_bridge_timers.py and test_bridge_reconcile.py. Re-judged "
        "2026-10-01 at 606 after D-385 mode-to-emotion handoff wiring; 2026-10-03 at 799 after D-433 "
        "(face-inputs hand-over on the 5 Hz power tick; payload and cadence live in bridge/display.py "
        "and core_common.face_screen, covered by test_face_inputs.py)",
    ),
    "perception/control/sensing/perception/lane_bev.py": (
        611,
        "accept: one owner (LaneEdgeFollower + its bird's-eye helpers), ROS-free, host-testable (X5)",
    ),
    "core/events/core_events/events/audit.py": (
        745,
        "accept: one owner (svc.audit / FileAuditLog), ROS-free, covered by middleware/core/events/test/test_audit.py; "
        "about half the lines are the rationale comments the append/compaction/quarantine rules rest on (X5)",
    ),
    "core/services/core_features/line_follow/manager.py": (
        605,
        "accept: one line-follow decision and loss owner; recovery already lives in separate "
        "stuck/body mixins. The added low-light guards invalidate decisions and bypass autonomous "
        "recovery without introducing another writer. Configured back-off, active recovery and "
        "stale-decision tests plus independent reproduction cover this safety boundary.",
    ),
    "core/services/core_features/docking/manager.py": (
        663,
        "accept: 930 -> 663 after the parking-only phases moved to docking/parking_phases.py and the phase/"
        "executor/config definitions to docking/model.py (user decision 2026-09-24: split, not a size exception); "
        "what remains is the one lock owner (state, RLock, take/release_mode seams, fail/retry/release, the "
        "default-dock phases, battery return, public API), ROS-free, covered by core_features/test/test_docking*.py "
        "and core/test/test_docking_*.py (X5)",
    ),
    "core/services/core_features/traffic_policy/manager.py": (
        609,
        "accept: one owner (the TrafficPolicyManager verdict state machine with its evidence contracts "
        "RoadEvidence/SignalHeadEvidence/config/decision), ROS-free, host-testable via core/test/test_traffic_policy.py; "
        "the D-337 measured-light fusion grew the dwell-complete branch (2026-09-29) and the observer transport "
        "already lives in traffic_policy/observer_source.py (X5)",
    ),
    "simulation/gazebo/scripts/lane_live_view.py": (
        709,
        "accept: sim-only read-only viewer server (HTTP handler + ROS subscriptions); the pure logic already lives in live_view_model.py and the page in lane_live_view.html, covered by test_lane_live_view*.py and test_live_view_model.py (X5)",
    ),
    "core/services/core_features/line_follow/recovery": (
        2_098,
        "split: re-judged at 2093, 2098 after merging main (D-520 motion_admit.py +5), on 2026-10-08 (critic agent, read-only) in refactor/junction-subpackage, "
        "the binding follow-up of the 2987 verdict (docs/plans/2026-10-07-line-follow-recovery-subpackage.md, "
        "2026-10-08 section): junction.py, junction_approach.py and junction_bend.py moved with git mv into "
        "recovery/junction/ (gate.py, approach.py, bend.py), its own SIZE_UNITS entry; 3040 before the move = "
        "2093 + 947; merging main brought D-520's motion_admit.py +5 (2098) and junction.py +12. Pure move, no shim, no behaviour change. What stays is D-407 stuck, D-468 lane return, "
        "D-476 bridge and the shared D-507 6 motion_admit.py (lane_bridge and lane_return_decision use it); "
        "every file below 600 (largest stuck_recovery.py 573); all LineFollowManager mixins under the single "
        "manager lock and generation, no own lock, thread, store or publisher; CORE CommandManager stays the "
        "final cmd_vel publisher. The +150 allowance is measured from 2098.",
    ),
    "core/services/core_features/line_follow/recovery/junction": (
        959,
        "split: judged at 947 on 2026-10-08 (critic agent, read-only, APPROVE WITH CHANGES applied) when it left recovery "
        "(docs/plans/2026-10-07-line-follow-recovery-subpackage.md, 2026-10-08 section): gate.py 530 "
        "(D-494 4 / D-495 instruction gate and bounded turn), approach.py 207 (D-507 2-4 window and pivot "
        "approach), bend.py 208 (D-507 addendum map bend pass), __init__.py 2; merging main brought D-520's "
        "gate.py +12 (542, arc refusals), so 959. Mixins of LineFollowManager "
        "under its one lock and generation; motion admission stays recovery/motion_admit.py. Growth inside "
        "+150 is open again (the 2987 verdict's block ends with this move); past 1109 re-judge, and no file "
        "may pass 600 (gate.py is 542): split gate.py by state (e.g. the turn/approach maneuver out of the "
        "gate) before that.",
    ),
    "core/services/core_features/line_follow/arc": (
        310,
        "accept: independently re-judged 2026-10-08 at 299 (lane_arc.py 298, read-only critic agent). "
        "D-520 2 puts map-guided arc following in its own size unit because line_follow/recovery "
        "(2713 +150) and core_features (12772 +150) have no room for it. One cohesive LineFollowManager "
        "mixin under the single manager lock and generation, with no own lock, thread, store or publisher. "
        "CORE CommandManager stays the final cmd_vel publisher, and the D-422 sweep is called, never "
        "changed. Dependency runs arc to recovery only. Split plan of record: "
        "docs/plans/2026-10-08-line-follow-arc-subpackage.md; re-judge on the next +150. Measured 310 "
        "(lane_arc.py 309) after the same review's four safety fixes, inside 299 +150.",
    ),
    "core/services/core_features/localization": (
        922,
        "accept: independently re-judged at 922 on 2026-10-09 (read-only safety reviewer); "
        "docs/plans/2026-10-09-core-localization-size-unit.md registers assist, halt, mission, "
        "D-546 pose_request and package init as one localization domain. No runtime move, new owner, store, "
        "publisher or command path. Re-judge after +150.",
    ),
    "core_features": (
        12_270,
        "accept: independently re-judged at 12270 on 2026-10-09 (read-only safety reviewer): "
        "the cohesive 922-line localization package is now its own size unit under "
        "docs/plans/2026-10-09-core-localization-size-unit.md. The combined pre-split measure was "
        "13192; moving this domain out fulfills the previous split condition without moving runtime code. "
        "Keep the +150 parent allowance and re-judge at the next growth. "
        "Previously re-judged at 13105 on 2026-10-09 for D-546 5: CORE raises and clears the pose request "
        "(localization/pose_request.py, lane_return_pose_request.py); no motion path, D-468 gates unchanged. "
        "Previously independently re-judged 2026-10-08 at 12947 (D-520 step 1 merged with main c06ddcad5; "
        "read-only critic agent). Main alone is 12922 (12772 +150, after D-517 M2 authority.py and D-507 "
        "bend). This branch adds 25 lines outside its arc unit. manager.py +11 is the thinnest possible "
        "hook: ArcMixin base, init and reset calls, the status arc field, and two early returns for the arc "
        "tick and authority gate. model.py +14 is three arc_* config fields with a comment, plus their "
        "validation. The arc logic is in the line_follow/arc size unit. Moving the validation to the arc "
        "unit would create a model/lane_arc import cycle for about 5 lines, so it stays. Condition: the next "
        "core_features growth must move code out (candidate: junction code to recovery, per the recovery "
        "verdict), not raise this number again. Re-judge on the next +150. "
        "Previously: accept: Independently re-judged 2026-10-07 at 12772 after the condition of the 14934 verdict was met: "
        "docs/plans/2026-10-07-line-follow-recovery-subpackage.md moved line_follow lane recovery "
        "(2320 lines) into its own size unit core/services/core_features/line_follow/recovery with its own "
        "verdict. The move, not new code, brings core_features back under its allowance (main had reached "
        "15091 > 14934+150). Remaining line_follow (manager, model, body_stop, clearance, crosswalk_zone) "
        "keeps the policy, the D-422 safety path and the manager that binds the mixins. "
        "Previously independently re-judged 2026-10-07 (code-reviewer agent, read-only): ACCEPT with condition at 14934. "
        "The growth is one line_follow junction mixin (junction.py 443, under the 600 file limit) plus "
        "manager/model/wiring hooks under the same manager lock, generation and CORE final publisher; "
        "no new owner, store, publisher or deploy unit. Condition: "
        "docs/plans/2026-10-07-line-follow-recovery-subpackage.md lands as its own branch; the next "
        "core_features re-judge before that move is on main is REJECT. "
        "accept: with condition: re-judged 2026-10-07 at 14449 for D-476 rev 1 (main 14328 + "
        "branch 121). Condition: before the next core_features re-judge, a dated plan in "
        "docs/plans/ splits line_follow lane recovery (lane_return*, lane_bridge, stuck_*) into "
        "its own core_features subpackage with its own size verdict, keeping the single manager "
        "lock/generation; a re-judge without that plan is REJECT. "
        "Previously independently re-judged 2026-10-06 at 14258 for D-476 lane bridge "
        "(feat/d476-lane-bridge, review ACCEPT: one cohesive line_follow feature under the D-468 "
        "lock/generation; no file over threshold; X1): main already sat at 14083 = 13933+150; "
        "175 above it are lane_bridge114, model+33 (bridge_* config), lane_return+4 "
        "(rebase_retrace extracted), arbitration+19, wiring+3, manager+2. The bridge reuses the "
        "D-468 checkpoint/trail and D-422 sweep under the same manager lock/generation and CORE "
        "final publisher; no new package, store, publisher or deploy unit. Every file threshold "
        "and package+150 remain. "
        "Previously independently re-judged 2026-10-05 at 13933 for D-468 manager arbitration: "
        "216 above13717 are policy+37, approach51, arbitration112, wiring+9, manager+5 and stuck+2. "
        "Existing line_follow leaves separate pure policy, measured approach, evidence and "
        "arbitration under one manager lock/generation and CORE final publisher. No extra "
        "package or deploy unit is justified; all file thresholds and package+150 remain. "
        "See docs/validation/lane-return-2026-10-05/README.md. "
        "Previously independently re-judged 2026-10-05 at 13717 for D-468 source-time lane return: "
        "515 lines above13202 are peer bounded_trial+22 and line_follow policy/admission/mixin+493. "
        "Each new source is below600, owns no publisher or deploy unit and depends only on "
        "its own feature and core_common. Existing feature subpackages preserve the split; "
        "every file threshold and package+150 growth allowance remain unchanged. "
        "See docs/validation/lane-return-2026-10-05/README.md. "
        "Re-judged 2026-10-05 at 13202 for the private cumulative trial "
        "restriction in docs/plans/2026-10-05-core-bounded-camera-trial.md. "
        "The new ROS-free command/bounded_trial.py owns one durable trial ledger "
        "and has no publisher, API, deployment unit or feature-cross imports; "
        "CORE bridge adapts original pose clocks and restricts its existing final "
        "output. Each file remains below600; all existing file limits and the "
        "+150 package re-review allowance remain unchanged. No new package is "
        "justified for this command-owner policy. Previously re-judged "
        "2026-10-04 at 12926 after D-452/D-453 integration: "
        "D-452 adds 93 discovery owner/helper lines (agent 16, helper 77); D-453 adds "
        "110 to the existing stuck recovery/wiring seam (103 and 7). These remain "
        "independent feature subpackages below file budgets, with CORE's existing "
        "command publisher and lease/E-Stop authority preserved. Independent source "
        "count/owner review retains all file limits, 1000 zero-growth tier and +150 "
        "package allowance. The ROS-free CORE feature managers (command, safety, docking, line_follow, "
        "traffic_policy, navigation, swarm, ...) are already one subpackage per feature, each "
        "under the file budget; the package total is a sum of independent owners, not one "
        "tangled module. First judged 2026-10-02 at 10104 when D-407 lane stuck recovery joined "
        "as its own modules (line_follow/stuck_recovery.py, stuck_wiring.py). Re-judge on the "
        "next +150; split by feature into separate packages only if a feature gains its own "
        "deploy unit. Re-judged 2026-10-02 at 10849 when main's D-395 P2-7 localization mission "
        "(core_features/localization) merged in beside D-407; same verdict, each feature still its "
        "own subpackage under the file budget. Re-judged 2026-10-02 at 11061 when the D-407 console "
        "re-run fixes landed (FleetAgent single receive loop, stuck event fields; main had reached "
        "10977); same verdict. Re-judged 2026-10-02 at 11430 when D-422 body-referenced "
        "obstacle stop joined as line_follow/body_stop.py (mixin) and clearance.py geometry; "
        "same verdict. Re-judged 2026-10-02 at 11596 for the D-422 review fixes (near-point "
        "memory, motion envelope, exact straight sweep) inside body_stop.py/clearance.py; same verdict. Re-judged 2026-10-03 at 12140 when D-419 "
        "SAF-003 landed beside D-422 as its own module (safety/fleet_loss.py, the FleetLossMonitor), "
        "the Fleet-goal hooks in navigation/manager.py, and FleetAgent's reply deadline, link "
        "freshness and backoff merged into the D-407 single receive loop in "
        "fleet_agent/agent.py; same verdict. D-424 merged on top (within the allowance) "
        "(localization/mission.py body-referenced rotate and nudge checks, watched turn, "
        "mission_config); same verdict. Re-judged 2026-10-03 at 12297 for the D-424 follow-up (debounced turn evidence gaps in "
        "localization/mission.py); same verdict. Re-judged 2026-10-04 at 12479: bounded "
        "read-only keeper evidence lives separately in vision/lane_perception.py; motion admission "
        "uses the existing ModeMachine and its separate lock. No new deploy unit or file-budget "
        "exception; independent safety review recorded in docs/validation/learned-lane-modes-2026-10-04/README.md. "
        "Concurrent merge adds the main branch's 57 reviewed FleetAgent/discovery lines to this "
        "12479 baseline, yielding 12536; the existing 150 allowance is unchanged. "
        "Re-judged 2026-10-04 at 12551: the user-requested long testing dwell and bounded "
        "low-battery limits add 15 production lines within the existing power owner; "
        "docs/plans/2026-10-04-power-health-and-wake.md records the policy and safety review. "
        "Re-judged 2026-10-04 at 12723 after the concurrent power-health merge: "
        "independent production-line counts are 12662 for integration parent 8dfa7fe (73 files), "
        "12701 for main parent 030323440 (73 files), and 12723 for the union (73 files). "
        "The integration-parent delta is battery.py +22 and power/manager.py +39; "
        "the main-parent delta retains 22 D-442 manual-owner and mode-locked command/watchdog lines. "
        "Power policy remains in its existing owner and the command admission lock is preserved. "
        "docs/validation/ui-release-integration-2026-10-04/README.md records the independent review. "
        "The feature grouping, file budgets and 150 allowance are unchanged.",
    ),
    "perception/control/sensing/perception": (
        11_035,
        "accept: P1a separates the ROS-free camera and lane evidence subpackage as a size unit "
        "(docs/plans/2026-10-08-control-p1a-sensing-perception-split.md). The Python import path, "
        "colcon package, ROS adapters and CORE command ownership do not change; the later "
        "package move needs its own review and ARM64 image proof. Judged at 11035 on 2026-10-09.",
    ),
    "control": (
        34_446,
        f"split: P1a size unit on 2026-10-09: control 45481 = 34446 remaining + 11035 in the separate perception evidence unit (docs/plans/2026-10-08-control-p1a-sensing-perception-split.md). No import or deploy change. Previously 45394 = main verdict 45258 + 136 for the D-507 B9 bend rule gated on bend_expected (default off; lane_keep_bend.py new 108, lane_keep_junction.py +18, lane_keep_pairs.py +10). Re-judged at 45258 on 2026-10-08: the right-boundary fallback width guard stays in "
        "the existing ROS-free lane_bev owner with one focused regression; the P1a sensing split "
        f"still applies. Deploy closure needs only sensing + safety provider (P1a); {CONTROL_SPLIT} "
        "(re-judged 2026-10-07 at 44926 after lane containment projection uncertainty (lane_containment.py "
        "+133, with reviews), the camera AE/AWB re-lock (camera_controls/camera_visibility/v4l2_controls +77; "
        "lock mixin camera_lock.py split out of camera_detect_node) and the D-468 sim-sensor flag (+15). The "
        "ROS-free pieces sit inside sensing/perception and move with it — verdict unchanged); "
        "(re-judged 2026-09-30 at 33090 after D-356 added the ROS-free learned perception backend "
        "(sensing/perception/learned), the shadow node and the recording CLI; the learned backend sits "
        "inside sensing/perception and moves with it — verdict unchanged; re-judged 2026-09-30 at 35197 "
        "under D-362 — web/diagnostic.html and the sensing web assets now count toward the package total; "
        "re-judged 2026-09-30 at 36091 when the pilot branch merged the ROS-free lane keepers "
        "(lane_keep.py 'keep', lane.py 'between') and the NOMINAL ground inside sensing/perception — verdict unchanged; "
        "re-judged again at 36677 with the ROS-free IR line calibration (perception/ir_calibration.py), its read-only "
        "device CLI and the camera-launch overlay validator (control/ir_overlay.py) — verdict unchanged; "
        "re-judged again at 36861 with keep v2 (boundary tracking, wall-base tape, corner-mode holds) and its "
        "front end split into lane_keep_lines.py — verdict unchanged; re-judged 2026-10-01 at 37732 "
        "when the D-47 addendum added the ROS-free calibration fits (sensing/odometry_fit.py, "
        "sensing/perception/camera_extrinsic.py), the stationary camera step mixin "
        "(calibration_camera.py) and the store reader (calibrated_values.py) — each its own module, "
        "verdict unchanged; "
        "re-judged 2026-09-30 at 36859 on the D-373 branch after it added capture trigger/snapshot recorder/"
        "compressed camera/learned status, and 2026-10-01 at 37725 after its first main merge — verdict "
        "unchanged; re-judged 2026-10-01 at 38673 when main (37732) merged into the D-373 branch again: the "
        "D-373 pieces (control/capture_trigger*, the snapshot half of control/recording.py, the learned "
        "status/rate cap and wall role in sensing/perception/learned) stay in the same package and move "
        "with the P1a split — verdict unchanged; re-judged again at 38903 on main when "
        "feat/d384-road-state-and-behaviour merged the D-384 ROS-free road-state estimator "
        "(perception/road_state.py + road_state_model.py) and its shadow node — it sits inside "
        "sensing/perception and moves with it — verdict unchanged; re-judged 2026-10-01 at 39914 when "
        "main (38903) merged into the D-373 branch: both additions stay inside the control package and "
        "move with the P1a split — verdict unchanged; re-judged 2026-10-01 at 40547 when the "
        "D-395 ROS-free localization candidates, objects, injection check and state machine "
        "(sensing/loc_*.py) and the paint-hypothesis and reference-square cues (sensing/perception) "
        "joined — they move with the P1a split, verdict unchanged; re-judged 2026-10-01 at "
        "40803 for the bounded, observation-only follow_preview module and camera-stamp joins "
        "(docs/plans/2026-10-01-follow-preview-design.md): rendering stays in perception, ROS I/O "
        "stays in observer wrappers, and the P1a sensing/safety split remains required; re-judged 2026-10-01 at 41059 when the "
        "D-395 P2-3 robot node joined: the ROS-free LocAssist core (control/loc_assist.py) and its thin ROS "
        "adapter (control/loc_assist_node.py) stay with the sensing nodes and move with the P1a split, "
        "verdict unchanged; re-judged 2026-10-02 at 41237 after the lane A review fixes and the camera "
        "paint points (control/loc_assist*.py, sensing/perception/paint_hypothesis.py) — same subjects, "
        "verdict unchanged; re-judged 2026-10-02 at 41491 on the D-395 Phase 2 integration branch "
        "when lane A (loc_assist) met main's follow_preview additions — same subjects, "
        "verdict unchanged; "
        "re-judged 2026-10-02 at 40961 for the observation-only lane_topology and visual_tags "
        "modules plus explicit boundary/object annotations "
        "(docs/plans/2026-10-02-lane-object-preview-design.md): no new driving authority, "
        "all move with the existing perception split — verdict unchanged; re-judged 2026-10-02 at 41649 "
        "on the D-395 Phase 2 integration branch when main's lane_topology/visual_tags met lane A's "
        "loc_assist — same subjects, verdict unchanged; re-judged 2026-10-02 at 41145 for the D-408 "
        "paint sources (denoise_white_mask in lane_keep_lines.py, learned/paint_worker.py, the lane-mask "
        "helper) — ROS-free inside sensing/perception, they move with the P1a split, verdict unchanged; "
        "re-judged 2026-10-02 at 41833 on the D-395 Phase 2 integration branch with D-408 and loc_assist "
        "together — same subjects, verdict unchanged; re-judged 2026-10-02 at 42013 when D-395 S1 R1 "
        "made LOCALIZED robots report unmapped objects (control/loc_assist*.py) — same subjects, "
        "verdict unchanged; re-judged 2026-10-02 at 42225 when D-411 A added the ROS-free Pilot "
        "recording session (control/pilot_recording.py) beside control/recording.py — evidence only, "
        "it moves with the P1a sensing split, verdict unchanged; re-judged 2026-10-02 at 42346 with its "
        "thin node (control/pilot_recorder_node.py) and the camera's on-demand JPEG switch — same "
        "subjects, verdict unchanged; re-judged 2026-10-02 at 42540 after the D-411 A review hardening "
        "(orphan-writer recovery, off-timer hashing, reserve and disk floor in control/pilot_recording.py, "
        "the camera's dead-recorder check) — same subjects, verdict unchanged; re-judged 2026-10-03 at "
        "42784 when D-411 A landed on main beside D-395 rev. 11 (reference-square NMS, lidar self-beam "
        "drop, learned lane component filter) — same subjects, verdict unchanged;"
        "re-judged 2026-10-03 at 42888 for the D-408 paint CPU follow-up (learned mask area filter, mask-only inference, paint cadence in learned/paint_worker.py) — same subjects inside sensing/perception, verdict unchanged; "
        "re-judged 2026-10-03 at 43055 with D-424 (the bumper's pure scan_geometry "
        "and strip_ranges in control/lidar_guard.py, the shared-body delegation in sensing/body.py, "
        "legacy-envelope lifting in calibration_profile.py) — same subjects, verdict unchanged; "
        "re-judged 2026-10-03 at 43998 when D-423 merged onto main: the ROS-free region range "
        "(sensing/perception/region_range.py: LiDAR bearing-span association with ground-plane fallback), "
        "the NOMINAL-profile and lidar-mount store readers (calibrated_values.py), the opt-in wiring in "
        "camera_detect_node, the ROS-free object_det backend, signature check and slot layout "
        "(sensing/perception/learned/detector.py, signature.py, slots.py), the detector core and its thin "
        "node (control/object_detector*.py) and the overlay pairing in follow_preview -- advisory evidence "
        "beside the learned lane shadow, each its own module, moves with the P1a split, verdict unchanged; "
        "re-judged 2026-10-03 at 44301 for the D-344 §12 addendum: the operator override overlay validator "
        "beside the IR one (control/ir_overlay.py) and its root-run bench CLI (control/line_observer_overrides.py) "
        "-- launch-side config, no node logic, moves with the P1a split, verdict unchanged). "
        "Re-judged 2026-10-04 at 44469 for shared raw road-ROI visibility, invalid camera "
        "evidence/reset and optional raw/annotated recording: observation-only subjects stay "
        "separate and move with the existing P1a split; no new command writer. "
        "Re-judged 2026-10-06 at 44646 for the keep side-flip fix (SIDE_FLIP_FRAMES bounded "
        "side tracking in lane_keep.py) with the junction HOLD policy split out to "
        "lane_keep_junction.py to stay under the file budget — same subjects inside "
        "sensing/perception, they move with the P1a split; verdict unchanged. "
        "re-judged 2026-10-07 at 45104: main's D-491 crosswalk extent +148 (unrecorded) and D-468 paint "
        "inner edge (lane_containment.py, line_observer_node.py); tests excluded from the count. Condition: "
        "the next control re-judge needs a dated P1a step in docs/plans/ (sensing/perception move); "
        "without it, REJECT.",
    ),
    "perception/control/line_observer_node.py": (
        608,
        "accept: with condition: one ROS adapter for the line observer; detection/keep/containment/paint "
        "logic is ROS-free in sensing/perception. Judged 2026-10-07 at 604 (D-468 paint inner edge). "
        "Re-judged 2026-10-08 at 608 for the D-507 keep spin-in-place reset (odom twist joins the "
        "camera-gap reset; paint freshness deduplicated onto pose_if_fresh): no extraction target had "
        "room (lane_keep.py 600, lane_bev.py over, control at its 45254 limit), so the debt moves to the "
        "dated P1a step in docs/plans/2026-10-08-control-p1a-sensing-perception-split.md. Condition: no "
        "further node growth before that step lands; a re-judge above 608 is REJECT.",
    ),
    # --- D-362 newly-covered files (web assets in src/ packages, ops roots). ---
    "perception/web/diagnostic.html": (
        1857,
        "accept: re-judged 2026-09-30 (D-362 P1) — the single HTML file with one IIFE is the "
        "recorded design, not an accident (web/AGENTS.md: dependency-free on purpose, no build "
        "step, served straight from the share dir); it is a debug-only surface excluded from "
        "operational launch and deploy (D-150, ports pinned out by test_control_launch_boundary), "
        "with one owner (web_node). Splitting it into css/js partials would break that contract "
        "to shorten a dev-only file. Zero growth allowance applies (>1000)",
    ),
    # hmi/dashboard/app.js (1338 -> 745) and styles.css (1119 -> 492): the P1
    # extraction landed — telemetry/teleop/state-socket modules and the
    # console-detail.css tail split — so these entries left with it.
    "simulation/gazebo/scripts/lane_live_view.html": (
        856,
        "accept: same owner as the accepted lane_live_view.py — the pure logic already lives in "
        "live_view_model.py and this is the read-only page it renders, covered by test_lane_live_view*.py "
        "and test_live_view_model.py (X5)",
    ),
    "deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py": (
        799,
        "accept: single-entry first-boot provisioning that runs once on the card — one state machine, "
        "covered by test/test_first_boot_provisioning.py (X5)",
    ),
    "deploy/robot/pinky_pro/sd/verify-media-readback.py": (
        788,
        "accept: standalone Windows readback script the operator runs from one file; covered by "
        "test/test_media_readback.py (X5)",
    ),
    "tools/harness/rosy_harness.py": (
        897,
        "accept: the harness gate itself (lint/generate) — one CLI owner pinned by "
        "test/test_harness_contracts.py (X5)",
    ),
    "learning/training/perception/rosy_ml.py": (
        615,
        "accept: the operator CLI is one argparse dispatcher over the wrapped tools (deliver, "
        "harvest, fetch_http, intake), which own the behaviour; covered by "
        "learning/training/perception/test/test_rosy_ml.py (X5, D-411 fetch --http)",
    ),
    "deploy/robot/pinky_pro/native/rosy-face.py": (
        1265,
        "accept: re-judged at 1265 on 2026-10-09 after merging D-552 with D-548 (the DEV prefix now rides the status bar on faces and card bars). Previously 1256 (+26) on 2026-10-09 for D-552 and its review (sound and reversing read from the record, the caution hold, the mixed-install fallback): the lamp, the status bar, the expression and the sound "
        "now come from one core_common.presentation record, so the stage-only lamp fallback, the bar painter and one "
        "record call replace the old lamp/strip calls here and every rule lives in core_common; zero growth allowance "
        "remains. Previously re-judged at 1230 on 2026-10-09 after merging D-546 with D-472/D-537: the 1.5 s recovery hold, "
        "the e-stop clear and the reversing beep (D-546) and the bounded identity pulse with the normal lamp off "
        "(D-537) all stay with the one process that owns the buzzer and the lamp; zero growth allowance remains. "
        "Previously 1229 for D-546 and 1183 for D-472/D-537. Previously re-judged at 1182 on 2026-10-09 for D-483: the same LCD card now shows "
        "the first 16 digits of the validated TLS CA fingerprint for tablet comparison; "
        "zero growth allowance remains. Previously re-judged at 1177 on 2026-10-08 for D-472 4/5: the identity blink's SIGKILL reap, "
        "hard 3.5 s cut and immediate refusal answer stay with the one process that spawns "
        "lamp_pattern; IDENTIFY_OVER and the identify age constants may later move to "
        "core_common.face_screen; zero growth allowance remains. "
        "Previously re-judged at 1148 on 2026-10-07: the existing display owner draws safety cues "
        "before the blocking buzzer and still announces when LCD rendering fails; zero growth allowance. "
        "Previously re-judged at 1140 on 2026-10-07. An accepted fleet identify plays two "
        "1400 Hz beeps from this same buzzer owner and leaves the health sound in place. "
        "Re-judged at 1133 on 2026-10-06 for D-483: the pair-request approval-code card "
        "is one more status row of the same LCD owner; its strict reader and priority live in "
        "core_common.face_screen, rosy-face only passes the file and draws the notice. "
        "Re-judged at 1119 on 2026-10-06: bounded LED identity pulse joins the "
        "existing face lamp owner, gated by live IDLE and alarm state; the zero-growth "
        "allowance remains. The one owner of LCD, buzzer and lamp (D-433, was rosy-boot-display.py) — one poll "
        "and one frame tick; the situation table lives in core_common.face_screen; covered by "
        "test/test_rosy_face.py (X5). 1048 after the review fixes (last good hand-over, "
        "shutdown-only poll). Re-judged 2026-10-04 at 1074: opt-in light session uses the "
        "same device owner and priority loop; eligibility/freshness stays in face_screen "
        "and light rendering is separate. Independent review and queued-test regressions "
        "preserve alarm-first order, emergency lamp and stale-evidence expiry.",
    ),
    "deploy/robot/pinky_pro/release/updater.py": (
        686,
        "accept: activate/rollback atomicity is one transactional script; covered by "
        "test/test_release_updater.py (X5)",
    ),
    "deploy/robot/pinky_pro/release/secret_scan.py": (
        670,
        "accept: one scan entry over the release tree — the rules and the walker are the same concern (X5)",
    ),
    "deploy/robot/pinky_pro/native/rosy_auto_update.py": (
        1591,
        "split: D-412 robot-side updater — the GitHub/rollout fetch and staging, the eligibility "
        "reader (status-inputs, hold, seals, claim), and the apply/resume/rollback transaction with "
        "its journal are separate seams; move fetch+staging and eligibility into sibling modules in "
        "deploy/robot/pinky_pro/native after the first two-robot device validation (D-412 Validation). "
        "Re-judged at 1505 (+33): second verification review (self-rollback vs operator rollback, "
        "bounded tail loop, rollback_failed acknowledgement); 1515 (+10) after the final batch "
        "(release-hold under the run lock, refused rollback is sticky); verdict unchanged. "
        "1559 (+42) for D-433: the Updating marker for rosy-face and the one-time start of the "
        "retired display unit after a rollback (Q5); 1591 (+32) for the D-433 review "
        "(live display swap moved here from the sync, marker only during this run's steps); verdict unchanged",
    ),
    "deploy/robot/pinky_pro/native/rosy-ssh-access.py": (
        862,
        "accept: D-418 root SSH helper — one stdlib-only privileged entry point whose request parsing, "
        "managed authorized_keys, temporary password (wall + boot clock, boot id) and boot cleanup share "
        "one lock and one audit trail; splitting would spread the root trust boundary over several files "
        "the image layer must install and the twin must cover. Split the password half out if it grows further",
    ),
    "tools/device_twin/scenarios.py": (
        703,
        "split: device twin scenarios — the D-412 update scenarios and the D-418 ssh/ssh_socket scenarios "
        "are independent tables; move the ssh scenarios into their own module when the next scenario lands",
    ),
    "tools/release/publish_payload_release.py": (
        655,
        "accept: D-412 operator publish tool; rollout signing, the GitHub release I/O and the "
        "canary watch are one short sequential flow; split the canary watch out if it grows further",
    ),
    "deploy/robot/pinky_pro/native/sync-image-layer.py": (
        1023,
        "split: D-388 image-layer sync — the allowlist/plan, the backup-record history (records, "
        "cleanup, crash reconcile) and the apply/pending transaction are separate seams; move the "
        "record history into a sibling module in deploy/robot/pinky_pro/native once the 2026-10-02 bench "
        "run has exercised it on a robot, so the split does not land untested on device; owner deploy, "
        "covered by test/test_image_layer_sync.py. Re-judged 2026-10-03 at 1018: main reached 1000 "
        "(state-directory bootstrap) without a re-judgement, D-433 adds 18 (retired units); verdict unchanged. "
        "Re-judged 2026-10-04 at 1020: two lane-only Host unit allowlist entries, no new sync logic; "
        "record-history split remains required after device exercise. "
        "Re-judged 2026-10-06 at 1023: D-477 adds one condition-gated join unit to UNITS and "
        "ENABLED_UNITS, no new sync logic; verdict unchanged.",
    ),
    "deploy/robot/pinky_pro/native/rosy-hw-probe.py": (
        641,
        "accept: single-entry hardware probe CLI the commissioning runbook drives top-to-bottom — "
        "splitting probe sequence from reporting would sever one diagnostic narrative (X5)",
    ),
    "apps/device/omx/adapter/omx_adapter/action_store.py": (
        1_191,
        "accept: one owner for the durable local Action, per-attempt ROS phase journal, and semantic "
        "workflow terminal gate; they share SQLite transactions, identity fences, and restart-to-UNKNOWN "
        "recovery. ROS-free and host-testable. Re-judged 2026-10-01 at 1109 after the durable gripper "
        "evidence gate and restart-to-HOLD journal recovery; recovery updates share the same SQLite "
        "transaction so the Action, phase, and possible-held-object state cannot split. Re-judged "
        "2026-10-01 at 1176 for late ROS UUID and exact-cancel intent journaling after UNKNOWN/HOLD "
        "without reopening phase state (D-386). Re-judged 2026-10-01 at 1187 after the "
        "canceled-action hold joined (peer's change). Re-judged 2026-10-02 at 1191 (C4b G8): "
        "completion is journaled per kind (PICK_PLACE names kept, CELL_TRANSFER its own) with "
        "net -3 lines. The hard-tier zero-growth rule prevents silent expansion",
    ),
    "apps/device/omx/adapter/omx_adapter/command_owner.py": (
        621,
        "accept: one owner (2026-10-02, C3b review) for the single-writer arm command policy: "
        "config, joint-state intake, submit admission (limits, start window), poll timeouts on "
        "the owner and wall clocks, cancel and recovery share one lock and one HOLD latch; "
        "splitting admission from the watchdog would split that lock. ROS-free and host-testable",
    ),
    "apps/device/omx/adapter/omx_adapter/pose_plan.py": (
        714,
        "accept: one owner (2026-10-02, C3b) for the simulation cell profile and the analytic "
        "CELL_TRANSFER planner that reads it. C3b added the profile's width-matched jaw mapping, "
        "after-grasp per-phase tolerances and wall-clock bound, and the request's grasp depth/width; "
        "the planner and validate_cell_transfer_plan consume exactly these fields, so a profile/"
        "planner split would only move the shared validation. ROS-free and host-testable. Split "
        "the profile loader out if MoveIt (D-402 follow-up) adds a second planner. Re-judged at 714 "
        "after the review's accepted-recipe item check, release rejection and fingertip overhang",
    ),
    "ui/robot/app.js": (
        803,
        "split: the shell's session/auth/refresh cycle, the Escape e-stop handler, the goal "
        "tracking, the mode bindings and the formation cell wiring grew with D-383/D-385/D-396 "
        "— the natural seam is the D-362 P1 module split that already moved telemetry, teleop "
        "and the state socket out; the remaining event bindings and the rosy:goal listener "
        "belong in a sibling module (D-338 pattern). Owner dashboard, scheduled for the "
        "D-362 P2 round.",
    ),
}

WORKSPACE_REF_PATTERNS = (
    re.compile(r"get_package_share_directory\(\s*['\"](\w+)['\"]"),
    re.compile(r"FindPackageShare\(\s*['\"](\w+)['\"]"),
    re.compile(r"\$\(find-pkg-share\s+(\w+)\)"),
    #: ``package://x/…`` URIs — mesh/world/map refs in urdf/xacro/sdf/world/rviz/yaml.
    re.compile(r"package://(\w+)/"),
)
#: Executable references, scanned in launch files only (``setup.py`` also says ``package``).
LAUNCH_EXEC_PATTERNS = (
    re.compile(r"\bpackage\s*=\s*['\"](\w+)['\"]"),
    re.compile(r"<node\b[^>]*\bpkg\s*=\s*['\"](\w+)['\"]"),
)
CODE_SUFFIXES = {".py", ".cpp", ".hpp"}
DECLARING_TAGS = {"depend", "exec_depend", "build_depend", "build_export_depend"}


#: D-427 wave 0 item 5: every colcon root in the platform manifest.
COLCON_ROOTS = tuple(ROOT / root for root in yaml.safe_load(
    (ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))["colcon_roots"])
#: An empty walk passes every per-package rule; today the roots hold 27 packages.
MIN_PACKAGES = 27


def _rel(path: Path) -> Path:
    """``path`` relative to the colcon root that holds it (``src``, ``learning`` or ``operations``)."""
    return path.relative_to(next(root for root in COLCON_ROOTS if path.is_relative_to(root)))


def _is_prod(path: Path) -> bool:
    parts = _rel(path).parts
    return not any(p in ("test", "tests", "build", "install", "log") or p.startswith(".") for p in parts)


def _packages():
    found = {}
    for package_xml in sorted(xml for base in COLCON_ROOTS for xml in base.rglob("package.xml")):
        if not _is_prod(package_xml):
            continue
        root = ET.parse(package_xml).getroot()
        found[root.findtext("name")] = {"dir": package_xml.parent, "xml": root}
    assert len(found) >= MIN_PACKAGES, sorted(found)
    return found


PACKAGES = _packages()


#: D-427: packages leave the D-310 src/ domains for the D-427 parts, but the P4 direction
#: table still judges each package by the D-310 role it had there (name -> (domain, family)).
#: Package names are frozen (D-231), so this table does not move with the folders.
D310_ROLE = {
    "core": ("runtime", None), "core_events": ("runtime", None), "core_features": ("runtime", None),
    "core_api_web": ("runtime", None), "control": ("runtime", None), "navigation": ("runtime", None),
    "core_common": ("contracts", None), "interfaces": ("contracts", None),
    "web_common": ("hmi", None), "emotion": ("hmi", None), "dashboard": ("hmi", None), "pilot": ("hmi", None),
    "pinky_pro": ("products", "pinky_pro"), "bringup": ("products", "pinky_pro"),
    "sensor_adc": ("products", "pinky_pro"), "lamp_control": ("products", "pinky_pro"),
    "led": ("products", "pinky_pro"), "omx": ("products", "omx"), "omx_adapter": ("products", "omx"),
    "imu_bno055": ("drivers", None), "description": ("sim", None), "gz_sim": ("sim", None),
}


def _domain(name: str) -> str:
    if name in D310_ROLE:
        return D310_ROLE[name][0]
    return _rel(PACKAGES[name]["dir"]).parts[0]


def _family(name: str):
    if name in D310_ROLE:
        return D310_ROLE[name][1]
    parts = _rel(PACKAGES[name]["dir"]).parts
    return parts[1] if len(parts) == 3 and parts[0] == "products" else None


# D-241 and D-242: the ROS package name stays. These directories use the role name.
ROLE_DIR = {
    # D-427 wave 4d: middleware/core/<role>, contracts/foundation, contracts/ros_idl.
    "core": ("core", "gateway"),
    "core_events": ("core", "events"),
    "core_features": ("core", "services"),
    "core_api_web": ("core", "api_web"),
    "core_common": ("foundation",),
    "interfaces": ("ros_idl",),
    "control": ("perception",),  # middleware/perception (D-427 wave 4e)
    "web_common": ("web",),  # shared/web (D-427 wave 4b)
    "emotion": ("ui", "face"),  # middleware/ui/face (D-427 wave 4b)
    "dashboard": ("ui", "robot"),  # middleware/ui/robot (D-427 wave 4b)
    # D-427 wave 4c: middleware/apps/device/<robot>/<role>, middleware/drivers/<robot>_<role>.
    "pinky_pro": ("apps", "device", "pinky", "profile"),
    "bringup": ("apps", "device", "pinky", "bringup"),
    "description": ("apps", "device", "pinky", "description"),
    "sensor_adc": ("drivers", "pinky_adc"),
    "lamp_control": ("drivers", "pinky_lamp"),
    "led": ("drivers", "pinky_led"),
    "omx": ("apps", "device", "omx", "profile"),
    "omx_adapter": ("apps", "device", "omx", "adapter"),
    "imu_bno055": ("drivers", "imu_bno055"),
    "navigation": ("core", "navigation"),
    "gz_sim": ("simulation", "gazebo"),
    "isaac_sim": ("envs", "isaac"),  # learning/envs/isaac (D-427 wave 1)
    "rosy_vision": ("vision",),  # operations/vision (D-427 wave 3b)
    "fleet": ("fleet",),  # operations/fleet (D-427 wave 3c)
}


def layout_ok(rel: tuple, name: str) -> bool:
    """P2(a) + D-310: declared product packages and independent drivers."""
    if not rel or rel[0] not in DOMAINS:
        return False
    if name in ROLE_DIR:
        return rel == ROLE_DIR[name]
    if rel[0] == "products":
        return False  # Product packages require an explicit family/role declaration.
    # D-377: an app package is `rosy_<word>` in folder `<domain>/<word>`.
    return len(rel) == 2 and name in (rel[1], f"rosy_{rel[1]}")


def _declared(name: str) -> set:
    return {
        (e.text or "").strip()
        for e in PACKAGES[name]["xml"]
        if e.tag in DECLARING_TAGS and (e.text or "").strip() in PACKAGES
    }


def _files(name: str, suffixes):
    for path in PACKAGES[name]["dir"].rglob("*"):
        if path.is_file() and path.suffix in suffixes and _is_prod(path):
            yield path


def _used(name: str) -> dict:
    """Workspace packages this package reaches, mapped to one example site."""
    used = {}
    for path in _files(name, {".py"}):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                tops = [node.module.split(".")[0]]
            else:
                continue
            for top in tops:
                used.setdefault(top, f"{_rel(path).as_posix()} imports {top}")
    for path in _files(name, {".py", ".xml", ".cpp", ".hpp", ".yaml",
                               ".urdf", ".xacro", ".sdf", ".world", ".rviz"}):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in WORKSPACE_REF_PATTERNS:
            for match in pattern.finditer(text):
                used.setdefault(match.group(1), f"{_rel(path).as_posix()} references {match.group(1)}")
        if "launch" in path.relative_to(PACKAGES[name]["dir"]).parts or ".launch." in path.name:
            for pattern in LAUNCH_EXEC_PATTERNS:
                for match in pattern.finditer(text):
                    used.setdefault(match.group(1), f"{_rel(path).as_posix()} runs {match.group(1)}")
        if path.suffix in {".cpp", ".hpp"}:
            for match in re.finditer(r"#include\s*[<\"](\w+)/", text):
                used.setdefault(match.group(1), f"{_rel(path).as_posix()} includes {match.group(1)}")
    return {top: site for top, site in used.items() if top in PACKAGES and top != name}


def edge_allowed(src_domain, src_family, dst_domain, dst_family, target) -> bool:
    """P4 direction table (D-168, D-310). Pure, so rows are testable."""
    if target in CORE_CONTRACTS:
        return True
    if src_domain == "core":
        return dst_domain == "core"
    if src_domain in ("sim", "envs"):  # envs: Isaac moved out of sim (D-427 wave 1)
        return True
    if src_domain == "products":
        if dst_domain == "sim" and target == "description":
            return True
        if dst_domain == "drivers":
            return True
        return bool(src_family) and dst_domain == "products" and dst_family == src_family
    return False


def _allowed(source: str, target: str) -> bool:
    src_domain, dst_domain = _domain(source), _domain(target)
    if source == "navigation" and target == "bringup" and dst_domain == "products":
        return True
    if src_domain == "runtime" and dst_domain == "runtime":
        return True
    # D-243: the API package serves the operator screens and nothing else in runtime does.
    # D-323: the pilot teleop surface follows the same serving exception.
    if source == "core_api_web" and target in {"dashboard", "pilot"}:
        return True
    return edge_allowed(src_domain, _family(source), dst_domain, _family(target), target)


def _lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def test_the_scan_sees_the_whole_tree():
    assert len(PACKAGES) >= 20, sorted(PACKAGES)


def test_every_package_sits_in_a_domain_group_under_its_own_name():
    """P2(a) + D-147 + D-310: package names persist at declared source roots.

    Products nest under their family; standalone drivers stay under drivers/.
    """
    bad = []
    for name, info in PACKAGES.items():
        rel = _rel(info["dir"]).parts
        if not layout_ok(rel, name):
            bad.append(f"{name}: {'/'.join(rel)}")
    assert bad == [], bad


def test_every_package_has_agents_md():
    """P2(b)."""
    missing = [name for name, info in PACKAGES.items() if not (info["dir"] / "AGENTS.md").is_file()]
    assert missing == [], missing


def test_every_package_is_a_harness_module():
    """P2(c): registered in harness.yaml (the harness tests check the records)."""
    config = yaml.safe_load((ROOT / "tools" / "harness" / "harness.yaml").read_text(encoding="utf-8"))
    registered = {(ROOT / m["path"]).resolve() for m in config["modules"]}
    missing = [name for name, info in PACKAGES.items() if info["dir"].resolve() not in registered]
    assert missing == [], missing


def test_library_packages_leave_runtime_gates_to_their_consumer():
    """P2: library/contract packages write N/A for ROS-SIM..FIELD."""
    bad = []
    for name in sorted(LIBRARY_PACKAGES):
        text = (PACKAGES[name]["dir"] / "progress.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        for gate in ("ROS-SIM", "ARTIFACT", "DEVICE", "FIELD"):
            state = meta["gates"][gate]["state"]
            if state != "N/A":
                bad.append(f"{name} {gate}={state}")
    assert bad == [], bad


def test_every_package_owns_tests():
    """P2(d), with the exception list checked both ways (P5)."""
    without = {
        name
        for name, info in PACKAGES.items()
        if not any((info["dir"] / "test").glob("test_*.py"))
    }
    assert without == set(KNOWN_WITHOUT_OWN_TESTS), (
        f"new: {sorted(without - set(KNOWN_WITHOUT_OWN_TESTS))}, "
        f"stale: {sorted(set(KNOWN_WITHOUT_OWN_TESTS) - without)}"
    )


def test_every_cross_package_use_is_declared():
    """P3: imports, includes and launch references all appear in package.xml."""
    undeclared = {}
    for name in PACKAGES:
        declared = _declared(name)
        for target, site in _used(name).items():
            if target not in declared:
                undeclared[(name, target)] = site
    assert set(undeclared) == set(KNOWN_UNDECLARED), (
        f"new: {[undeclared[k] for k in sorted(set(undeclared) - set(KNOWN_UNDECLARED))]}, "
        f"stale: {sorted(set(KNOWN_UNDECLARED) - set(undeclared))}"
    )


def test_cross_domain_edges_follow_the_direction_table():
    """P4: declared or used edges must be allowed for the source domain."""
    wrong = {}
    for name in PACKAGES:
        for target in _declared(name) | set(_used(name)):
            if target != name and not _allowed(name, target):
                wrong[(name, target)] = f"{_domain(name)}/{name} -> {_domain(target)}/{target}"
    assert set(wrong) == set(KNOWN_DIRECTION), (
        f"new: {[wrong[k] for k in sorted(set(wrong) - set(KNOWN_DIRECTION))]}, "
        f"stale: {sorted(set(KNOWN_DIRECTION) - set(wrong))}"
    )


def test_core_chain_stays_one_way():
    """P4 core row: common <- events <- features <- api_web <- core."""
    order = ["core_common", "core_events", "core_features", "core_api_web", "core"]
    back = [
        f"{order[i]} -> {order[j]}"
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if order[j] in _declared(order[i]) | set(_used(order[i]))
    ]
    assert set(back) == set(KNOWN_CHAIN_BACK_EDGES), (
        f"new: {sorted(set(back) - set(KNOWN_CHAIN_BACK_EDGES))}, "
        f"stale: {sorted(set(KNOWN_CHAIN_BACK_EDGES) - set(back))}"
    )


def _is_prod_outside_src(path: Path) -> bool:
    """Prod filter for the OPS_ROOTS (D-362), same rule as _is_prod."""
    return not any(
        p in ("test", "tests", "build", "install", "log") or p.startswith(".")
        for p in path.relative_to(ROOT).parts
    )


def _over_budget() -> dict:
    over = dict.fromkeys(SIZE_UNITS, 0)
    for name in PACKAGES:
        total = 0
        for path in _files(name, CODE_SUFFIXES | {".sh"} | WEB_SUFFIXES):
            count = _lines(path)
            rel = _rel(path).as_posix()
            unit = max((u for u in SIZE_UNITS if rel.startswith(u + "/")), key=len, default=None)  # innermost
            if unit:
                over[unit] += count
            else:
                total += count
            budget = FILE_BUDGET_WEB if path.suffix in WEB_SUFFIXES else FILE_BUDGET
            if count > budget:
                over[rel] = count
        if total > PACKAGE_BUDGET:
            over[name] = total
    for root_name in OPS_ROOTS:
        for path in (ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix not in OPS_SUFFIXES:
                continue
            if not _is_prod_outside_src(path):
                continue
            count = _lines(path)
            if count > FILE_BUDGET:
                over[path.relative_to(ROOT).as_posix()] = count
    return over


def test_over_budget_code_has_a_recorded_verdict():
    """P6: every file > 600 lines and package > 10k lines has a verdict, and no stale ones."""
    over = _over_budget()
    assert set(over) == set(SIZE_VERDICTS), (
        f"needs a verdict: {sorted((k, over[k]) for k in set(over) - set(SIZE_VERDICTS))}, "
        f"stale: {sorted(set(SIZE_VERDICTS) - set(over))}"
    )


def test_size_units_are_real_subpackages_with_a_split_plan():
    """P6: each SIZE_UNITS entry is a counted Python subpackage whose verdict cites its split plan."""
    over = _over_budget()
    bad = []
    for unit in SIZE_UNITS:
        dirs = [root / unit for root in COLCON_ROOTS if (root / unit / "__init__.py").is_file()]
        if not dirs:
            bad.append(f"{unit}: no Python subpackage (__init__.py) under a colcon root")
        if over[unit] <= 0:
            bad.append(f"{unit}: counts no lines")
        plans = re.findall(r"docs/plans/\S+?\.md", SIZE_VERDICTS.get(unit, (0, ""))[1])
        if not any((ROOT / plan).is_file() for plan in plans):
            bad.append(f"{unit}: verdict cites no existing docs/plans split plan")
    assert bad == [], bad


def _allowance(key: str, at_verdict: int, now: int) -> int:
    """D-362: a file above HARD_TIER gets zero growth allowance (packages keep 150)."""
    if key not in PACKAGES and key not in SIZE_UNITS and max(at_verdict, now) > HARD_TIER:
        return 0
    return REGROWTH_ALLOWANCE


def test_size_verdicts_are_well_formed_and_current():
    """P6: split/accept only, split plans exist, and no silent regrowth."""
    over = _over_budget()
    bad = []
    for key, (at_verdict, verdict) in SIZE_VERDICTS.items():
        kind, _, reason = verdict.partition(": ")
        if kind not in ("split", "accept") or not reason:
            bad.append(f"{key}: verdict must be 'split: ...' or 'accept: ...'")
        for plan in re.findall(r"docs/plans/\S+?\.md", verdict):
            if not (ROOT / plan).is_file():
                bad.append(f"{key}: plan not found {plan}")
        allowance = _allowance(key, at_verdict, over.get(key, 0))
        if key in over and over[key] > at_verdict + allowance:
            bad.append(f"{key}: {over[key]} lines, grew past {at_verdict}+{allowance}; re-judge")
    assert bad == [], bad


@pytest.mark.parametrize(
    "src_domain, src_family, dst_domain, dst_family, target, ok",
    [
        ("products", "pinky_pro", "sim", None, "description", True),
        ("products", "pinky_pro", "drivers", None, "imu_bno055", True),
        ("products", "pinky_pro", "products", "pinky_pro", "bringup", True),
        ("products", "pinky_pro", "products", "omx", "omx_adapter", False),
        ("products", "omx", "products", "pinky_pro", "bringup", False),
        ("products", "omx", "contracts", None, "core_common", True),
        ("products", "omx", "runtime", None, "core", False),
        ("runtime", None, "products", "pinky_pro", "bringup", False),
        ("drivers", None, "products", "pinky_pro", "bringup", False),
        ("site", None, "drivers", None, "imu_bno055", False),
    ],
)
def test_direction_table_rows_for_products_and_drivers(src_domain, src_family, dst_domain, dst_family, target, ok):
    """D-310 P4 rows retain separate product, driver, and runtime ownership."""
    assert edge_allowed(src_domain, src_family, dst_domain, dst_family, target) is ok


@pytest.mark.parametrize(
    "rel, name, ok",
    [
        (("apps", "device", "pinky", "bringup"), "bringup", True),
        (("apps", "device", "pinky", "profile"), "pinky_pro", True),
        (("apps", "device", "omx", "adapter"), "omx_adapter", True),
        (("drivers", "imu_bno055"), "imu_bno055", True),
        (("devices", "pinky_pro", "bringup"), "bringup", False),
        (("devices", "bringup"), "bringup", False),
        (("products", "pinky_pro"), "pinky_pro", False),
        (("products", "omx", "bringup"), "bringup", False),
        (("perception",), "control", True),
        (("runtime", "control"), "control", False),
        (("core", "control"), "control", False),
        (("apps", "x", "control"), "control", False),
    ],
)
def test_layout_rule_allows_declared_product_packages_and_standalone_drivers(rel, name, ok):
    """P2(a) + D-310: product packages require explicit family ownership."""
    assert layout_ok(rel, name) is ok
