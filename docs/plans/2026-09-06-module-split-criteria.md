# Module split criteria — when a `rosy_core` module becomes a package

**Scope:** Python subpackages inside `src/rosy_core/rosy_core/`. Nothing here is about ROS packages.
**Sibling:** [2026-09-03-runtime-maintainability-rules.md](2026-09-03-runtime-maintainability-rules.md) owns launch files, ROS packages and deploy overlays. Its non-goal *"Do not add a new ROS package"* means exactly that — ROS packages, not Python subpackages. These two documents do not overlap.
**Operative copy:** a short checklist in [`src/rosy_core/rosy_core/AGENTS.md`](../../src/rosy_core/rosy_core/AGENTS.md). That file is loaded on every edit in the tree; this one is the reasoning behind it. If they disagree, this file is wrong and should be fixed.

## Why this exists

Every split in this package has been argued from scratch. That produces two failures in opposite directions: real defects survive because nobody wants to relitigate, and cosmetic reorganisations happen because "it's big" sounds like a reason. This file names what actually counts, so the argument happens once.

**The findings that matter most are the "leave it alone" rows.** They are what stops the next round of churn.

## How to apply

Run A → B → C in order and record the verdict — including "nothing fired". A criterion that no longer matches the tree is a bug in the criterion, not in the tree; re-derive before citing.

---

## Rule A — what a subpackage is here

*Descriptive, not a gate. It tells you what you are joining, not whether you may.*

Two kinds of directory live under `rosy_core/`:

- **Service packages** own one requirement family and are reachable through at least one `CoreServices` field: `command/`, `docking/`, `events/`, `navigation/`, `power/`, `safety/`, `state/`, `system/`, `waypoints/`.
- **Structural packages** are layers or adapters with no service field, and are **exempt from A3 by name**: `api/`, `bridge/`, `protocol/`, `web/`, `fleet_agent/`, `diagnostics/`.

| | Check | Escape hatch |
|---|---|---|
| A1 | Owns one requirement family, named in its own `AGENTS.md` Purpose | none |
| A2 | Has an `AGENTS.md` | none — 17 exist under `rosy_core/` |
| A3 | Maps to ≥1 `CoreServices` field, **or** is a named structural package | the list above |
| A4 | Behaviour is covered by some host test | if no test bears the package's name, the package's own `AGENTS.md` **Testing Requirements** must name the file that covers it — that is what makes A4 falsifiable rather than a shrug |

**Size is not in this table and must not be added.** See X1.
*(Amended 2026-09-22 by D-168 P6: size is still not a split criterion here, but a production file over 600 lines or a package over 10k lines must carry a recorded `split`/`accept` verdict in `test/test_module_structure.py`.)*

### Verification — all sixteen subpackages

*Hand-built. Re-derive before citing.*

| Package | A3 — `CoreServices` field | A4 — name-matching test |
|---|---|---|
| `api/` | — (structural) | `test_api.py` |
| `bridge/` | — (structural) | `test_bridge_translate.py`, `test_goal_tracker.py` |
| `command/` | `command` (+`registry`, `modes`) | **none** → `test_core_logic.py` |
| `diagnostics/` | — (structural) | `test_diagnostics_api.py` |
| `docking/` | `docking` | `test_docking.py` |
| `events/` | `events`, `audit` | `test_audit.py` |
| `fleet_agent/` | — (structural) | `test_fleet_agent.py` |
| `navigation/` | `nav` *(field name ≠ directory name)* | `test_initial_pose.py` |
| `swarm/` | `swarm` | `test_swarm.py`, `test_swarm_api.py`, `test_swarm_stream.py`, `test_swarm_integration.py`, `test_navigation_swarm_boundary.py` |
| `power/` | `power`, `battery` | `test_power.py`, `test_battery.py` |
| `protocol/` | — (structural) | `test_protocol_schemas.py` |
| `safety/` | `safety` | **none** → `test_core_logic.py` |
| `state/` | `state` | **none** → `test_core_logic.py` |
| `system/` | `runtime_probe` *(field name ≠ directory name)* | `test_host_runtime.py`, `test_ros_graph_monitor.py` |
| `waypoints/` | `waypoints` | **none** → `test_core_logic.py` |
| `web/` | — (structural) | `test_dashboard.py` |

