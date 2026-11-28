
# omx

**Parent context:** `../AGENTS.md`

## Purpose

Workstation development and simulation preparation for the OMX-AI workcell: a ROS 2 Jazzy OCI image built from an immutable ROBOTIS source lock, host-inventory placement preflight, Gazebo/pilot probes, and the real-arm cell tools (`cell_*.py`, `chunk_runner.py`, `record_session.py`). Not part of the Pinky Pi image and not an accepted field actuator runtime; the runtime profile stays disabled (no joint map, hardware plugin, serial or camera identity). Field control is one native systemd instance per workcell (D-246). Usage, inventory and carry order: `README.md`.

## For AI Agents

### Working In This Directory

- Keep OMX inputs here; do not move them under `pinky_pro/` or add ARM64 product-image content.
- Change `stack.lock.yaml` only to another immutable revision, never a branch name.
- Do not enable a runtime profile or invent joint, serial, or camera identities; those need device acceptance first.
- Example/template files stay free of real hosts, addresses, and credentials (public repo).
- Every real-arm command goes `checked` through `cell_transfer.Gate` (D-911); each re-plan is assessed. Moving steps need `--commissioning --person-at-switch`; without them use `--dry-run` or `--plan-only`, which move nothing. Never bypass the Gate.
- A designated slot (cell-site-map name) opens for motion only after `cell_site_register` promotes it to measured (Z then XY evidence; layers 1/2 also tier step); until then every motion path refuses `SITE_NOT_MEASURED`. Order and config locking: `cell_site_register.py`.
- Supervised tools (`cell_step`, `cell_push --friction`, `cell_two_arm --carry`, `cell_pipeline --stage recover --person-at-switch`) are D-911: `--commissioning --person-at-switch`, else `--dry-run`/`--plan-only`.
- Automatic roles stay held by D-911 until reviewed; `cell_role` is rescue only (load is a Fleet ARM_TRANSFER job, D-996 5).
- Sessions end torque OFF with caps restored, except a runner HOLD: the arm folds home and is read back before torque OFF, else a human hold keeps torque ON until a person sends SIGUSR2. Never cut torque on an extended arm.
- Claim the per-arm lease first (`cell_arm_lease`, D-1035); a held lease refuses every claim until `release-hold`. `observer_handoff.py` and the runner never SIGKILL a session.
- Guard stops (following error, contact, 55 C, joint at 80 % of its session cap) park or hold; never raise a cap to pass a stop. Fleet, not the cell, clears an incident (D-971).
- `cell_params_web.py` keeps guards and motion values locked; saves are refused while `session.lock` is held. `cell_collect_plan` writes drafts only: proposer != approver, never sets `policy_real_approved`; live runs need `--person-at-switch`, `--commissioning` and D-1024 approval.
- A new real-arm plan (pose set, path, recovery) runs only after four checks and one "agree" from a session that did not write it:
  1. collision along the whole path in sim at the measured cell;
  2. load as tool output: per-joint torque against the session's per-ID caps file (not the datasheet); `load_predict`; flag at 50 % of a cap;
  3. what happens if it stops midway, and the recovery;
  4. first real run with the runner's strain watch live; a script reads `state.fault` before each jog and never jogs past a hold.
- An unchanged rerun of a checked plan needs no new check. Why: 2026-11-09 a hand-eye pose checked only for collision overloaded arm_a's XL330 wrist; the guard cut torque and the extended arm dropped onto its plate.
- Device-trial units (`rosy-omx-arm-session@`, `rosy-omx-attested-producer@`) run off; a person starts them. The session is the only bus writer; the producer posts PRE_DISPATCH only behind a SOURCE_CLEAR.
- Driving the Leader as a reference arm needs an explicit hands-off attestation (D-846). During a recovery park send `human-hold` to freeze the arm; `stop` is refused there.
- `omx_autoupdate.py` switches `current` only while idle (no session lock, devices free, follower torque OFF), with smoke check and rollback.

### Testing Requirements

```bash
python3 -m pytest test/test_omx_workstation.py test/test_omx_host_inventory.py test/test_omx_multi_preflight.py test/test_omx_vendor_stack_lock.py -q
```
