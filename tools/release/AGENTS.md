<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# release

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Developer-side steps between "the GitHub runner built a payload" and "push a signed release to a robot". These run on the release operator's PC. Robot-side install, signing code and the push script live in `deploy/robot/pinky_pro/` (`release/`, `rosy-release-push.ps1`), not here.

## Key Files

| File | Description |
|------|-------------|
| `download_artifact.py` | Downloads one GitHub Actions artifact (`--run` + `--name`, or `--artifact-id`) with parallel resumable byte ranges (`--workers`, default 8), progress with rate and ETA, exact API-size check, optional `--extract DIR` (CRC check, entries that escape the folder are refused). Parts live next to the output (`<out>.parts/`) and a re-run resumes. Token from `GH_TOKEN` or `gh auth token`; neither it nor the signed URL is printed. Stdlib only. Exists because `gh run download` printed nothing for a 2.6 GB artifact |
| `ship.py` | D-553 addendum 4: one command for a delta (`--base <id> --robots 9dfk,8kcn`): calibration guards, `payload-reserved-<id>` tag, `make_delta_release`, one ssh session per robot at once (`deploy/robot/pinky_pro/rosy-ship-remote.sh`), camera-only restart when only camera perception code changed, image-layer sync only for `deploy/robot/native/` changes, one summary. `--dry-run` builds only. Tests: `test/test_ship.py` |
| `make_delta_release.py` | D-553 addendum 3: signed delta payload from a prepared signed base and a commit: maps each changed source file to payload files with the same name and old content, refuses build inputs/added/deleted/unmapped shipped files, builds the new manifest/SHA256SUMS from the base's signed metadata (addendum 4, no local full tree), keeps `.modes.json` for the next delta, packs only metadata + changed files + `.rosy-delta-base`. Never pushes or publishes. Tests: `test/test_make_delta_release.py` |
| `prepare_payload_release.py` | From a `build-native-payload.yml` run (`--run`) or a downloaded folder (`--artifact-dir`) to a signed payload tarball: download, required-package list must name only ROSY packages, read-only ROS ABI check per `--robot` over SSH (`--skip-abi` to skip), atomic extract (refuses an existing dir), sign (`sign_image_release.py`) and pack (`build_payload_release.py pack`), then prints the `rosy-release-push.ps1` lines. Never pushes. Release id is `YYYY.MM.DD-NNN`; default work folder is under `X:\DevTemp` |

## For AI Agents

### Working In This Directory

- Never push or activate from these scripts; printing the push command is the boundary. Pushing is a separate, operator-approved step (project skill `rosy-release-push`).
- The signing private key is read from the operator's local application-data folder and is never copied into the repo or printed. Only the public key (`deploy/robot/pinky_pro/release/public-keys/`) is tracked.
- Never print the GitHub token or a signed download URL, in logs or in error messages.
- The ABI check is read-only (`dpkg-query`); do not add commands that change a robot.
- Robot addresses are arguments, not constants; do not hard-code them.
- Keep stdlib-only for `download_artifact.py` so it runs on a bare operator PC.

### Testing Requirements

```bash
python -m pytest test/test_download_artifact.py test/test_prepare_payload_release.py -q
```

The tests live in the repo-level `test/`, not here, and do not hit the network.

### Common Patterns

- Scratch and downloads go to `X:\DevTemp`, never into the repo.
- Failures raise a named error and exit non-zero with the reason; there is no silent fallback.

## Dependencies

### Internal

- `deploy/robot/pinky_pro/release/` (`sign_image_release.py`, `build_payload_release.py`), `.github/workflows/build-native-payload.yml`, `deploy/robot/pinky_pro/rosy-release-push.ps1`

### External

- GitHub API access (`GH_TOKEN` or `gh`), OpenSSH client for the ABI check, the operator's signing key

<!-- MANUAL: -->