A4 has no name-matching test for four packages — `command/`, `safety/`, `state/`, `waypoints/`. Each is covered by `test_core_logic.py`; the escape hatch requires that to be written in the package's `AGENTS.md`, not inferred here.

## Rule B — promoting a top-level module to a subpackage

Fires only when **all three** hold.

- **B1 — unowned family.** It implements a requirement family that no existing package's `AGENTS.md` claims. *Check:* grep the ID prefix across `rosy_core/**/AGENTS.md`.
- **B2 — two roles today.** It already needs ≥2 files with genuinely different roles, **or** work that adds the second file is scheduled and carries a requirement ID or checklist item. Name the second file and the ID that forces it. If you cannot, B2 is false.
- **B3 — cross-package consumers.** ≥2 distinct packages import it.

**One file with one role stays a module**, however many things import it.

---

## Published criteria

These generalise. Use them.

### C1 — a host-untestable decision

The file cannot be imported by host pytest **and** contains a decision — a branch, a conversion, a threshold, a status-code interpretation, an ordering — whose wrongness the CI boot smoke would not catch.

*Check (pasted output, run from `src/rosy_core/`):*

```
$ python -c "import rosy_core.bridge.ros_bridge"
ModuleNotFoundError: No module named 'rclpy'
```

`bridge/AGENTS.md` records the same fact from the other side: *"Host pytest does not import `ros_bridge.py`"*. Anything decided inside that file is decided where no host test can see it.

**Remedy:** extract the decision to a ROS-free sibling. This is not theory — the package has done it twice on its own, before this document existed:

- `bridge/translate.py` — message → dict conversion, asserted on real values in `test_bridge_translate.py`.
- `bridge/goal_tracker.py` — Nav2 goal generations, six real-value tests in `test_goal_tracker.py`, and `_goal_handle` deleted from `ros_bridge.py` rather than left beside it.

A criterion the codebase reinvents unprompted is describing something real. **C1 is the strongest criterion here.**

### C6 — a seam lie

A dependency reached through `hasattr`/`getattr` instead of a declared member, **or** a Protocol member that is not that Protocol's concern.

**C6 is a test, not a rule you have to remember:** [`src/rosy_core/test/test_module_criteria.py`](../../src/rosy_core/test/test_module_criteria.py) asserts **set equality** between the reaches in the package and the triage below. Add a reach — including a line-wrapped one, which a per-line scan would miss at `--max-line-length=120` — and it fails, naming the new one. That keeps this table true instead of true-on-the-day-it-was-written.

*What it does not catch, stated so the guarantee is not oversold:* a reach whose receiver is itself a call or a subscript (`getattr(obj["k"], ...)`, `getattr(self.dep(), ...)`), and anything reaching an attribute without `getattr`/`hasattr` at all. It gates the syntax C6 names, not every possible way to dodge a contract.

*Check (pasted output, at `5a5b7c3`):*

```
$ grep -rnE "hasattr\(|getattr\(self\.|getattr\(svc\." src/rosy_core/rosy_core/ --include=*.py
api/v1/safety.py:45:    deep = getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0)
api/v1/safety.py:141:        "battery_deep_percent", getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0))
docking/manager.py:170:        if getattr(self._safety, "estop", False):
docking/manager.py:199:        if getattr(self._safety, "estop", False):
docking/manager.py:261:        if self._manual_active or getattr(self._safety, "estop", False):
docking/manager.py:284:        if getattr(self._safety, "estop", False) and self._state in (
docking/manager.py:403:        voltage = getattr(self._battery, "voltage", None) if self._battery else None
power/manager.py:199:        return float(getattr(self._cfg, _RATE_ATTR[mode]))
system/host_agent_client.py:157:        if not hasattr(socket, "AF_UNIX"):  # pragma: no cover - Windows dev host
```

