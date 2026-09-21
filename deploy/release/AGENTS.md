<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-14 -->

# release

## Purpose

Release packaging and the privileged Host Agent. Modules are scripts (not an installed package). `HostAgent` is pure decision/dispatch; `host_agent_server` is POSIX transport + injected `HostCommands`. CORE talks to it over `/run/rosy/host-agent.sock`.

## Key Files

| File | Description |
|------|-------------|
| `host_agent.py` | Decision layer: roles, confirmations, refusals, audit; no socket, no root |
| `host_agent_server.py` | Unix-socket server, peer credential check, privileged actions |
| `manifest.py` | Release manifest read/write |
| `manifest.schema.json` | Manifest JSON schema |
| `signing.py` | OpenSSL 3 raw Ed25519 sign/verify |
| `sign_image_release.py` | Offline image checksum verification and fail-closed Ed25519 signing CLI |
| `storage.py` | On-disk release store |
| `updater.py` | Activate / rollback a signed release |
| `layout.py` | Directory layout for releases |
| `network.py` | Network profile provisioning helpers |
| `image_checks.py` | Image content checks used by the pipeline |
| `secret_scan.py` | Secret scanning before ship |
| `arm64_release_builder.py` | Native ARM64 `core`/`io` build and unsigned release-payload assembler; private keys are forbidden here |
| `import_unsigned_payload.py` | Fail-closed checksum, archive, identity, payload, and nested ARM64 image verifier before offline signing; never accepts a private key |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `public-keys/` | Committed Ed25519 **public** trust anchors only (see `public-keys/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Never give Host Agent an arbitrary shell. Commands are an allow-list.
- Inject `HostCommands` in tests; do not run `nmcli`/`systemctl`/`reboot` in pytest.
- CORE client must treat `HOST_AGENT_UNAVAILABLE` / `HOST_AGENT_TIMEOUT` / `HOST_AGENT_UNREADABLE_RESPONSE` as three distinct outcomes (`host_agent_client.py`).
- Activation `runtime_mode` is always `"core"` (`layout.py:ACTIVATION_RUNTIME_MODE`). Motor/hardware is a separate field approval — updater must not activate those modes.
- Keep this directory importable via `test/conftest.py` (no `setup.py`).

### Testing Requirements

```bash
python3 -m pytest test/test_host_agent.py test/test_release_manifest.py \
  test/test_release_signing.py test/test_release_storage.py \
  test/test_release_updater.py test/test_release_layout.py \
  test/test_release_boundary_guards.py -v
```

### Common Patterns

JSON request/response lines, schema version 1, bounded request size.

## Dependencies

### Internal

- Contract: `docs/reference/rosy-host-agent-contract.md`
- Client: `src/core/core_api_web/core_api_web/api/host_agent_client.py`

### External

- OpenSSL 3, POSIX unix sockets (server path)

<!-- MANUAL: -->
