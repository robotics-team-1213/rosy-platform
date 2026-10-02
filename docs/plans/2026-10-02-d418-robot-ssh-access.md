# D-418 robot SSH access: implementation plan and shared contract

ADR: `docs/adr/D-418-robot-ssh-access-code-enrollment-temporary-password-team-key.md`. Integration branch: `feat/d418-ssh-access`. Two tasks, R (robot and CORE) and P (operator PC), run in parallel worktrees and merge back into it. **The contract below binds both tasks.** Change it only in this file.

## Shared contract

All API routes are under `/api/v1/host/ssh` and require the **administrator** role (D-193 tokens). Errors use the existing CORE error envelope.

| Method + path | Request | Response |
|---|---|---|
| `GET /host-keys` | — | `{"hostname": "rosy-pinky-xxxx", "host_keys": ["ssh-ed25519 AAAA…", …]}` (public host keys from `/etc/ssh/ssh_host_*_key.pub`) |
| `GET /keys` | — | `{"keys": [{"label", "type", "fingerprint" (SHA256:…), "added_at", "expires_at", "added_by"}]}` |
| `POST /keys` | `{"public_key": "<type> <base64> [comment]", "label": "<label>", "expires_days": 1..365}` | `201 {"label", "fingerprint", "expires_at"}`; `409` label exists; `422` invalid key, label or days; `409` when 32 managed keys exist |
| `DELETE /keys/{label}` | — | `204`; `404` unknown label |
| `POST /password` | `{"minutes": 1..60}` | `200 {"user": "rosy", "password": "rosy-xxxx-xxxx-xxxx", "expires_at"}` |
| `GET /password` | — | `{"enabled": bool, "expires_at": "<Z>" or null}` |
| `DELETE /password` | — | `204` (turns it off now) |

- **Labels:** `^[a-z0-9][a-z0-9._:-]{0,47}$`. Team keys use `team:<name>`, enrolled devices `dev:<name>`.
- **Allowed key types:** `ssh-ed25519`, `sk-ssh-ed25519@openssh.com`, `ecdsa-sha2-nistp256|384|521`.
- **Times:** UTC, `YYYY-MM-DDTHH:MM:SSZ`.
- **`added_by`:** the label of the administrator token that made the request.
- **Managed keys file:** `/var/lib/rosy/ssh/authorized_keys`. Line format: `expiry-time="YYYYMMDDHHMMZ" <type> <base64> rosy-managed:<label>`. sshd reads it through `AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys`, set in an sshd_config.d drop-in.
- **Metadata and audit:** metadata goes in `/var/lib/rosy/ssh/keys.json`, and an audit trail goes in `/var/lib/rosy/ssh/history.jsonl` (add, revoke, password on, password off, expire).
- **Temporary password:**
  - The drop-in `/etc/ssh/sshd_config.d/60-rosy-temp-password.conf` contains `Match User rosy Address 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`, then `PasswordAuthentication yes` and `MaxAuthTries 3`.
  - When it is off, the drop-in is removed and the `rosy` shadow password field is `*`.
  - It is also off after every boot.
  - The password is never written to any log, history or file other than shadow.
- **Privilege boundary:** CORE stays unprivileged. It hands requests to a root helper `rosy-ssh-access.py` through a request/response file pair in a CORE-writable directory. A root `.path` unit wakes the helper, in the same pattern as `rosy-hw-test.path`. CORE waits for the response for at most 10 s. The helper re-validates everything.

## Tasks

- **R, robot and CORE (`feat/d418-robot`).**
  - The root helper, the path, service and expire timer units, a boot cleanup step, and the sshd drop-in for `AuthorizedKeysFile`.
  - The D-388 sync lists and the image build lists.
  - The CORE administrator routes and schemas. Update the API reference version together with `schemas.py` (D-18; see `docs/solutions/workflow-issues/a-contract-version-bump-is-three-pins-not-one.md`).
  - Tests.
  - A device-twin scenario that adds sshd to the twin and checks enroll, login, revoke, expiry, and password on and then off.
- **P, operator PC (`feat/d418-pc`).**
  - `tools/ssh/rosy_ssh_enroll.py <robot>`: makes a device key, pairs with a login code typed by the operator, posts the key, writes `known_hosts` from `/host-keys` and a `Host` alias, and logs the token out.
  - `tools/ssh/rosy_ssh_share.py create|revoke|list --name <team>`:
    - It makes a passphrase-locked ed25519 key and a zip bundle with the locked private key, `config`, `known_hosts` and a Korean `README.md`.
    - It registers the public key as `team:<name>` on each robot given with `--robot` (through the API with a login code, or through the operator key over ssh as a fallback).
    - The passphrase is shown once and never written to the bundle.
  - `docs/deployment/robot-ssh-access.md`: a Korean guide covering all three ways, for the operator and for the people receiving access.
  - Tests with a fake CORE and a fake ssh.
