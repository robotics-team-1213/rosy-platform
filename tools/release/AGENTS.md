
# release

**Parent context:** `../AGENTS.md`

Developer-side steps between "the GitHub runner built a payload" and "push a signed release to a robot", on the release operator's PC. Robot-side install, signing code and the push script live in `deploy/robot/pinky_pro/` (`release/`, `rosy-release-push.ps1`). Multi-device flow: `docs/deployment/deployment-tools.md`.

## For AI Agents

### Working In This Directory

- Never push or activate from these scripts; printing the push command is the boundary. Pushing is a separate, operator-approved step (skill `rosy-release-push`). `make_delta_release.py` and `prepare_payload_release.py` never push or publish.
- `ship.py --dry-run` builds only (D-553 addendum 4). `make_delta_release.py` refuses build inputs, added, deleted or unmapped shipped files.
- The signing private key is read from the operator's local application-data folder; it is never copied into the repo or printed. Only the public key (`deploy/robot/pinky_pro/release/public-keys/`) is tracked.
- Never print the GitHub token or a signed download URL, in logs or errors.
- The ABI check is read-only (`dpkg-query`); add no command that changes a robot.
- Robot addresses are arguments, not constants. A robot id resolves through gitignored `private/lab-hosts.json` (copy `tools/remote/hosts.example.json`).
- `download_artifact.py` stays stdlib-only (bare operator PC) and refuses archive entries that escape the extract folder.
- Scratch and downloads go to `$ROSY_SCRATCH`, never into the repo. Failures raise a named error and exit non-zero; no silent fallback.

### Testing Requirements

```bash
python -m pytest test/test_download_artifact.py test/test_prepare_payload_release.py -q
```

Tests live in repo-level `test/` and do not hit the network.
