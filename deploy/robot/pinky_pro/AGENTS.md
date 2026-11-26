<!-- Parent: ../AGENTS.md -->

# Pinky Pro deployment

**Parent context:** `../AGENTS.md`

## Purpose

Pinky Pro deployment inputs for Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy (D-161). Product services live under `native/`: CORE starts without device access; I/O and navigation are explicit hardware modes. Dockerfile/Compose are development/CI only and not installed in the product image. OMX inputs live at `../omx/`, outside this runtime. Files: `ls`; subfolders `config/`, `dev/` (D-179 bench overlay, not product install), `native/`, `verify/` have their own `AGENTS.md`.

## For AI Agents

### Working In This Directory

- `runtime-mode.sh` modes: `core` | `motor` | `hardware`; hardware selects `ROSY_NAVIGATION_BACKEND=localization|slam`. `slam` is valid only in `hardware` and makes the maps mount writable (D-144); localization keeps it read-only.
- `install-pi.sh`: `--preset` or `--slices` (must match a preset, include `core`) map to `ROSY_RUNTIME_MODE`; vision/omx/ai are not installable and have no compose service. Do not start them.
- D-161 product paths must not call Docker or Compose. Do not wire legacy `rosy-runtime.service` into a product image.
- `rosy-core` has **no** `/dev` devices and no Docker socket. Do not add them.
- Low-battery shutdown (D-27): CORE writes `battery-shutdown-request.json`; the host unit halts (sentinel age 900 s, grace cap 600 s). CORE must not call shutdown itself.
- `rosy-runtime.service` **Requires** `rosy-release-recover.service`; `Wants=` would make recovery advisory.
- `ROS_DOMAIN_ID` has **no default**: derived from `ROSY_ROBOT_NUMBER` (`40 + N`, namespace `rosy_%02d`) at install; `compose.yaml` uses `${VAR:?}` so unset identity stops the runtime (D-33). A default once shipped every unit as 42/`rosy_01`. CycloneDDS: `file:///etc/rosy/cyclonedds.xml`.
- `verify/verify-motors.sh` refuses to probe the UART when it cannot establish the motor runtime is down.
- `measure-dds-baseline.sh` (D-34) requires `hardware` mode and records pre-attach subscriber counts.
- `capture-vendor-baseline.sh`: passive, secret-redacted vendor-image capture; I2C probing is opt-in and raw output needs review before repository admission.
- `commission-pinky.py`: ordered G0-G5 evidence; operator procedure `docs/deployment/pinky-pro-first-device-runbook.md`.
- `collect-rosy-diagnostics.ps1` (D-175 L2): key-only BatchMode SSH with pinned `%LOCALAPPDATA%\Rosy\known_hosts`; never overwrites evidence. `-PrintPlan` runs nothing.
- `rosy-release-push.ps1` (D-225): verifies the signature locally, scp's a signed payload, runs `native/activate-release.sh` or rollback. `-PrintCommands` shows the sequence without network. `rosy-release-push-many.ps1` (D-553) runs it per robot in parallel; canary = sequential calls.
- `Dockerfile` `core` stage lacks `core_common`/`core_events`/`core_features`/`core_api_web`; it is not a working CORE build. Healthcheck: `GET http://127.0.0.1:8080/api/v1`.
- Do not commit secrets in `.env.example`. Build context `../..`; contract `docs/reference/rosy-host-agent-contract.md`.

### Testing Requirements

```bash
python3 -m pytest test/test_native_systemd_contract.py test/test_robot_runtime.py test/test_release_boundary_guards.py -v
```

<!-- MANUAL: -->
