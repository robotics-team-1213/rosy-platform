# D-406 robot auto-update — implementation plan and shared contract

ADR: `docs/adr/D-406-robots-self-update-from-signed-github-releases-when-idle.md`. Branch: `feat/d406-robot-auto-update`.

Three tasks run in parallel worktrees branched from `feat/d406-robot-auto-update` and merge back into it. **The contract below is binding for all three.** Change it only in this file, in a separate commit that every task rebases onto.

## Shared contract

### GitHub Release (written by T3, read by T2)
- **Release.**
  - Tag and name: `payload-<release-id>`. The tag targets the release's `source_revision` commit.
  - Not a draft, not a prerelease.
  - Repository: `livsbittt/rosy-os`.
- **Assets.**
  - `<release-id>.tar.gz`: the signed payload tarball, the same file `rosy-release-push.ps1 -Tarball` takes.
  - `rollout.json`: UTF-8, LF line endings, keys sorted, no BOM.
  - `rollout.json.sig`: ASCII base64 of the raw 64-byte Ed25519 signature over the exact bytes of `rollout.json`. It is made with `signing.sign_checksums(bytes, private_key)` and checked with `signing.verify_signature(bytes, sig, public_key)`.
- **`rollout.json` (schema 1).**
  ```json
  {"schema": 1, "release_id": "2026.10.01-022", "tarball": "2026.10.01-022.tar.gz",
   "tarball_sha256": "<64 hex>", "source_revision": "<40 hex>",
   "published_at": "2026-10-01T15:00:00Z", "canary": ["rosy-pinky-8kcn"],
   "canary_ok": false, "wave_delay_s": 600, "withdrawn": false, "reason": ""}
  ```
- **Updating a rollout.** T3 rewrites and re-signs `rollout.json`, then uploads both files again (`gh release upload --clobber`). It changes only `canary_ok`, `withdrawn` and `reason`; `published_at` never changes.

### Device files (owned by T2; T3 reads them over ssh)
All files live under `/var/lib/rosy/updates/` (root 0755; files 0644 except where noted).

| File | Contents |
|---|---|
| `config.json` | `{"enabled": true, "repo": "livsbittt/rosy-os"}`. Missing file = those defaults. |
| `hold.json` | `{"holder": "...", "reason": "...", "created_at": "<Z>", "expires_at": "<Z>"}`. `expires_at` is required and at most 7 days after `created_at`. An expired hold is ignored and moved to history. |
| `state.json` | Private to T2 (ETag, staged id, failed ids). |
| `status.json` | Format below. |
| `history.jsonl` | Append-only lines `{"at", "event", "release_id", "detail", "boot_id"}`. |

`status.json`:
```json
{"schema": 1, "updated_at": "<Z>", "hostname": "rosy-pinky-8kcn", "current_release": "2026.10.01-021",
 "candidate": "2026.10.01-022", "phase": "idle|staged|waiting|held|ineligible|applying|committed|rolled_back|failed|disabled|error",
 "reason": "human-readable why",
 "last_result": {"release_id": "...", "outcome": "committed|rolled_back|refused", "at": "<Z>", "detail": "..."}}
```

- **Device CLI** (root, at `/opt/rosy/native-runtime/rosy_auto_update.py`):
  - `run`: the timer entry.
  - `status [--json]`
  - `hold --holder H --reason R --hours N` (N in (0, 168])
  - `release-hold`
  - `eligibility [--json]`: read-only.
- **T3 calls these over ssh** as `sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py ...`.
- **Claim** (D-387 decision 4, interim):
  - `mkdir /run/rosy-claim` is atomic. Whoever succeeds writes `/run/rosy-claim/claim.json` = `{"holder", "purpose", "acquired_at", "expires_at", "boot_id"}`.
  - If the claim is expired, or its `boot_id` differs from the current boot, it may be cleared by exactly one party: `mv /run/rosy-claim /run/rosy-claim.stale.<rand>`.
  - Both push (T3) and the updater (T2) take the claim for their whole sequence.

### CORE status file (T1 writes, T2 reads)
`/run/rosy/status-inputs.json` moves to **`schema` 2**.
- **Kept:** every schema-1 key, unchanged.
- **Added keys:**
  - `velocity_linear` (float m/s), `velocity_angular` (float rad/s)
  - `battery_percent` (float or null), `battery_charging` (bool or null)
  - `docking_state` (string or null), `line_follow_mode`, `line_follow_state` (strings)
  - `swarm_active` (bool), `estop` (bool), `activity_kind` (null or string, e.g. `"CALIBRATING"`)
- **Values** come from the same snapshot that `GET /api/v1/robot/state` returns.
- **Readers:**
  - `rosy-boot-status.py` must accept schema 1 and 2.
  - T2 requires schema >= 2 and treats the file as stale after 60 s.

## Tasks

- **T1 — CORE status inputs schema 2.** Writer in `src/runtime/api_web/core_api_web/api/v1/host.py` (with node wiring if needed); the reader change in `deploy/robot/pinky_pro/native/rosy-boot-status.py`; tests.
- **T2 — Device updater.**
  - `deploy/robot/pinky_pro/native/rosy_auto_update.py`, `rosy-auto-update.service`, `rosy-auto-update.timer` (10 min, `RandomizedDelaySec`, `Persistent=true`).
  - Add the units to the D-388 lists (`UNITS`, `ENABLED_UNITS`), the `build-native-payload.sh` cp list and the `customize-rootfs.sh` enable list, plus the sandbox contract.
  - Move `rosy-release-unpack.sh` into `native/` and update the push path. The claim helper is shared code, so put it in `native/rosy_claim.py`.
  - Tests.
- **T3 — Operator PC.**
  - `tools/release/publish_payload_release.py`: create the release, sign the rollout, watch the canary, then set `canary_ok` or withdraw.
  - `deploy/robot/pinky_pro/rosy-update-hold.ps1`: hold, release and status over ssh.
  - The claim in `rosy-release-push.ps1`.
  - The skill doc `rosy-release-push`.
  - Tests.

Merge order: T1, then T2, then T3, each with an independent review before it merges. Device validation runs after all three, coordinated with the peers using the robots.
