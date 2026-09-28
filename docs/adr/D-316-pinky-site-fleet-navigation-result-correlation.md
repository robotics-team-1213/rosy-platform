## D-316 Pinky Site Fleet navigation result correlation

**Status:** Accepted (2026-09-28; SOURCE/LOCAL implementation boundary only).
This decision does not claim ROS-SIM, image, device, field, or physical-stop
acceptance.

**Context:** Site Fleet persists `task_id` and a per-dispatch `attempt_id`, but
the Pinky CORE navigation REST request and its navigation events previously had
no shared identifier. Fleet could record a positive receipt as `ACCEPTED`, but
could not safely advance that exact task to `RUNNING` or a final result. Matching
by goal coordinates, event order, or a robot's most recent task would confuse
concurrent or late evidence. D-293 keeps the server as task authority; D-298
separates task outcome from stop evidence; D-297's PRT-004 ACK protocol remains
Proposed for the central Fleet activation path.

**Decision:**

1. **Keep identities distinct.** Fleet `task_id` identifies the durable site
   task. Fleet's existing `attempt_id` identifies one dispatch attempt and is
   sent as the optional CORE REST `correlation_id`. CORE echoes it only in the
   events produced by that correlated navigation goal. Fleet does not expose
   its task ID as a robot command ID and does not infer identity from coordinates.
2. **Project only exact Pinky navigation evidence.** The paired CORE Agent event
   path may update a Fleet task only when robot ID, current `attempt_id`, event
   type, event ID, and event sequence identify that attempt. `nav.started`
   projects `RUNNING`; `nav.completed` projects `COMPLETED`; `nav.failed`
   projects `FAILED`. A matching `nav.canceled` event means the local cancel
   request was issued, so the task remains `UNKNOWN` with final action result
   pending. Duplicate event IDs and older correlated sequence numbers never
   regress the task. A later final result may resolve `UNKNOWN`.
3. **Preserve ambiguity.** A timeout or unclassified error after dispatch stays
   `UNKNOWN`; Fleet never replays that attempt automatically. A result event may
   reconcile that exact attempt. A late HTTP receipt or timeout cannot downgrade
   a correlated `RUNNING` or final task status.
4. **Keep proof layers separate.** CORE navigation result events establish the
   software action result only. A task status, cancel request, HTTP response, or
   zero command is not physical standstill proof. Stop request, driver/actuator
   readback, and physical stop evidence remain separate gates under D-298.
5. **Keep protocol scope narrow.** The new identifier is an additive field in
   the existing `/api/v1/navigation/goal` request and optional navigation event
   `data`. This does not set top-level `Envelope.correlation_id`, add
   `AckPayload` messages, activate D-297/PRT-004 for central Fleet, generalize
   the API to OMX or drones, or change the PRT protocol version.

**Alternatives considered:**

- Join by robot ID, event sequence, or coordinates: rejected because none proves
  which dispatch attempt produced the event.
- Put `task_id` in CORE or the PRT envelope: rejected because Fleet owns the
  task ledger and the device protocol should carry only command-attempt identity.
- Treat `nav.canceled` as a final failure or stop: rejected because it is emitted
  after issuing a cancel request, before action result or physical readback.
- Generalize a shared device Action schema: deferred until a second device
  implementation provides evidence for the same wire and result semantics.

**Validation:** Host tests cover request propagation, CORE event echo, exact
robot/attempt matching, duplicate and stale events, cancellation ambiguity,
late receipt ordering, and durable Fleet event projection. These are
SOURCE/LOCAL checks. ROS-SIM must verify the running CORE bridge emits the same
correlation through the real Nav2 result callback. ARTIFACT and DEVICE/FIELD
must separately verify the installed image, event delivery, final action
readback, and physical stop evidence. These gates remain open.

**Consequences:** `GET /api/fleet/tasks/{task_id}` can expose correlated
navigation progress and outcome while preserving Fleet's durable status
history. This decision supersedes the earlier statements in D-269, D-293, and
D-297's context that this specific Site Fleet Pinky navigation path has no
active result correlation. It does not supersede their transport ownership or
authorization boundaries, and D-297's central Fleet PRT-004 design remains
Proposed.
The attempt correlation is not a generic action contract, a stop interlock, a
hardware sample freshness guarantee, or central Fleet PRT ACK.

**References:** D-18, D-55, D-59, D-293, D-297, D-298, D-315; API Reference
§§5.3, 8, 10.8, 10.10.
