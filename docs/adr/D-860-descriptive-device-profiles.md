# D-860 — Descriptive device profiles independent of enrollment and control

**Status:** Accepted (2026-10-24, user instruction)

## Context

An operator identified the connected robot as OMX S with one arm. Historical leader/follower configuration and a two-arm observation manifest did not identify it. A USB controller name or the number of connected USB ports cannot establish a robot's model, declared arm composition, calibration or permission to move. CORE enrollment and OMX workcell instances also have different operational identities.

## Decision

Fleet stores descriptive device information in `fleet_device_profiles` in its existing task SQLite database. This metadata is separate from operational membership. A stable `device_id` identifies the record; `display_name`, `manufacturer`, `model`, `device_kind`, optional `arm_count` and `hardware_ids` describe the operator-declared device. Model and name are free text, so OMX S, OMX AI and other robots do not require hardcoded product names.

`hardware_ids` contains up to sixteen unique opaque identifiers. They are metadata, never shell arguments, file paths to open or credentials. A record can describe a disconnected device. Saving cannot add a CORE endpoint, enroll a robot, create an OMX owner, alter measured joint limits, clear a fault, enable torque or admit a command. Existing stores and owners retain those responsibilities.

The installation screen calls this area **장치 정보**. Viewer can list and read. Only a named Operator can create or replace a record. Fleet persists its updater and server timestamp. The write validates the complete replacement before a transaction; invalid input leaves the previous record intact. No delete action or automatic reclassification is introduced.

Every read states `connection_status: "not_checked"` and `control_enabled: false`. This first version provides no live identity attestation. Future verification must compare the selected device's registered identifiers and measured hardware profile through its existing owner; USB count, user-supplied names and old model defaults are insufficient. A saved one-arm record does not silently replace a disconnected two-arm member.

## Alternatives and consequences

- Reusing CORE enrollment was rejected because it would imply a CORE client and operational membership for standalone OMX hardware.
- Extending the leader/follower host inventory was rejected because its enabled workcell contract requires both ports and is intended for that workflow.
- Descriptive metadata in the existing Fleet database supports all device kinds without changing admission or creating another operational roster. It intentionally reports verification as unperformed until a separate verified path exists.

## Verification

Store/API tests cover persistence, replacement validation, Unicode, bounds, unknown authority fields and role guards. Console tests cover explicit composition, drafts, Viewer access, duplicate saves and installation wiring. These software checks do not establish physical identity, calibration, stop behavior or field acceptance.
