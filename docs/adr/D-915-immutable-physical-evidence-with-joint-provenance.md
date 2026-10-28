## D-915 Immutable physical evidence with measured joint provenance

**Status:** Accepted for software implementation (2026-10-29, user-approved pipeline design and immediate execution). Independent contract/Safety review and source verification are required before the implementation commit. This decision grants no device activation, deployment, landing or publication.

### Problem and scope

D-856 physical receipts bind a successful transfer and released original claims to a canonical two-sample proof. They do not contain the measured joint values, capture times and source revision required by a business application's independent retreat evidence. Combining a historical receipt with a new pose GET would attest facts that the receipt never validated.

### Decision

1. The independent observer may submit an optional immutable joint measurement per owner: `sample_id`, `sequence`, source UTC `observed_at_ns`, ordered unique `joint_names` and equally sized finite `positions_rad` (1..32 joints). It is a fact, not a command or a new source of clearance authority. Omission preserves the existing observation/receipt path.
2. World owns the measurement shape. Fleet includes submitted joint timestamps in the existing freshness and two-sample ordering checks; paired joint measurements must have the same joint order, distinct source IDs and increasing sequence. Missing joint facts remain missing. Legacy canonical evidence omits the optional field when absent so stored/retransmitted proof bytes do not change.
3. New API v1.330 `GET /api/fleet/arm-transfers/jobs/{mission_id}/physical-evidence` uses the existing viewer and job-creator scope. It reads the confirmed job and its original stored POST_ACTION proof in one SQLite read snapshot, verifies the stored SHA-256 and current installed policy identity, and exports the unchanged receipt, exact canonical `evidence_document` and original released zone IDs. Complete joint measurements in both samples are required; legacy receipts without them are unavailable through this new route, not upgraded or backfilled.
4. The response proves historical closure of the original attempt and claims, not current zone availability. It contains no observer credential or private device address. It does not refresh capture times, issue a new event, change claims, send an Action, authorize admission, or complete a business task.
5. Harbor consumes the public response with its own service identity, verifies the proof/receipt binding and explicit installed object/location/arm/zone/joint correspondence, and constructs its existing independent placement/retreat evidence. Harbor retains business completion and original evidence freshness. It receives no observer write token, ROS access or automatic admit/rearm permission.
6. Source times are UTC capture times as in the existing physical observation contract. Simulation/ROS source ticks must retain their clock identity and require a verified mapping before becoming UTC input. An observer callback's receipt time or a newly generated read ID does not create a new source measurement.

### Compatibility and failure behavior

Existing physical receipt routes, old observation payloads, writer boundaries and two-person admission remain unchanged. The new read route returns pending/unavailable for absent or incomplete proof; cross-job service reads remain forbidden. Tampered proof, changed identity, stale joint measurements, conflicting replay and partial joint coverage never gain a fabricated measurement or additional execution/release. Identical canonical observation retransmission retains the existing idempotent result.

### Ownership and verification

| Existing decision | Relationship |
|---|---|
| D-427 / D-429 | Reuse foundation contracts, World facts and Fleet's existing transaction and deployment; no new top-level holder or execution database. |
| D-430 | Independent Safety review and the required commit trailer apply to classified paths; source tests do not attest physical stop. |
| D-856 | Public read projection of the same neutral transfer proof; business completion stays with the application. |
| D-858 / D-793 | Hardware owner and learned-policy execution gates remain closed until their own acceptance. |

Verify exact stored-proof export, original times/IDs, old canonical bytes, optional measurement validation, stale/future/sequence refusals, pending legacy proof, creator scope, tamper detection and zero write/dispatch effects. Then verify Harbor's single-move confirmation over a real isolated HTTP server with explicitly injected observations. Independent Gazebo measurement, actual source-clock mapping, real hardware and FIELD remain separate gates.

Rollback disables the new consumer/provider and read route while preserving journals, proof bytes and original claims. Do not erase evidence, change request keys or auto-replay an uncertain submission.
