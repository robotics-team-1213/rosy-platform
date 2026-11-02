# Rosy Docking Station Design

## Objective

Give the robot somewhere to charge and a way to get there on its own, and give
the software a trustworthy answer to "is it actually charging".

Docking has been a declared stub since the first SRS: `docking.supported=false`,
`501` on the two endpoints, priority slot 4 reserved and unused
([`arbitration.py:25`](../../src/rosy_core/rosy_core/command/arbitration.py)),
`RobotMode.DOCKING` present in the enum and never entered. This document turns
that stub into a system: a dock we design and build, a detection boundary, a
state machine, a charge signal that exists, and a return policy that fires
before the pack is too flat to act on it.

It builds directly on the
[battery integrity work](2026-09-02-battery-integrity-low-battery-alert-design.md),
which had to land first — return-to-dock triggers on state of charge, and
before that work state of charge was pinned at zero on real hardware.

## What the code already decided

Three things in the tree constrain this design before it starts.

### RETURN_HOME is E-Stop in disguise

`NavigationManager.home()` resolves the reserved waypoint `__home__`
([`manager.py:99`](../../src/rosy_core/rosy_core/navigation/manager.py)) and
`WaypointManager.get()` raises `WaypointError` when it is absent. `ros_bridge`
catches that and trips E-Stop. **Nothing in the tree ever creates `__home__`** —
it is a name a human must register. So on a robot nobody has taught a home
pose, the shipped `battery_critical_policy: RETURN_HOME` behaves as `STOP`.

That is the safe direction and not a defect, but it means the existing critical
policy has never actually driven a robot anywhere. Return-to-dock is the first
implementation of that promise, and the dock is a far better target than
`__home__` because arriving there does something.

### The mode table forbids NAVIGATION → DOCKING

`_ALLOWED` permits `DOCKING` only from `IDLE`, and out only to `IDLE` or
`EMERGENCY`
([`arbitration.py:40-46`](../../src/rosy_core/rosy_core/command/arbitration.py)).
The obvious sequence — navigate to the staging pose, then switch to docking —
is not expressible.

The fix is not to add an edge. **The docking action owns the whole sequence**,
including the Nav2 leg, and the robot is in `DOCKING` from the moment the
command is accepted until it is docked or has failed. This is what Nav2's
`opennav_docking` does (its action calls `NavigateToPose` internally), it leaves
the transition table untouched, and it gets the priority right for free:
`DOCKING` is 4 and `NAVIGATION` is 5, so a fleet navigation command cannot
preempt a robot that is halfway into a dock.

### A dock is not a waypoint

`Waypoint` carries `name`, `x`, `y`, `yaw`, `map_id`
([`waypoints/manager.py:15-20`](../../src/rosy_core/rosy_core/waypoints/manager.py)).
A dock additionally needs its type, its staging offset, the address of its
agent, and its charge contract. The dock database is a new store. It does not
replace waypoints and does not extend them: a dock's *pose* is the same kind of
thing a waypoint holds, but a dock is a device.

## Map is coarse, sensor is fine

The single most important property of any docking system: **the map gets the
robot near the dock and is then discarded.**

AMCL localisation error is routinely ±10 cm and can be worse after a long
traverse. Charge contacts engage within a few millimetres. The gap is two
orders of magnitude, so a controller that drives to the dock's recorded map
coordinates and stops will never dock. Every stage of the approach after
staging closes the loop on the dock as *observed*, not as recorded.

```
[1] staging drive        [2] acquisition       [3] approach        [4] settle
Nav2 NavigateToPose      detector finds dock   servo on relative   confirm charge
dock pose from database  relative pose         pose, contact       from the dock
±10~30 cm                ±1~3 cm               ±3~5 mm             electrical
map is used              map discarded         map irrelevant      —
```

The dock's map pose therefore has exactly one job: compute a staging pose in
front of it. It is allowed to be a few centimetres wrong.

### Teaching the pose

The pose is recorded by **teach-by-docking**: push the robot into the dock by
hand or by teleop, then record the robot's current map pose as the dock pose.
Nobody measures a dock with a tape against a SLAM map and gets a usable number.
`POST /api/v1/docking/docks/{id}/teach` captures it.

This also makes the recorded pose self-consistent with the map that will be
used to return to it, including whatever distortion that map has.

### The dock is an obstacle to the costmap

