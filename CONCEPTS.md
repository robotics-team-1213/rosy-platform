# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Platform and execution roles

### ROSY Platform

The whole product: device-local execution, site coordination, observation, human interfaces, and future AI/data/deployment roles. It is not one operating-system replacement or one process. `ROSY OS` remains a historical repository and artifact name (D-290, D-296).

### Device middleware

The local contract and control boundary of one robot or workcell. It validates and accepts permitted requests, exposes observed state and effective capability, arbitrates the single final command owner, and handles loss or stale state locally. Pinky CORE implements this role for the mobile base. An OMX local controller must own final arm commands after its separate device acceptance; mounting OMX on Pinky does not transfer that authority to CORE or Fleet (D-296).

*Avoid:* using `middleware` alone to mean both this local role and the site Fleet service.

### Fleet

The site mission coordinator and durable task ledger. It selects and sequences admitted device actions through device APIs, records handoffs and evidence, and distinguishes acceptance from completion. It does not publish final base velocity or arm trajectory (D-12, D-290, D-293, D-296).

### Fleet Mission, Mission Step, Device Action, Local Transaction

A Fleet Mission owns site order, priority, handoffs and result history. Its Mission Steps request bounded Device Actions through device APIs. A Local Transaction sequences work inside one accepted action, such as approach, grasp and place; it does not own final actuator commands or a second site Mission DSL. An Episode records observed execution evidence. These are target terms; the current Fleet `/api/fleet/tasks/*` tracks durable navigation requests, not a general Mission engine (D-298).

### Action identity and message identity

A Device Action has a lifecycle across multiple submit, read, cancel, feedback and result exchanges. `action_kind` describes the work (currently `PICK_PLACE` in the OMX grant), `action_id` identifies that work, and `attempt_id` identifies its execution attempt. The current first slice binds one attempt to an Action; automatic multi-attempt execution is not enabled.

PRT `Envelope.type` and `msg_id` describe a message. UDS `operation` selects an operation on the Action. These fields do not replace Action identity. `GetAction` currently sends only `action_id`; Fleet validates the returned attempt and full grant scope. Repeated reads do not create an execution or a journal event. Top-level PRT `correlation_id` is schema-only today; it must not be presented as implemented end-to-end correlation. See D-369 and `docs/plans/2026-09-30-action-message-identity-design.md`.

### Stop evidence

Request sent, device response, local safety latch, zero-motion readback, and physical E-stop/driver interlock are distinct observations. The current Fleet `estop` response's legacy `stopped` count means HTTP response received from CORE, not verified physical stop. A missing response leaves the result unknown (D-298).

### ROSY Runtime

A target-architecture name for node-local execution. It does not imply a universal `rosy-runtime-base` package, one process, or a shared ROS graph on all hosts (D-296). The source directory `src/runtime/` is a code grouping, not a deployment unit.

### 호스트 에이전트 (Host Agent)
The one ROSY process on a robot that holds host privilege — network mode, Wi-Fi, release rollback and recovery-hold clearing. CORE reaches it and relays its answers; browsers never talk to it directly.

*Avoid:* `Host Agent` in operator copy — the screen says 호스트 에이전트; the English name stays in code, logs and API codes (`HOST_AGENT_*`).

When it cannot be reached, every host action it would carry is blocked for the same reason, so the screen states that cause and its next step once for the whole group rather than beside each button.

## Robot commissioning

### Robot number
The single value that identifies one physical robot within a fleet, chosen when the unit is commissioned and never inferred from anything else.

Everything else about a unit's identity derives from it, so it is the only identity value a person supplies. It is a plain decimal with no leading zero — a leading zero is refused rather than interpreted, because shell arithmetic and zero-padded formatting can read the same written value as two different numbers and agree with each other while both are wrong. Its upper bound is whatever keeps the derived domain inside the range the host operating system reserves for it.

### Robot identity
The pair of a robot's DDS domain and its ROS namespace, derived together from one Robot number.

*Avoid:* confusing the ROS identity pair with API `robot_id`, which is the existing public robot key.

