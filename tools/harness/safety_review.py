"""D-430 §5: commits that touch safety-tagged paths carry a ``Safety-Review:`` trailer.

Usage: python tools/harness/safety_review.py BASE HEAD [--warn-only]

Checks the commits in BASE..HEAD, minus ancestors of BASELINE (history from
before this check landed) and the reviewed ``EXEMPT`` list. CI passes exactly the
event's range: the PR base for ``pull_request``, ``before`` for ``push``. When
BASE is empty, all zeros (a new branch) or unreachable (a force push), only
HEAD itself is checked (HEAD^..HEAD), never the whole history, so one old
untrailered commit cannot keep CI red. Needs full history (``fetch-depth: 0``).

What is safety-tagged comes from ``tools/harness/platform_parts.yaml``: files under
a ``concern: safety`` root (deepest root wins) and the ``safety_modules`` list. A
path counts when the manifest at HEAD, at BASE, at the commit, or at its parent
tags it, so a branch forked before a path was tagged is still checked. A commit needs the
trailer when it

- changes such a path (a ``git mv`` changes both the old and the new path, so wave
  3/4 moves of safety roots or modules need the trailer), or
- stops tagging a root, module or ``safety_anchors`` entry that its parent tagged.

A non-merge commit is checked on its diff to its parent. A merge is checked only
on the paths it changes against every parent (``diff-tree --cc``: conflict
resolutions and evil-merge edits); what it brings in is checked on the merged
commits themselves.

``--warn-only`` prints the same report and exits 0; ``tools/hooks/pre-push`` uses it
as an opt-in early warning. The CI step is the enforcement.
"""

from __future__ import annotations

import re
import subprocess
import sys

import yaml

