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
| `build_payload_release.py` | D-225 2.1: `build` (payload tree → unsigned native release dir) and `pack` (deterministic tar.gz for `rosy-release-push.ps1 -Tarball`); never reads a private key |

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

### Payload-only update (D-225 2.1, operator)

기존 로봇의 payload 계층만 바꿀 때. 카드 재기록 없음. `UPDATE_GO`가 HOLD인 동안은 개발용이고 DEVICE 증거가 아니다.

```powershell
# 1. CI: Actions > "Build Pinky Pro native payload" (release_id) 실행 후 artifact 받기
gh run download <run-id> -n rosy-native-payload-unsigned-<id>-<sha> -D X:\payload
# 2. 오프라인 서명 (파일럿 키, 이미지 서명과 같은 도구)
python deploy\release\sign_image_release.py X:\payload\<id> `
  --private-key <offline key> --public-key deploy\release\public-keys\rosy-release-2026-01.pem
# 3. 재포장: --modes-from 이 artifact zip이 잃은 exec bit를 Linux 빌드 tarball에서 되살린다
python deploy\release\build_payload_release.py pack --release-dir X:\payload\<id> `
  --out X:\payload\<id>.tar.gz --modes-from X:\payload\<id>.unsigned.tar.gz `
  --public-key deploy\release\public-keys\rosy-release-2026-01.pem
# 4. 전송·전환
deploy\robot\rosy-release-push.ps1 -Robot <ip> -Tarball X:\payload\<id>.tar.gz
```

Tests: `python -m pytest test/test_payload_release_build.py test/test_native_payload_workflow.py -q`.

### Common Patterns

JSON request/response lines, schema version 1, bounded request size.

## Dependencies

### Internal

- Contract: `docs/reference/rosy-host-agent-contract.md`
- Client: `src/core/core_api_web/core_api_web/api/host_agent_client.py`

### External

- OpenSSL 3, POSIX unix sockets (server path)

<!-- MANUAL: -->