The two halves must agree, because separating robots by domain alone still leaves their topic names colliding. Identity is device state, not repository content: no template, installer default, or compose default supplies it, and a missing identity stops the runtime rather than being filled in — a default is what once shipped every unit with the same one. Re-provisioning a unit under a different number fails loudly instead of renumbering it in place, and all derived values are validated before any of them is written, so a unit is never left half-migrated.

### Runtime mode
The staged install/hardware preset a unit runs at: core, then motor, then hardware, each admitting more physical hardware than the last.

*Operator word:* 실행 모드 (화면 문구는 실행 모드; `core`·`motor`·`hardware` 값 자체는 `title`에만)

*Avoid:* profile, 프로필

Core is the safe default a unit boots into and the only one that starts no motion hardware; motor adds the drivetrain for bench commissioning; hardware adds navigation and the remaining sensors. Promotion is explicit and is expected to be re-earned after an update or rollback. A board catalog may define aliases that resolve to one of the three; anything that resolves to none of them is an error rather than a fallback.

### Recovery hold
A recorded refusal that stops a unit's runtime from starting after a release failed to prove itself healthy.

A hold is evaluated before the runtime starts, and its verdict is specifically "does this block the runtime" rather than "did everything succeed" — the two differ, and keying on the latter is how a held device boots anyway. The gate expresses its verdict as a process exit status, and nothing in the boot path may retry or restart past it, since either would convert a hold into a boot.

## Domain objects

v1 maps the concept OS objects onto CORE + D-62 slices (D-65). Code names below are the types that will hold this data; they are not a second runtime.

### Node
The computer that runs CORE — hostname, architecture, OS, software version, runtime mode, and active slices.

*Code:* `RuntimeNode`

*Avoid:* rclpy node. ROS nodes stay an implementation detail inside the CORE process (D-1).

### Device
The physical robot CORE manages. Its `device_id` is the ROS namespace derived from the Robot number.

*Code:* `Device`

*Avoid:* treating Nav2, a driver, or a compose service as a Device.

For proposed OMX workcells, `Device` means an independently assigned control/stop boundary. A host may run multiple device instances; a mounted OMX arm does not inherit Pinky's final arm command owner (D-282, D-296).

### Component
A functional part of a Device — drivetrain, lidar, encoder, and the rest listed from the mounted hardware YAML or capabilities.

*Code:* `Component`

### Capability
An advertised boolean or descriptor of what the Device can do. It is not a scheduler and does not start work.

*Code:* `Capability`, `CapabilityDescriptor`

*Operator word:* 기능 (도킹 관련은 도킹 기능)

*Avoid:* `rosy-profile-*` as a capability. Install presets and D-62 slices are not capabilities. 운용자 문구의 `capability` 영어 표기.

### Asset
v1 is the single Device (`type=mobile_base`, `asset_id=robot_id`).

*Code:* `Asset`

A composite Pinky+OMX MobileManipulator is not an Asset yet (concept 09 / concept 13 Phase 5).

### Task
An atomic REST action the robot will run (`TaskKind`: move, navigate, follow, dock, and the like).

*Code:* `TaskKind`

*Avoid:* workflow or mission — those belong to Fleet (D-12).

The current `/api/fleet/tasks/*` uses `task` for its durable navigation request. State which API or layer is meant; future cross-device work uses Fleet Mission / Mission Step / Device Action (D-298).

## Swarm formation

### Reference stream
The stream of a leader robot's own pose that followers consume to hold their place in a formation.

The follower does not ask where the stream came from — a Fleet relay, a direct link from the leader, or a future peer source all deliver the same frames — and it holds position on its own when the stream stops for longer than its timeout. Nothing in the path may invent a frame: a repeated or synthesized pose makes a dead leader look alive, and so does a health figure that does not decay when frames stop.

### Formation hold
The formation-wide stop taken when any one robot reports it cannot continue, made by withholding the reference stream so that every follower's own stream-loss behavior fires.

*Avoid:* group stop, all-stop (those name an e-stop, which is a different, faster path)

A hold leaves each follower's following session alive, so resuming is a matter of letting the stream flow again; it never resumes on its own, and resuming first re-verifies that every robot is still following and none has a newer reason to stop. A refusal that touched no robot — a bad formation shape, robots on different maps, a leader in e-stop — never causes or lifts a hold; it leaves the formation exactly as it was.