A dock is a solid object in front of a wall, so SLAM maps it and the local
costmap treats it as something to avoid. Left alone, the robot refuses to
approach the thing it is trying to reach. Nav2 handles this with
`dock_collision_threshold`, disabling collision checking inside a radius of the
dock; this design does the same and confines it to the approach phase, so the
exemption cannot leak into ordinary navigation.

## Detection stays behind a boundary

The choice between a LiDAR retro-reflector pattern, an IR beacon and a camera
tag is **not made here**, because it depends on whether the camera gets a real
driver — currently it exists in URDF and simulation only, with no `v4l2`,
`libcamera` or `apriltag` anywhere in the tree — and that is its own spec.

Deferring it is cheap if the boundary is drawn now:

```python
class DockDetector(Protocol):
    def start(self, dock: DockInstance) -> None: ...
    def relative_pose(self) -> Optional[DockObservation]: ...   # base_link 기준
    def stop(self) -> None: ...
```

Everything in this document consumes `DockObservation` and nothing consumes a
scan, an image or an IR reading. Two detectors ship: a `SimulatedDetector` that
replays a pose so the state machine can be tested without hardware, and
whichever real one the camera decision produces.

The provisional choice remains LiDAR reflectors for acquisition plus the
forward IR array for the final centimetres, for reasons that survive the camera
question: docking must work in the dark, the IR array at `x=0.0295, z=-0.015`
sits at contact height while the camera at `z=0.0495` loses the marker at close
range, and returning to charge should not itself cost CPU and power.

## The dock is instrumented

There is no charging signal on this robot. `rosy_sensor_adc` publishes
`batt_state` with `current`, `temperature` and `percentage` as NaN and
`power_supply_status` hardcoded to `UNKNOWN`
([`main_node.cpp:147-153`](../../src/rosy_sensor_adc/src/main_node.cpp)). The
strongest confirmation Nav2's docking framework offers — `use_battery_status` —
is unavailable, and the weakest — a distance threshold — confirms neither
contact nor conduction.

Since the dock is ours to design, it measures instead. An MCU in the dock reads
charge current and reports it, which keeps the robot hardware untouched and
gives a true electrical answer rather than an inference.

It also solves a hazard that has nothing to do with software. Exposed DC
contacts sitting on a floor at pet and toddler height, permanently energised,
are a short-circuit and foreign-object risk. **The dock energises its contacts
only after it detects a load** and de-energises when the load leaves. That
requires a controller in the dock regardless of what the robot wants to know,
so the marginal cost of also reporting current is close to zero.

### Dock agent contract

The robot polls; the dock never initiates. The dock does not know which robot is
approaching, the robot knows exactly which dock it is going to (the address is
in its dock database), and an inbound path into the robot's API would be one
more unauthenticated surface for no gain. Routing through Fleet was rejected for
a blunter reason: a robot must be able to charge when Fleet is down.

Polling runs only during a docking sequence and while docked, so it costs
nothing on a robot going about its work.

```
GET http://<dock-address>/status
{
  "dock_id": "dock_1",
  "firmware": "1.0.0",
  "output_enabled": true,
  "load_present": true,
  "charging": true,
  "current_a": 1.42,
  "output_voltage_v": 8.31,
  "faults": []
}
```

`load_present` and `charging` are different questions. Contacts can be engaged
while no current flows — an oxidised contact, a full pack, a protection board
that has latched. Reporting them separately is what lets the robot distinguish
"I am parked in a dock that is not charging me" from "I never made contact",
and those need different recoveries: the first is a fault to report, the second
is a retry.

### Never trust the dock alone

A device on the LAN asserting `"charging": true` must not by itself convince the
robot it is charging, because the consequence of believing it is that the robot
sits still and drains. **Charging is accepted only when the dock reports current
*and* the filtered pack voltage is not falling** over a confirmation window. The
`BatteryMonitor` from the battery work already owns a filtered voltage, so this
costs one trend check.

This matters most for the interlock in the next section, where a false charging
claim would suppress a safety shutdown.

## Charging must suppress the deep shutdown

This is the sharpest interaction with the battery work and it is a defect if
missed.

[D-27](../reference/ROSY%20ADR%20Log.md) halts the host when the pack holds the
`deep` level past its dwell. A robot that reaches a dock at 4% and starts
charging is still at `deep` for some minutes. Without an interlock the host
halts **while sitting on the charger**. The pack charges — that is electrical —
but the robot never comes back: [D-25](../reference/ROSY%20ADR%20Log.md)
established that a halted Pi 5 has no wake source but the power button and an
RTC alarm. A robot that successfully returns to charge and then bricks itself
until somebody walks over is worse than one that simply ran flat.