**The list lives in the test, not here.** `ALLOWED` in `test_module_criteria.py` is the
authoritative set and the only copy a change has to keep true; this paste is dated evidence
and these paragraphs are the reasoning. The two drifted apart within a day the first time
they were both treated as authoritative — the test lost the `navigation/manager.py` entry
when Step 2 removed that reach, and this section did not notice, because the test compares
the code against its own allowlist and has no opinion about prose.

The original nine reaches above remain the historical triage. The absorbed
ControlSensorAdapter and ROS node compatibility layer add fourteen reaches;
the readiness bridge adds four accepted public-state probes;
they are also published here so the set-equality test and this document stay
in lockstep. Since the Level-3 split (D-125) the test scans only the `core`
entry package: verdicts for files that moved to `core_api_web`/`core_features`
stay published below, but no per-package C6 scan covers them yet.

| Reach | Verdict |
|---|---|
| `api/v1/safety.py` ×2 — `getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0)` | **Seam lie.** Reaches a *private* field across a package boundary because `BatteryMonitor` (`power/`) exposes no public accessor to `safety/`. Fix: add `BatteryMonitor.deep_percent`. Whether SAF or PWR should own battery thresholds at all is a separate, open question. |
| `docking/manager.py` ×5 | **Accepted.** None-tolerance for optional injections whose attribute is part of the injected type's public surface. |
| `power/manager.py` | **Accepted.** Mode → attribute dispatch over the module's own config object. |
| `system/host_agent_client.py` *(moved to `core_api_web/api/` under D-126 S5; out of this package's scan)* | **Platform guard, not a seam.** `AF_UNIX` is absent on the Windows dev host. |

| Reach | Verdict |
|---|---|
| `api/v1/observability.py` — `adapter` → `calibration_digest`, `calibration_revision`, `enabled`, `revision` | **Accepted.** Admin diagnostics reads the optional adapter's public metadata through a compatibility-safe probe; it does not read a private implementation field or grant command authority. |
| `bridge/control_sensor_adapter.py` — `node` → `_sensor_only`, `bind_policy_handoff`, `destroy_node`, `observations`, `profile`, `refresh_profile`, and dynamic `name` | **Accepted.** The adapter validates and cleans up an injected ROS worker/test double and checks its sensor-only lifecycle surface. The dynamic `name` probe is the command-authority deny-list check. |
| `bridge/control_sensor_adapter.py` — `safety` → `bind_control_policy`; `observations` → `max_age` | **Accepted.** These are optional public hooks on injected CORE safety/observation objects used to bind policy and its lease; missing hooks fail closed. |
| `bridge/control_sensor_adapter.py` — `provider` → dynamic `attr` | **Accepted (D-126 S1).** Entry-point provider dispatch selecting one of the three provider factories (`make_node`, `make_policy`, `load_snapshot`). A missing provider or factory raises an install hint instead of an `ImportError`; no private field is reached. |
| `node.py` — `self` → `get_namespace` | **Accepted.** ROS namespace compatibility guard for the host test stub and the real `rclpy` node. |
| `safety/manager.py` — `policy` → `evaluate`, `revision`; `calibration` → `revision` | **Accepted.** D-64: SafetyManager duck-types Control policy/actuation public members so `safety/` does not import `rosy_control`. |
| `safety/manager.py` — `profile` → `max_linear_velocity`, `max_angular_velocity` *(raised by the config-catalog refactor, since removed)* | **Seam lie — fixed by deletion, not by a verdict.** `RobotProfile` is owned by `rosy_core` (`profile.py`), both members are declared `@property -> Optional[float]`, and `services.py` reads `profile.model` directly off the same object one line later — so `profile` is never absent and `None` already means *not set*. The `getattr` default added nothing except silence: rename the property and the robot would fall back to the default speed ceiling without a word, on the path that computes speed limits. No test ever exercised the default — both stubs in `test_core_logic.py` declare the attributes. Replaced with direct attribute access; the reach is gone, so `ALLOWED` gains no entry. |

**Resolved — the criterion earned its keep on first application.** `navigation/manager.py`
reached the executor through `hasattr(self.executor, "reset_mapping")`, a member no contract
declared and `RosBridge` never implemented, so `POST /api/v1/slam/reset` answered
`{"reset": true}` for a no-op. Fixed in D-32: the contract declares the member, the bridge
implements it and fails with `CAPABILITY_NOT_SUPPORTED`, and the probe is gone. A criterion
that finds a live defect the first time it is run is not an abstraction.

Line numbers above drift; the test keys on `(file, kind, receiver, attribute)` for exactly that reason.

The readiness gate added four accepted bridge probes: the injected
`services.readiness` object and the public `TransitionEvent.goal_state` with
its `id`/`label` representations. They are listed in the test allowlist and
are kept inside the ROS bridge; none reaches a private owner or adds a command
path.

### C7 — a service field whose methods span two requirement families

C5 (below) is defined over the *current* service graph, so it is a fixed point: it can see misplacement in the API layer and is structurally blind to misplacement in the service layer. C7 is the criterion C5 cannot express.

***C7 is review-only, and stays that way.*** The obvious mechanisation — grepping for requirement-ID banners — is a source-grep over comment text and would fire on every legitimate cross-family reference. Saying so plainly is better than implying a mechanism that does not exist. Its one live instance is recorded in `navigation/AGENTS.md` and its closure is bound to the `mapping/` trigger, which *is* machine-checked.

**Live instance:** `NavigationManager` carries NAV-005 mapping-session state (`mapping_active`, `start/stop/save/reset_mapping`) under a literal `# --- NAV-005 Mapping 세션` banner, inside a class whose module docstring and `AGENTS.md` both claim NAV-001~004/006. The code labels its own seam. Accepted for now — there is no `mapping` service for that state to move to.

---

## Worked verdicts

*Derived from one or two cases. These are records of a judgement, not general tests — re-derive before citing one as a rule.*

### C2 — unrelated lifecycles in one object

One class registers periodic callbacks for ≥3 domains that can fail independently. `grep -c create_timer` is the **finder, not the test**: it counts timers rather than failure modes (`_state_timer` and `_diag_timer` both feed the same snapshot), and it is per-file where the criterion is per-class. Applies to one class in the tree.

### C3 — two Protocols, one implementation

`RosBridge` satisfies `NavExecutor` (`navigation/manager.py`) and `DockingExecutor` (`docking/manager.py`). Both are `typing.Protocol`, and `RosBridge` declares **no base class** — conformance is duck-typed on both sides and marked only by comment banners. That does not weaken C3, it sharpens it: nothing in the type system records that one class answers to two contracts, which is why adding a member to either Protocol binds nothing at runtime.

### C4 — an aggregator carrying content

`api/v1/routes.py` states the rule in its own docstring: *"새 엔드포인트는 해당 도메인 모듈에 넣고, 새 도메인이면 모듈을 만들어 여기에 등록한다."* It obeys it today — zero `svc.` references. Recorded as the repo's rule, not as a finding.

### C5 — an API module with two service owners

**Rule (authoritative).** For each module under `api/v1/`, list the `svc.<field>` names its endpoints **mutate**, or that a **router in the file is named after**. **Reads do not count.** Drop the ambient set `{state, events, capability, modes, config}`. If ≥2 remain and they are backed by different subpackages or top-level modules, the module has two owners.

*The ambient set is ambient because those fields are cross-cutting infrastructure every domain touches — **not** because they are read-only. They are mutated all over: `svc.state` at `control.py:44` and `safety.py:25`, `svc.modes` at `control.py:41`, and `svc.config` is written and persisted to disk at `safety.py:150,154` and `system.py:89,92`.*

A grep is a candidate generator only. Applying it and stopping there is what produced the wrong answer the first time this table was written.

**Two owners is a finding, not automatically a split.** Record the verdict either way.

*Hand-built, derived under the rule above. Thirteen modules, excluding `__init__.py` — eleven before the `navigation.py` split below, plus the two it produced.*

| Module | Owners after the rule | Backed by | Verdict |
|---|---|---|---|
| `common.py` | — | — | **N/A** — shared auth dependencies, no endpoints |
| `routes.py` | — | — | **N/A** — aggregator (C4) |
| `host.py` | — | — | clean — owner set empty |
| `docking.py` | `docking` | `docking/` | clean |
| `map.py` | `maps` | `maps.py` | clean — a read-only module; ownership comes from `map_router`'s **name** |
| `waypoints.py` | `waypoints` | `waypoints/` | clean |
| `robot.py` | `power` | `power/` | clean — **three routers, one owner.** Router count is not the test |
| `swarm.py` | `swarm` | `navigation/` | clean |
| `observability.py` | — | — | clean. `svc.audit.history()` and `svc.started_at` are **reads**; `events_router`'s name matches the ambient `events` field, which the rule drops. Even counting the read, `audit` and `events` are both `events/` — one package |
| `system.py` | `identity` | `identity.py` | **clean.** `svc.identity.robot_id`/`robot_name` are mutated at `:61`/`:66`; `svc.runtime_probe.snapshot()` at `:152` is a **read**, and no router is named `runtime_probe`. One owner |
| `control.py` | `command`, `nav` | `command/`, `navigation/` | **fires** → verdict below |
| `safety.py` | `safety`, `battery` | `safety/`, `power/` | **fires** → verdict below |
| `navigation.py` | `nav` | `navigation/` | clean **now**. It fired with `{nav, maps, waypoints}` before the split below |

**Three of eleven fired** when this table was first derived. `navigation.py` has since been split, so two of thirteen fire today — both recorded accepts. An earlier draft of this table said four, by reading `system.py` off the raw grep instead of the rule — `runtime_probe` is a read. The rule caught its own author.

---

## Anti-criteria — these do not justify a split

Each cites an in-tree counter-example, because an anti-criterion without one is just an opinion.

- **X1 — line count.** `rosy_core/waypoints/manager.py` is 85 lines and is a package; `rosy_core/docking/manager.py` is 511 lines and is correctly one file. *(D-168 P6: line count alone still justifies nothing, but past the 600-line budget a verdict must be recorded.)*
- **X2 — symmetry.** `rosy_core/maps.py` is the last feature that is a top-level module rather than a package. That is an observation, not a defect; it stays a module because B2 is false.
- **X3 — speculative work.** `deploy/robot/config/capabilities.{core,motor,hardware}.yaml` all say `slam: false` and nothing deployed starts slam_toolbox, so a `mapping/` package would have no runtime to be verified against. Pre-building a home for unscheduled work is how empty packages happen.
- **X4 — test file size.** `src/rosy_core/test/test_docking.py` is 1157 lines. That is coverage, not debt. Never split production code to shorten a test file.
- **X5 — a long but fully host-testable file with one owner.** `rosy_core/docking/manager.py` again: 511 lines, one owner (`svc.docking`), covered by `test_docking.py`. There is nothing to gain — the seam a split would introduce is not load-bearing.
- **X6 — shrinking a diff during someone else's in-flight work.** `rosy_core/bridge/ros_bridge.py` was observed clean, dirty, and clean again over three days of swarm work. Refactoring a contended file is how conflicts eat commits. Wait for the branch.

---

## Verdicts

### `bridge/ros_bridge.py` — split **within** `bridge/` · **done, and bounded**

C1, C2, C3 and C6 all fired. Not a new package: ROS-101 keeps all ROS I/O in `bridge/`, and D-1 keeps the process single. The split was into ROS-free siblings inside `bridge/`, following `translate.py` and `goal_tracker.py`.

**The target is decisions covered by real-value host tests, not fewer lines** — and that target is met. Seven decisions now live in ROS-free siblings with real-value host tests: `translate.py`, `goal_tracker.py`, `display.py`, `reconcile.py`, `odometry.py`, `save_map.py`, `battery_policy.py`. What remains in `ros_bridge.py` (516 lines) is registration, one-line callbacks delegating to those siblings, and the Nav2 action plumbing. **C1 no longer fires on anything in it**: there is no remaining decision host pytest cannot see.

Note the corollary, learned from `goal_tracker.py`: extracting *stateful* logic can make the caller **longer**, because the sibling absorbs the algorithm and the call site grows the wiring. Net line count is not the measure.

**C2 and C3 still fire, and are accepted — see the accept-row below.**

### mapping — **no `mapping/` package**

B1 holds (no package claims MAP) and B3 holds — three importers across two packages plus a top-level module (`api/v1/map.py`, `bridge/ros_bridge.py`, `services.py`), but **B2 fails**: `maps.py` is one file with one role, and the second file exists only in unscheduled work. X3 applies independently — there is no runtime to verify against.

`maps.py` does **not** belong with SLAM, and would not even if `mapping/` existed. They share a word, not a concern:

| | `maps.py` | mapping / SLAM |
|---|---|---|
| Direction | read path — ROS subs → dashboard | write path — operator action → disk |
| Lifetime | ephemeral, last-value in memory | persistent artifact, survives reboot |
| Cadence | 5–10 Hz, continuous | discrete, operator-initiated |
| Failure cost | a stale tile in the UI | a lost survey run |
| Test shape | pure value assertions | service-call sequencing, needs slam_toolbox |
| ROS coupling | none, by construction | needs the optional dependency |

**The name is the real problem** — `maps.py` reads as though it owns maps. Renaming it was considered and rejected: it buys clarity at the cost of history churn, and the same clarity is free in the module docstring and the `AGENTS.md` row.

#### `mapping/` re-entry trigger

All three, or no package:

1. A launch reachable from one of the three deploy overlay **modes** starts slam_toolbox, and that overlay sets `slam: true`. **Machine-checked** by `test_slam_capability_requires_a_launch_that_actually_starts_slam_toolbox` in [`test/test_robot_runtime.py`](../../test/test_robot_runtime.py) — it fails the moment an overlay advertises slam the launch tree cannot deliver, and names this trigger. *(The standalone `rosy_navigation` map-building launches do start slam_toolbox, but no overlay mode includes them — which is why the condition reads "reachable from a mode".)*
2. MAP-003 upload or Flask parity item N-1 is scheduled — i.e. a second file with a distinct role can be named.
3. B3 still holds.

When it fires, `slam_router` moves out of `api/v1/navigation.py` in the same change, and C5 will say so on its own.

### `api/v1/navigation.py` — split three ways · **done**

C5 fired with `{nav, maps, waypoints}`. Resolved: `map_router` → `api/v1/map.py`, `waypoints_router` → `api/v1/waypoints.py`, leaving `navigation.py` with `{nav}`.

`slam_router` **stays** in `navigation.py` — not because `nav` is the right owner, but because **there is no `mapping` service for it to belong to**. That distinction matters: the underlying misplacement is the C7 instance above, and it is recorded rather than blessed. `navigation_path()`'s `svc.maps.get_path()` is a read and does not make `navigation.py` a two-owner module.

### Newly exposed, and accepted

- **`api/v1/control.py` → `{command, nav}`.** `svc.nav.cancel()` inside a mode transition is coordination, not ownership: leaving a navigation mode must stop navigation. Splitting would put half a state transition in each of two files. **No action.**
- **`api/v1/safety.py` → `{safety, battery}`.** `svc.battery.apply_thresholds()` is a `power/` object mutated from a `safety/` endpoint — one settings write that must land atomically across both. **No split**; fix the *access shape* only (the C6 `_cfg` reaches → a public `BatteryMonitor.deep_percent`). Whether SAF or PWR owns battery thresholds is genuinely open and larger than this document.
- **`NavigationManager` — the C7 instance.** NAV-005 mapping-session state on a NAV-001~004/006 manager. Accepted; unblocks on the `mapping/` trigger. Recorded in `navigation/AGENTS.md`.
- **`RosBridge` — the C2 and C3 instances. Accepted; the per-domain adapter reshape (3b) is declined.**

  **C2** — six timers across five independently-failing domains. **C3** — one class satisfying `NavExecutor` and `DockingExecutor`, both `typing.Protocol`, with no declared base.

  **Why declined.** Both are *worked verdicts*, not published criteria — records of a judgement over one class, which is what this section is for. Three reasons, in descending weight:

  1. **The stated target is met.** The verdict above defines it as *"decisions covered by real-value host tests, not fewer lines."* The extraction delivered exactly that. Reshaping the remaining wiring into per-domain adapters buys class shape, which that sentence names as not the objective.
  2. **Neither benefit is worth what it costs here.** C2's real content is fault isolation between timer ticks — but D-1 keeps the process single, so adapters built by a composition root share the executor and the coupling exactly as today. Only the source file changes. The isolation C2 actually wants is a per-tick `try/except`, which `_tick_swarm` already has; extending it is a **per-timer judgement, not a blanket edit**, and on the D-2 `cmd_vel` timer a guard is *harmful* — swallowing there means the robot silently stops receiving velocity commands while the node looks healthy. That change alters failure behaviour on the D-2 and SAF-005 paths and needs Pi evidence.
  3. **The gate cannot see the reshape's failure modes.** `test/test_bridge_timers.py` now pins callbacks, QoS and the four clients, which is a real gate — but CI boot smoke does not currently run (this repository has no remote), and no Pi evidence is available. A timer-ownership change whose primary risks sit in the semantic layer the harness disclaims does not merge on a document's tidiness.

  **Rejected remedy, recorded so it is not re-proposed.** Declaring `class RosBridge(NavExecutor, DockingExecutor)` looks like a one-line fix for C3 — nominal instead of duck-typed conformance. **It is worse than the status quo.** Protocol members are declared with `...` bodies, so explicit subclassing *inherits them as methods returning `None`*: a member added to the Protocol and forgotten on the bridge becomes a **silent no-op** instead of an `AttributeError`. Verified:

  ```
  duck-typed, missing member : AttributeError -> 'Duck' object has no attribute 'forgotten'
  explicit Protocol base     : returned None  <-- SILENT NO-OP
  ```

  That is D-32's exact failure shape — the defect this plan's Step 2 existed to fix. Duck typing plus `test_executor_contracts.py`'s AST check is strictly safer: the omission raises loudly at runtime *and* fails a test at author time.

  **X6 applies independently:** `ros_bridge.py` is under active contention across five worktrees and the DDS Phase 0 measurement work.

  **What holds the line instead.** `test/test_bridge_timers.py` pins six timers with periods and order, seventeen subscriptions with callback and QoS, five publishers with QoS, four service clients, the action client, the TF listener and both executor wirings. `test/test_executor_contracts.py` pins both Protocols' member sets and the five diagnostics providers. Together these make the accepted violation *stable* — it cannot silently grow — which is what an accepted violation has to be.

  **Re-entry trigger.** Any one of: (a) a seventh timer, or a sixth independently-failing domain, is added to `RosBridge`; (b) a third Protocol is satisfied by it; (c) a Pi becomes routinely available **and** CI boot smoke runs on the branch. Until then this is a recorded accept, not a backlog item.