#: main when this check landed (D-430 wave 0). Its ancestors are never checked.
BASELINE = "46b8720c297db5729297de4442051a0265f097ea"  # git commit revision
#: Reviewed historical commits after BASELINE that touch safety paths without a
#: trailer, as full SHA -> reason. Add only with an independent review.
EXEMPT: dict[str, str] = {
    "dc4ef1a90f3f8c28db9eccbf7b9288980eb297fe":  # git commit revision
        "Independent lap_review retrospective source review on 2026-10-10: safety.py AST identical "
        "to first parent ff1f70b3c (already carries independent Safety-Review APPROVE WITH NOTES); "
        "merge resolution only updates comment API version v1.195 to v1.196. Admin-only latch "
        "release and docking cancellation unchanged. See docs/validation/one-lap-route-review-"
        "2026-10-10/result.md; no device acceptance.",
    "f14e20e2fc52ff0fb9e8d7267dbeb0f7e6596d70":  # git commit revision
        "Independently reviewed on 2026-10-09: D-526 follow-up moves the TRUSTED map-pose check verbatim "
        "into tether_routes so the safety-tagged tether_watch imports no decision module; still fail-closed "
        "(19 tether tests). Part of the D-526 landing the user approved on 2026-10-09. See docs/validation/"
        "d526-tether-watch-safety-review-2026-10-09/result.md.",
    "66f0e629d4aad3533ad2c8ff07b7f95a9e817a14":  # git commit revision
        "Independently reviewed on 2026-10-09 (three rounds, final APPROVE): D-526 Fleet tether watch "
        "stops a tethered robot through the existing CORE E-Stop client on radius, turn or a stale "
        "trusted map pose (fail-closed). Exempted with user approval 2026-10-09. See docs/validation/"
        "d526-tether-watch-safety-review-2026-10-09/result.md; host tests only, no device acceptance.",
    "2c1c2310e42bcc54092935cb8ca86378422c9ed1":  # git commit revision
        "Independently reviewed on 2026-10-09: D-526 review fixes (trusted map pose only, per-stop "
        "timeout, watch liveness, TETHER_STOP_FAILED alarm via console alarm sources). Exempted with "
        "user approval 2026-10-09. See docs/validation/d526-tether-watch-safety-review-2026-10-09/result.md.",
    "a402c42935e27170be57e5240b807be6f88d38fc":  # git commit revision
        "Independent code-reviewer agent (read-only), 2026-10-09: APPROVE WITH NOTES. console.py adds "
        "LINK_DEGRADED_S (10 s) and a console-clock (time.monotonic) _last_ok; a failed state read within "
        "the grace gets link 'degraded' plus link_degraded_s, display only. The row keeps online=False, so "
        "traffic, dead-leader hand-off, swarm speed, capabilities, tracking and line-stuck readers are "
        "unchanged; only link 'unreachable' is rewritten (moved, tls-refused, protocol are not). A degraded "
        "robot still disarms the selected goal (review MEDIUM applied in the follow-up commit) and the "
        "server goal path is untouched. test_link_on_snapshot.py passes; no device acceptance.",
    "cd7464f3241145b28c1d2fa21aa734e7ccb6940f":  # git commit revision
        "Independent Codex review, 2026-10-09: D-535 adds a read-only link_reason field "
        "to failed Fleet robot rows and renders it in the roster. The field has no "
        "command, stop, admission or authority reader; D-499 link classification remains. "
        "Model-PC link-reason, dispatch-stop-latch and cancel-all tests passed 48/48. "
        "See docs/validation/d535-link-reason-safety-review-2026-10-09/result.md; "
        "a second independent review fixed missing SSL verify_code handling and passed 60 focused tests "
        "(docs/validation/d535-link-reason-review-2026-10-09/result.md); "
        "no device or motion acceptance.",
    "f8165b2a44d01ff628d5bd75ec923953bd09d000":  # git commit revision
        "Independently reviewed by Codex /root on 2026-10-05: D-463 retains existing "
        "operator policy/idempotency and goal authority, including legacy compatibility; fresh LOCALIZED finite map "
        "pose and lane band precede the short next point. Source review and 11 host "
        "route tests; no device acceptance. See docs/validation/"
        "d463-route-independent-review-2026-10-05/README.md. Also independently reviewed "
        "by the OpenCode GLM session on 2026-10-05: route uses the existing goal path; "
        "non-LOCALIZED pose is refused and cancel/stop generation stays untouched.",
    "7e34baacebc02dd6103dbdd17c5e861b92a02945":  # git commit revision
        "Independently reviewed by Codex /root/pilot_review on 2026-10-04: D-432 "
        "device TXT metadata, bounded opt-in admission, verified TLS and key-only SSH; "
        "moved firmware preserves handlers/interlocks. See docs/validation/"
        "ui-release-integration-2026-10-04/README.md.",
    "a4caeed0f5119df17f138203cd6e01eb373da671":  # git commit revision
        "Independently reviewed by Codex /root/pilot_review on 2026-10-04: D-447 "
        "validated fresh bound heartbeat reuse, monotonic age and stale/offline REST fallback; "
        "dispatch/traffic and CORE command ownership unchanged. See docs/validation/"
        "ui-release-integration-2026-10-04/README.md.",
    "a075a0bba2bec616c12dc2c99a6987c3764ae055":  # git commit revision
        "Independent security-reviewer agent, 2026-10-06: only drops memory points within "
        "1e-6 m of range_min (float rounding, below LiDAR resolution); D-422 blind-gap lower "
        "bound still applies, no-echo never clears, memory only shortens gaps; repro test "
        "fails pre-fix, C1/0.12 post latch tests pass (56/56, 463 filtered).",
    "463ae393a27e0ef5c644d851f96de3078a2e939c":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py change only widens "
        "trusted_map_pose to (x, y, yaw-or-None); TRUSTED-verdict, finite x/y and remember-row "
        "gates unchanged, non-finite/missing yaw is None not a pose. Lane-route caller indexes "
        "pose[0:2] only (D-463 gate, idempotency, operator goal path untouched); new D-488/D-490 "
        "/trip caller is plan-only (execute/start 501, named operator) and refuses a None yaw. "
        "No stop, admission, dispatch or auth path touched; 136 host tests pass at the commit "
        "(lane_route, site_map_api, stuck_resolver, server_console, overhead_tracking_service); "
        "no device acceptance.",
    "a86afa7f7714ba583e0da1c0a3245c47e91430b4":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: console.py only adds the D-494 3 '
        'state sink (attribute, set_state_sink, one call in _remember after _seen) feeding '
        'MapPoseService.observe_state, a pure trip-only odom recorder that never mutates the '
        'snapshot and is not an input to trusted_map_pose. The unguarded call never reached '
        'main alone: first main commit 246eac64f also carries the f42bcc865 try/except; no '
        'stop, admission, dispatch, goal, traffic, auth or trust path changed; 60 host tests '
        'pass (map_pose_service incl. raising sink, trip_caps, server_console, site_map_trip); '
        'no device acceptance.',
    "2b08f9629618c8fc34d181ca7a6fc1d8666ae91c":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: console.py adds caps_for, a read of '
        'the existing CapabilityDisplay cache (wait_s=2.0, bounded asyncio.wait on the shared '
        'refresh task) mapped to TripCaps; only caller is the /trip plan route (named operator, '
        'start still not_open), where caps only narrow the plan; no stop, admission, dispatch, '
        'goal, traffic, auth or trust path changed; 60 host tests pass (map_pose_service incl. '
        'raising sink, trip_caps, server_console, site_map_trip); no device acceptance.',
    "f42bcc8651987f89224e611e7ddf6c638398e8f7":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: console.py wraps the D-494 3 state '
        'sink call in try/except with a once-per-robot log, so a bad snapshot can no longer '
        'skip the _loc_null_since/_trusted updates or later rows in _remember; no stop, '
        'admission, dispatch, goal, traffic, auth or trust path changed; 60 host tests pass '
        '(map_pose_service incl. raising sink, trip_caps, server_console, site_map_trip); no '
        'device acceptance.',
    "e3053c5ba6dc69abe85c24fd975ba88536dc06d8":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: console.py change is one docstring '
        'renumber (D-491 1 -> D-494 1) on caps_for; no executable line changed; no stop, '
        'admission, dispatch, goal, traffic, auth or trust path changed; 60 host tests pass '
        '(map_pose_service incl. raising sink, trip_caps, server_console, site_map_trip); no '
        'device acceptance.',
    "bdbbd400128eab3ac5a9b3f756aaaf1074e43fa4":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: console.py change is one comment '
        'renumber (D-491 3 -> D-494 3) on _state_sink; no executable line changed; no stop, '
        'admission, dispatch, goal, traffic, auth or trust path changed; 60 host tests pass '
        '(map_pose_service incl. raising sink, trip_caps, server_console, site_map_trip); no '
        'device acceptance.',
    "611756f1e5d6fb5f5456dbb831c45d27baa7aa89":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: merge of main into '
        'feat/d491-fleet-map-pose; console.py is the plain union of the caps_for and guarded '
        'state-sink sides with no resolution edits (empty --cc diff); no stop, admission, '
        'dispatch, goal, traffic, auth or trust path changed; 60 host tests pass '
        '(map_pose_service incl. raising sink, trip_caps, server_console, site_map_trip); no '
        'device acceptance.',
    "c8eb84a769798065169dee920f37f29feea96f1f":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py adds a default-false trip_busy hook "
        "and refuses goal (unless trip=True) and formation_start with TRIP_ROBOT_BUSY for a robot on a "
        "running trip; task_dispatch_routes.py refuses /goal before a task is queued and the dispatch "
        "loop skips trip robots. Only refusals were added: estop_all, cancel, cancel-all, formation stop,"
        " D-421/D-430 latches and auth are unchanged, and no stop path is wrapped. 273 host tests pass at"
        " branch head 2dbb81946 (trip_runner, server_console, site_map_trip, cancel_all, lane_route, "
        "line_stuck_api, stuck_resolver_loop, dispatch_admission, dispatch_stop_latch, server_formation, "
        "server_traffic); probes confirm estop/cancel/cancel-all reach a trip robot; no device "
        "acceptance.",
    "7b2146db26853544a3d59204488517e85a6fc4b6":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py and task_dispatch_routes.py inline "
        "the same TRIP_ROBOT_BUSY refusals (set_trip_busy/refuse_trip_robot replaced by a trip_busy "
        "attribute and one guard per site); behaviour is the same as c8eb84a76 and only adds refusals. No"
        " stop, E-stop, cancel, traffic, auth or trust path changed; 273 host tests pass at branch head; "
        "no device acceptance.",
    "77a86a2775be6ac5e06d4119019a6111ed4ad593":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py net -2 lines: the TRIP_ROBOT_BUSY "
        "checks move to trip_guard.py, which wraps goal/formation_start/line_follow_mode on the instance "
        "(line_follow_mode OFF is always forwarded and also cancels the trip); FleetConsole inherits "
        "TripAware (trip_busy defaults to False); _make_room gives a trip robot no yield bay and it is "
        "never a degraded-capability reassignment candidate. estop_all, cancel, cancel-all and latches "
        "are unwrapped and unchanged; the trip runner's own cancel_goal is the pre-guard bound method (no"
        " recursion). 6773eb6b0 then wraps cancel and estop_all so every operator stop also ends the trip"
        " after the stop is sent (re-reviewed 2026-10-07). 287 host tests pass; no device acceptance.",
    "11db3176dd7f0163723b186ad8f987bf968297e0":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: task_dispatch_routes.py change is one '
        'comment renumber (D-491 5 -> D-494 5) on the existing TRIP_ROBOT_BUSY refusal in '
        '/goal; no executable line changed; no stop, admission, dispatch, goal, traffic, auth '
        'or trust path changed; 287 fleet host tests pass on the branch (trip_runner, '
        'server_console, site_map_trip, cancel_all, lane_route, line_stuck_api, '
        'stuck_resolver_loop, dispatch_admission, dispatch_stop_latch, server_formation, '
        'server_traffic); no device acceptance.',
    "6a4dc56c583dceddd1e3dbefc6c203f9be94ba48":  # git commit revision
        'Independent security-reviewer agent, 2026-10-07: merge of main (via bf3175039) into '
        'feat/d491-fleet-trip-loop. The --cc diff for console.py and task_dispatch_routes.py is '
        'empty, so there are no conflict-resolution edits. console.py against the first parent '
        "adds only main's own +10 lines (D-494 3 state sink with its try/except, already "
        'reviewed on main as a86afa7f7, f42bcc865 and bdbbd4001). Against main, console.py '
        "differs only by the branch's four reviewed one-line edits (TripAware import and base "
        'class, no yield bay and no reassignment for a trip robot), and task_dispatch_routes.py '
        'only by the reviewed /goal TRIP_ROBOT_BUSY refusal. trip_guard is still installed '
        "after the real-provider wiring, the runner's cancel_goal is still the pre-wrap bound "
        'method, and the dispatch loop still skips trip robots. No stop, E-stop, admission, '
        'traffic, auth or trust path changed; Fleet 2446 host tests pass, 0 new; no device '
        'acceptance.',
    "20d423a1a604197291eb83422a0683cac153de89":  # git commit revision
        'Independently reviewed by Codex /root on 2026-10-07: D-499 only adds a display '
        'link word to snapshot rows from the existing gather exception and cached address '
        'status. The provider is called once and its failure falls back to an empty map; '
        'no extra robot request, goal, stop, admission, or motion path was changed. '
        '40 focused Fleet tests passed with 0 new failures; no device acceptance.',
    "71e68b8c9f3b68337d2e6634475151eb6b01d37c":  # git commit revision
        'Independently reviewed by Codex /root on 2026-10-07: D-493 stores a monotonic '
        'observation time beside the gathered state, then copies the response row to '
        'display state_age_s and gathered_at. The internal stamp is removed before the '
        'response; no goal, stop, admission, or motion path was changed. '
        '40 focused Fleet tests passed with 0 new failures; no device acceptance.',
    "153daa0e9537cafe2b6ba031bb422d6fccf2b7fd":  # git commit revision
        'Independently reviewed by Codex /root on 2026-10-07: the console.py conflict '
        'resolution combines D-493 observation age with D-499 read-only link class in '
        'the same gathered row. The --cc diff adds neither a goal nor a stop path; '
        '40 focused Fleet tests passed with 0 new failures; no device acceptance.',
    "756634d24d97582720802dfde7fd7c39d63543b3":  # git commit revision
        "Independently reviewed (security-reviewer, read-only) on 2026-10-08: on the five "
        "safety-tagged paths (core_features/safety, dock/firmware, dock/firmware/rosy_dock, "
        "signal/firmware, signal/firmware/rosy_signal AGENTS.md) the commit only adds 'Parent "
        "context'/'Updated' header lines and corrects the rosy_signal parent comment from "
        "../../AGENTS.md to ../AGENTS.md; all parent targets exist on main. Markdown only; no "
        "code, config, firmware or build/flash change; no safety rule, fail-safe, interlock or "
        "auth text altered or made optional. Exemption approved by livsbittt.",
    "35945410f33f55daac79ac68aea73ab72e953b69":  # git commit revision
        "Independent safety review (oh-my-claudecode code-reviewer, opus, read-only) on "
        "2026-10-08, APPROVE WITH NOTES, no HIGH/CRITICAL, together with its follow-up "
        "32f98d98b: D-507 10 drops a D-422 memory point only when it is strictly inside the "
        "URDF outline on entry; the C1 blind disc (range_min 0.05 around LiDAR x -0.017) lies "
        "strictly inside the Pinky body (>= 6.5 mm margin), so no obstacle outside the body is "
        "hidden; a range_min reaching past the body still remembers outside points; all memory "
        "readers (tick, junction, lane_bridge, motion_admit forward/reverse) use the one "
        "filtered store. 77 tests passed. Its two MEDIUM notes became tests on "
        "fix/d422-memory-outside-body (C1 disc inside the body guard, contact on entry). "
        "Trailer missing because the commits landed before the review; SIM on model PC.",
    "32f98d98bd9aab0a1ef7242ad7080b502ff75d9b":  # git commit revision
        "Same independent safety review as 35945410f (2026-10-08, APPROVE WITH NOTES): the "
        "outline check runs once, on entry, so a remembered point that odometry later puts "
        "inside the body (creep into contact, in-place turn) keeps holding; inside_body(strict=) "
        "in core_common.robot_body keeps a point exactly on the outline (conservative). Creep "
        "and turn hold tests pass.",
    "b4f96a974df15956b41086587c5003bb0bdc9794":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: import-only; console.py takes the pure "
        "D-499 classify_link (link word for status rows, not on the estop_all path) from the frozen "
        "console_view edge, where the function is now defined (link_class.py removed). No new "
        "safety->decision module; estop_all and dispatch unchanged. Exemption approved by livsbittt.",
    "d69299d04b9b47fc6c2390963d32ab3f50b48e68":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: adds NOMINAL_BODY = PINKY_PRO alias and its "
        "public safety anchor; second name for an already public object, no new capability; "
        "robot_body.py stays in the literal backlog. Exemption approved by livsbittt.",
    "a7fab3bf383e27e992f92f1165d30d9bf67b85e9":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: clearance.return_scan_view: future-stamped "
        "scans within SOURCE_FUTURE_TOLERANCE_S (0.1 s) count as age 0, beyond it dropped; 0.25 s "
        "staleness bound unchanged; only feeds D-468 return evidence, not the D-422 body stop; scan "
        "sequence high-water kept. Exemption approved by livsbittt.",
    "c2fe98e028597c73084a882f680e9722e653bf6a":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: body_stop.py docstring wording only (Pinky C1 "
        "-> the C1 LiDAR); no executable change. Exemption approved by livsbittt.",
    "0f1e07f7effdc983fa2110dc21ba7b97fc9f40d2":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: console.py added read-only CORE power_health "
        "projection; superseded by 6d2ad7327 which moved it out of the console state; no command, gate "
        "or stop path reads it. Exemption approved by livsbittt.",
    "6d2ad7327628942f2a27d847ce852bbd6e4635c0":  # git commit revision
        "Independent security-reviewer agent, 2026-10-08: console.py removes the power_health display "
        "from FleetConsole state (traffic/swarm inputs); projection now per-response in console_routes, "
        "display-only. Exemption approved by livsbittt.",
    "b64ce7a4f3413eee968066ca2efa3386c7507c1a":  # git commit revision
        "Independent D-581 review, 2026-10-10: history-only exemption, NOT approval of this commit "
        "alone. Its missing anchor_hold and odom-epoch guard were repaired by 1c362f141, "
        "efba0585f and ee79d749a before the first remote main candidate containing D-581. "
        "Only the integrated ae08cac387 source was host-tested (24 passed); TRAIL driving remains "
        "HOLD. See docs/validation/d581-trail-anchor-safety-review-2026-10-10/result.md.",
    "198986fef42452854bbca127246f9435358e7306":  # git commit revision
        "Independent D-581 review, 2026-10-10: formation status reads an anchor from a relay "
        "double; read-only projection, no stop, rearm or command authority change. Historical "
        "exemption applies to the integrated ae08cac387 source only. See docs/validation/"
        "d581-trail-anchor-safety-review-2026-10-10/result.md.",
    "93ec99d5ba4b16934d5e6f01e5cfb4347488b09a":  # git commit revision
        "Independent D-581 review, 2026-10-10: moves the anchored relay factory into swarm/anchor; "
        "the TRAIL condition and per-session anchor construction remain. Historical exemption "
        "applies to integrated ae08cac387 only. See docs/validation/"
        "d581-trail-anchor-safety-review-2026-10-10/result.md.",
    "8754cc2b5ed904a000733ae2a92e83a3509e7225":  # git commit revision
        "Independent D-581 review, 2026-10-10: moves relay kwargs and status into the anchor "
        "helper; provided factory wins and missing poses keep the default relay/status None. "
        "Historical exemption applies to integrated ae08cac387 only. See docs/validation/"
        "d581-trail-anchor-safety-review-2026-10-10/result.md.",
    "03d530eab93e4ce911be5a6e442c27f99d55a214":  # git commit revision
        "Independent review by the integrating agent, 2026-10-10: app composition injects the "
        "same D-581 anchored relay factory; console removes a forbidden safety-to-decision "
        "import and retains provided-factory priority, default relay and read-only anchor "
        "status. Remote model-PC formation/CORE/D-430 tests 55 passed, 0 new failures. See "
        "docs/validation/d581-trail-anchor-safety-review-2026-10-10/result.md; driving HOLD.",
    "74b87f13b62890a5595a4c66914ac4aec9e5c1e6":  # git commit revision
        "Independent D-581 follow-up review, 2026-10-10: console.py only condenses the same "
        "app-injected relay selection and anchor status read to its existing 1251-line verdict. "
        "No stop, rearm, command, authority or D-430 import boundary changes; 16 focused "
        "remote tests passed with 0 new failures. See docs/validation/"
        "d581-trail-anchor-safety-review-2026-10-10/result.md; TRAIL driving remains HOLD.",
    "4c2b14ec8ec8d3a370f6bd008ea474d56650a180":  # git commit revision
        "Independent D-430 review, 2026-10-10: merge first-parent diff in safety-tagged "
        "body_stop.py changes only a robot-name comment. D-591 blind-floor behavior came from "
        "94a6aa65a, which has a Safety-Review trailer; no new executable stop logic in this merge. "
        "Remote AI/model-PC tests on follow-up af2933291f passed with 0 new failures. See "
        "docs/validation/d591-merge-safety-review-2026-10-10/result.md; device acceptance separate.",
}
MANIFEST = "tools/harness/platform_parts.yaml"
TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)
ZERO = re.compile(r"^0*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _exists(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _manifest(commit: str) -> dict:
    """Manifest at ``commit``; empty before it existed."""
    try:
        return yaml.safe_load(_git("show", f"{commit}:{MANIFEST}")) or {}
    except subprocess.CalledProcessError:
        return {}


def is_safety(path: str, roots: list[dict], modules: set[str]) -> bool:
    if path in modules:
        return True
    owner = max((root for root in roots if _under(path, root["path"])),
                key=lambda root: len(root["path"]), default=None)
    return owner is not None and owner.get("concern") == "safety"


def _is_safety_in(path: str, manifest: dict) -> bool:
    return is_safety(path, manifest.get("roots") or [], set(manifest.get("safety_modules") or ()))


def tagged(manifest: dict) -> set[str]:
    """Every safety tag: roots, modules and anchors (removing any is a safety change)."""
    anchors = {f"anchor:{anchor.get('symbol') or anchor.get('in', '') + '.' + anchor.get('string', '')}"
               for anchor in manifest.get("safety_anchors") or ()}
    return ({f"root:{root['path']}" for root in manifest.get("roots") or () if root.get("concern") == "safety"}
            | {f"module:{path}" for path in manifest.get("safety_modules") or ()} | anchors)


def _parents(commit: str) -> list[str]:
    return _git("rev-list", "--parents", "-n", "1", commit).split()[1:]


def needs_review(commit: str, range_manifests: tuple[dict, ...]) -> list[str]:
    """Why ``commit`` needs a trailer (empty when it does not)."""
    parents = _parents(commit)
    if len(parents) > 1:
        changed = _git("diff-tree", "--cc", "--no-commit-id", "--name-only", commit).split()
    else:
        changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "--root", commit).split()
    own = _manifest(commit)
    parent_manifests = [_manifest(parent) for parent in parents]
    manifests = (*range_manifests, own, *parent_manifests[:1])
    reasons = [f"touches {path}" for path in changed if any(_is_safety_in(path, m) for m in manifests)]
    # A merge untags only what every parent tagged; a branch's own removal is
    # reported on that branch's commit.
    kept = set.intersection(*(tagged(m) for m in parent_manifests)) if parent_manifests else set()
    reasons += [f"untags {entry}" for entry in sorted(kept - tagged(own))]
    return reasons