So confirmed charging suppresses the deep escalation: the shutdown does not arm,
and an armed request is withdrawn. Confirmed, per the previous section, means
the dock reports current *and* voltage is not falling — precisely so that a
misreporting or spoofed dock cannot disable a safety path.

This amends D-27's interlock list and needs recording there.

## Return to dock

### At 20%, not 10%

SAF-005's critical threshold is 10%. On a 2S lithium-ion pack that is inside the
steep part of the discharge curve, where the remaining energy is small and the
estimate is at its least reliable. Leaving for the dock from there risks
stopping on the way, which is the worst outcome available: the robot is now
flat, not at its charger, and possibly in a doorway.

Return therefore fires at the **warning** threshold, 20%. The robot abandons its
task earlier than it strictly must, and that is the intended trade.

The existing SAF-005 rows are unchanged. Return-to-dock is a new action attached
to the warning level, and the critical row keeps `RETURN_HOME` or `STOP` as the
fallback for a robot with no dock, which is every robot until one is built.

### No energy budget, and why

The obvious refinement is to ask Nav2 for the path length to the dock and
compare it against remaining charge. It is not in this design.

Converting remaining percent into remaining metres requires knowing the energy
cost per metre, and with no current sensor there is nothing to measure it with.
Any coefficient would be a guess presented as arithmetic, and the failure mode
is silent: a robot that computes it can reach the dock, and cannot. A fixed
threshold with margin is honest about being a fixed threshold.

The pieces to do it properly arrive together — a current sensor makes both the
budget and coulomb counting possible — and that is a later decision.

### What it interrupts

Returning to dock cancels the active navigation goal and takes `DOCKING` mode,
which outranks `NAVIGATION` and `FLEET`. A fleet mission in progress is
abandoned and reported as such; a robot that runs flat mid-mission has abandoned
it too, and more expensively.

Manual control (priority 3) still outranks docking. An operator with a teleop
session keeps it, and the return is retried when they let go. E-Stop outranks
everything, as always.

## State machine

The contract in DNC-003 names `DOCK/UNDOCK/CHARGING/DOCKED/DOCK_FAILED` and
leaves the detail to the API Reference. It has no state for "not docked", which
is where a robot spends most of its life, and it conflates the act of docking
with the outcome. This design refines it:

| State | Meaning |
|---|---|
| `UNDOCKED` | Default. Not at a dock, not trying. |
| `DOCKING` | Sequence running. Robot mode is `DOCKING`. |
| `DOCKED` | Contacts engaged, charging not confirmed. |
| `CHARGING` | Dock reports current and voltage is not falling. |
| `UNDOCKING` | Reversing out on odometry. |
| `DOCK_FAILED` | Gave up after `max_retries`. Terminal until commanded. |

Adding enum values is additive at the protocol level (PRT-006), so this is a
MINOR protocol bump and an API Reference update, not a break.

`DOCKING` has internal phases that exist because retries need to know where
they failed:

```
STAGING ──► ACQUIRING ──► APPROACHING ──► SETTLING ──► DOCKED ──► CHARGING
   │            │              │              │
   │            └──────┬───────┘              │ no current
   │                   │ lost / timeout       │ within timeout
   │                   ▼                      ▼
   └───────────► back off, re-stage, retry (≤ max_retries) ──► DOCK_FAILED
```

`SETTLING` is separate from `DOCKED` because arriving is not charging. Contact
oxidation and a mis-seated pin both present as a successful approach that never
draws current, and they are worth distinguishing from a failed approach — the
recovery is a small re-seat, not a full re-stage.

### Undocking runs blind on purpose

`UNDOCKING` reverses in a straight line on odometry alone, with the detector
stopped and Nav2 not yet resumed. Half-inside a dock the LiDAR is looking at a
wall 3 cm away and the camera, if any, at the same. There is nothing worth
believing until the robot is clear, so it drives a known distance and only then
hands control back.

### Interlocks

- Docking requires `capability.docking.supported`; otherwise `501`, unchanged.
- `DOCKING` is entered only from `IDLE`, per the existing table.
- E-Stop at any phase aborts to `DOCK_FAILED` and releases the mode.
- The costmap collision exemption exists only in `APPROACHING`.
- Confirmed charging suppresses the D-27 deep shutdown.
- `DOCK_FAILED` does not retry on its own. A robot that failed to dock twenty
  times unattended has a physical problem, and a loop would hide it while
  draining the pack it was trying to save.

