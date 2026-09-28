## D-319 SETUP 뒤 현장 입회 하에 모터 구동 준비를 자동화한다

**Status:** Proposed (2026-09-28). The PC helper has been exercised on one
Pinky Pro; automatic image boot, full G4 acceptance, and field operation remain
separate gates.

## Context

First boot deliberately writes `ROSY_RUNTIME_MODE=core` without
`ROSY_IO_DRIVE_ENABLED`. D-192 keeps torque off because starting the motor node
enables torque and subscribes to `cmd_vel`; a successful identity and Wi-Fi setup
does not establish a clear floor, reachable power cut, or correct wheel direction.
After a moved-card rebind, the device also has a new UID and no G4 approval.
The setup helper previously ended at SD writing, leaving the operator to edit
`runtime.env` and restart services by hand.

## Decision

The Windows setup flow offers one follow-up command,
`enable-motor-commissioning.ps1`, after verified first boot. The command
automates the technical transition **during an attended session**. It requires
the operator to assert that someone is beside the robot and can cut power at
once. It reads the live device UID, number, namespace, provisioned state, CORE
identity, and the root runtime file before changing anything.

The helper latches CORE E-Stop, stops I/O, probes motor IDs 1 and 2 with torque
disabled, saves the old runtime file under `X:\DevTemp`, atomically selects
`motor` and `drive=true`, restarts CORE, relatches E-Stop, and starts I/O. It
requires fresh stationary odometry, `drive=ready`, and one final `cmd_vel`
publisher with one subscriber. Failure after a configuration change stops I/O,
restores the old runtime file, restarts CORE, relatches E-Stop, and restarts
no-drive I/O where possible. `-CheckOnly` verifies identity without actuation.

SETUP completion alone does not enable torque. No software signal currently
proves that an operator is present or that the independent power cut is
reachable. Enabling torque at unattended first boot would remove D-192's
actuator boundary. The helper does not release E-Stop, send velocity, create
G4 approval files, or promote navigation. G4 still needs measured directional
and stop trials on the current device and release, with a separate physical
review under D-312 and the mapping recovery procedure.

## Verification and limits

- The read-only identity check on one device returned `PROVISIONED`; the
  attended helper observed torque-free motor IDs 1 and 2, activated `motor`,
  and read back `drive=ready`, E-Stop, fresh odometry, and one final publisher.
  The private operator record under `X:\DevTemp` contains the device-specific
  readback. This is a commissioning-mode check, not G4 acceptance.
- The first bounded forward command had no confirmed physical movement. The
  second had operator-confirmed forward movement and a normal stop, but its
  peak reported speed exceeded the requested 0.03 m/s limit. Neither sequence
  is a passing G4 trial; detailed measurements remain in the private record.
- After the trials, the device was restored to `core` with E-Stop latched, and
  both motor torque registers read as disabled. No G4 approval was made.
- The PC helper requires the existing strict SSH alias and the matching DPAPI
  CORE credential. It is not a signed image update and cannot make an old
  installed image acquire a new first-boot feature.

## Alternatives and recovery

Unattended torque-on at `PROVISIONED` was considered and rejected because
provisioning proves identity and network state only. A permanent no-drive
state would require manual SSH edits on every supervised test, so the attended
helper provides a repeatable transition while retaining D-192's boot default.
If a trial is uncertain or abnormal, stop I/O, restore the saved `runtime.env`,
restart CORE, latch E-Stop, start no-drive I/O, and read both torque registers
before attempting another trial. Do not manufacture G4 evidence or approval
markers from API command acceptance alone.