### Slot offset
A follower's place in a formation, expressed as a distance behind the leader and a lateral offset to the leader's left, in the leader's own heading frame.

Every formation shape reduces to one slot offset per follower, so changing shape is re-issuing offsets rather than a new kind of command. Offsets have a floor below which two robots' footprints, with their obstacle inflation, would overlap.

## Docking

### Dock
The charging station a robot drives into, which measures the charge it delivers rather than leaving the robot to infer it.

It carries a controller for a safety reason rather than a reporting one: its contacts sit on the floor at pet and toddler height, so it detects a load before it energises anything and de-energises the moment the load leaves. Measurement is the second benefit of a controller that had to exist anyway, and it matters because the robot has no current sensor of its own. The dock never opens a connection to a robot — the robot asks, because the robot knows which dock it is going to and an inbound path into the robot would be an unauthenticated surface for no gain. It reports load and current as separate facts, because contacts can be engaged while nothing flows, and those two situations need different recoveries.

### Docking
The staged approach that takes a robot from somewhere in the map to engaged contacts.

Map coordinates get it near; every stage after that closes the loop on the observed dock, because localisation error is two orders of magnitude larger than the contact tolerance. The whole approach holds one mode from start to finish, which both stops a fleet command from pushing a half-engaged robot out and avoids widening the mode transition table. Stages exist so that a failure's location is known: not arriving and arriving without conduction need different recoveries, and the second re-seats rather than starting over. A funnel absorbs the last centimetre or two of lateral error, so a controller that must be millimetre-accurate on its own is a controller that fails on a dusty floor.

### Charging confirmation
The judgement that a robot is actually charging, requiring two independent sources rather than the dock's word.

*Avoid:* charge detection

The dock's reported current is one source; the robot's own filtered pack voltage not falling is the other. Two are required because this judgement suppresses the deep-discharge shutdown, so anything on the network able to assert charging would otherwise be able to switch off a safety path. The asymmetry is deliberate: confirming requires the whole window, and losing it is immediate.

### Dock detector
The sensing boundary that reports where the dock is, relative to the robot, and nothing else about how it knows.

Which physical signal it uses is deliberately not decided by the boundary, so the approach logic could be built and verified before the sensing was chosen; the product has since chosen a camera tag, and a run missing any piece of that stack falls back to a detector that sees nothing. A detector also has a usable distance band whose near edge is not zero — features leave the sensor's view close in — and that near edge must be measured on the chosen sensor before it is trusted, because it sets how early the dock type hands off to the funnel and the contact judgement; for the camera tag it has not been measured yet. A detector that reports nothing ends the run in a plain failure, never an automatic retry; a detector that confidently reports the wrong pose drives the robot into something that is not the dock, which is why refusing is preferred to guessing.

## Line following

### Lane lost
The line-follow state a robot enters after going without fresh lane evidence for longer than its loss window; it stops the robot and stays set until a line-follow mode is selected again.

Stale evidence on its own only holds the robot while the evidence stays stale; lost is latched, so a robot that regains its view of the lane still does not move. Freshness is judged on the clock the evidence arrives on — in simulation that is simulated time, because a slow simulator would otherwise age every frame past the window by wall time and latch a robot that sees the lane perfectly well.

## Flagged ambiguities

- "Robot id" had been used for both the Robot number and the namespace derived from it — these are distinct, and only the number is supplied by a person.
- "Hold" in swarm material means the formation-wide stop made by withholding the stream; "e-stop" is the robot's own emergency path and is faster. The two are not interchangeable even though both leave robots stationary.
- "Profile" still means Compose service grouping or hardware YAML; Runtime mode is the staged install preset (core, then motor, then hardware). D-62 slices are the install units. None of these is a Capability, and they are not interchangeable even where they share names.
- "Node" in this glossary is the computer running CORE (`RuntimeNode`), not an rclpy node.
- "Task" here is an atomic REST action; Fleet missions and concept 08 workflows are a different object (D-12).