## Dock hardware

The pieces that do not depend on the detection choice can be specified now.

**Docking direction is forward.** The IR array and the ultrasonic sensor both
face `+X` ([`rosy.urdf.xacro:262-288`](../../src/rosy_description/urdf/rosy.urdf.xacro)),
so driving in forwards keeps the alignment sensors pointed at the dock for the
entire approach. Rear docking would need sensors the robot does not have.

> **2026-11-01:** [D-950](../adr/D-950-docking-direction-rear-entry.md) changed the docking direction to rear (reverse) entry (user decision). The paragraph above is kept as history.

**Mechanical guidance absorbs what the controller cannot.** A funnel geometry
with sloped side walls converts a lateral error of a centimetre or two into a
correct final position, and wide contact pads tolerate the rest. Every docking
system relies on this; a controller that must be millimetre-accurate on its own
is a controller that fails on a dusty floor.

**Contacts.** Spring-loaded pins in the dock against flat pads on the robot, at
the robot's front-bottom near the IR array height. Pins in the dock rather than
on the robot because the dock is the part that can be serviced without opening
the robot, and the sprung side wears first.

**Electrical.** The dock holds the charger — CC/CV to 8.4 V for the 2S pack —
and the robot side is contacts plus reverse-polarity protection. The pack's
protection board stays the last line of defence and is not relied on for normal
termination.

**Controller.** An MCU that senses load, energises only when a load is present,
measures current, serves the status endpoint, and de-energises on removal or
fault. Its firmware lives in a top-level `dock/` with the contract documented beside
it — **not** under `deploy/`, which means "how this robot is installed and
updated". The dock is a different device, and filing its firmware next to the
robot's OS image would suggest it belongs in the robot's release bundle.

## One dock per robot, a schema for more

Implementation targets a dedicated dock per robot: no occupancy contention, no
reservation, no Fleet arbitration, and a much smaller state machine.

The schema and API are nonetheless shaped for a pool — `docks` is a collection
keyed by id, each with a type, and the API takes a dock id rather than assuming
one. That is Nav2's split between `dock_plugins` (types) and `docks`
(instances), and adopting it now costs almost nothing while a later pool does
not have to break the contract.

What is deliberately *not* built: reservation, occupancy broadcast, and
"somebody else took it while I was driving" recovery. Those are a Fleet
concern, and guessing at them now would produce a protocol nobody has tested
against a real second robot.

## Module layout

```
rosy_core/docking/
    manager.py     DockingManager — state machine, retries, policy. ROS-free.
    database.py    DockInstance, DockType, teach/load/save.
    detector.py    DockDetector protocol + SimulatedDetector.
    agent.py       HTTP client for the dock's status endpoint.
dock/              ESP32 firmware and its contract (separate device).
```

`DockingManager` takes an injected clock, a detector, a dock-agent client and a
motion executor, and is tested without ROS — the same shape as `PowerManager`
and `BatteryMonitor`. `ros_bridge` supplies the real executor and detector and
reconciles, as it does for every other policy in this codebase.

## Non-goals

**Detection implementation.** Behind the plugin boundary, pending the camera
spec.

**Energy budgeting.** Needs current sensing.

**Multi-robot dock sharing.** Schema only.

**Charging optimisation.** Charge profile, cell balancing and top-up scheduling
belong to the charger hardware, not to this software.

**Automatic recovery from `DOCK_FAILED`.** Deliberate; see interlocks.

## Verification

The state machine, retry counting, phase transitions, interlocks and the
charging-suppresses-shutdown rule are all ROS-free with an injected clock and a
`SimulatedDetector`, so they are pytest, in the manner of `test_power.py` and
`test_battery.py`.

The dock agent client is tested against a stub server for: unreachable dock,
timeout, malformed JSON, a dock reporting `charging` while voltage falls, and a
dock reporting a fault. None of these may raise into a callback and none may
produce a confident wrong answer.

What only hardware can settle, and what belongs on the acceptance checklist: the
funnel's real capture envelope, the approach success rate from a spread of
starting poses, contact resistance after a hundred cycles, whether the dock
appears in the costmap in a way the exemption actually clears, and that a robot
which docks at 4% charges rather than halting on the charger.