def resolve_base(base: str, head: str) -> str:
    if not base or ZERO.match(base) or not _exists(base):
        return f"{head}^"  # new branch or force push: the pushed tip only
    return base


def commits(base: str, head: str) -> list[str]:
    return [commit for commit in _git("rev-list", "--reverse", head, "^" + base, "^" + BASELINE).split()
            if commit not in EXEMPT]


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    args = [arg for arg in argv if arg != "--warn-only"]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base, head = args
    if not _exists(BASELINE):
        print(f"[safety-review] baseline {BASELINE} is not in this clone; fetch full history "
              "(actions/checkout fetch-depth: 0)", file=sys.stderr)
        return 0 if warn_only else 1
    base = resolve_base(base, head)
    range_manifests = (_manifest(head), _manifest(base))
    missing = []
    checked = commits(base, head)
    for commit in checked:
        reasons = needs_review(commit, range_manifests)
        if reasons and not TRAILER.search(_git("log", "-1", "--format=%B", commit)):
            subject = _git("log", "-1", "--format=%h %s", commit).strip()
            missing.append(f"{subject}\n    " + "\n    ".join(reasons))
    print(f"[safety-review] {len(checked)} commit(s) checked after baseline {BASELINE[:9]}")
    if not missing:
        return 0
    print("[safety-review] safety-tagged changes without a `Safety-Review: <reviewer/lane> <evidence>` "
          "trailer (D-430 section 5):\n" + "\n".join(missing), file=sys.stderr)
    return 0 if warn_only else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
