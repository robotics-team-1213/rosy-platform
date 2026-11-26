<!-- Parent: ../AGENTS.md -->

# release

**Parent context:** `../AGENTS.md`

## Purpose

Release packaging and the privileged Host Agent. Modules are scripts (not an installed package). `HostAgent` is pure decision/dispatch; `host_agent_server` is POSIX transport + injected `HostCommands`. CORE talks to it over `/run/rosy/host-agent.sock`. Contract: `docs/reference/rosy-host-agent-contract.md`; client `middleware/core/api/core_api_web/api/host_agent_client.py`. Files: `ls`; `public-keys/` holds committed Ed25519 **public** anchors only.

## For AI Agents

### Working In This Directory

- Never give Host Agent an arbitrary shell. Commands are an allow-list.
- Inject `HostCommands` in tests; do not run `nmcli`/`systemctl`/`reboot` in pytest.
- CORE client treats `HOST_AGENT_UNAVAILABLE` / `HOST_AGENT_TIMEOUT` / `HOST_AGENT_UNREADABLE_RESPONSE` as three distinct outcomes.
- Activation `runtime_mode` is always `"core"` (`layout.py:ACTIVATION_RUNTIME_MODE`). Motor/hardware is a separate field approval; the updater must not activate those modes.
- Keep this directory importable via `test/conftest.py` (no `setup.py`). `signing.py` aliases `deploy/hosts/common/release/signing.py`; native installers copy that implementation.
- Signing tools (`sign_image_release.py`, `arm64_release_builder.py`, `import_unsigned_payload.py`, `build_payload_release.py`) other than `sign_image_release.py` (offline) never read or accept a private key; import verifies checksum, archive, identity and nested image before signing.
- `publish_secret_baseline.json` (D-889): one row per exact (commit, path, rule) of reviewed secret-scan hits, never a value or excerpt. A new commit or other rule still stops the publish. The 2026-10-26 rows were an agent review, not human sign-off.
- Payload-only update (D-225 2.1, operator; no card re-flash; DEVICE evidence only when `UPDATE_GO` is not HOLD):
- Payload steps: CI "Build Pinky Pro native payload" artifact, offline `sign_image_release.py`, `build_payload_release.py pack --modes-from <unsigned tar.gz>` (restores exec bits the zip lost), then `../rosy-release-push.ps1 -Tarball`. Use each script's `--help`.
- Payload builds against the ROS debs installed on the CI runner. Before pushing, diff payload `ros-packages.txt` (`name=version`) with the image release's `deb-packages.txt` (`ros-jazzy-*` only). If versions differ, consider an image rebuild; no gate enforces this.
- Artifact selection (D-325): `artifact_impact.py --base <installed image source_revision> --head <candidate> --json`; never substitute the payload revision. `none` skips; `native-payload`, `flashable-image` pick the workflow; `review` blocks. It is advisory and waives no signing, readback or field gate.

### Testing Requirements

```bash
python3 -m pytest test/test_host_agent.py test/test_release_manifest.py test/test_release_signing.py test/test_release_storage.py test/test_release_updater.py test/test_release_layout.py test/test_release_boundary_guards.py test/test_payload_release_build.py test/test_native_payload_workflow.py -q
```

JSON request/response lines, schema version 1, bounded request size.

<!-- MANUAL: -->
