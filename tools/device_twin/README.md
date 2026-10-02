# D-410 device twin

A systemd container that stands in for a Pinky Pro robot, so D-410 auto-update can be checked end to end without hardware.

It is a test tool only. Nothing here goes into the device image or into a payload.

## Run

```powershell
python tools/device_twin/run_twin.py --scenario all      # every scenario, about 25 min
python tools/device_twin/run_twin.py --scenario b,f      # a subset
python tools/device_twin/run_twin.py --list
```

- **Needs:** Docker Desktop (WSL2 backend, cgroup v2), Python 3.12+ on the host, and Git's `openssl.exe`. `signing.py` finds Git's copy by itself.
- **Output:** everything goes under `X:\DevTemp\d406-twin` (`--work`).
  - `report.md`: pass or fail per scenario, with the commands and their key output.
  - `logs/publish-<id>.log`: what the publish tool printed.
  - `store/`: the fake GitHub, including `requests.jsonl` and `gh-calls.jsonl`.
- **Exit code:** 0 only if every selected scenario passed.
- **Commit first.** The product side (`deploy/robot/pinky_pro`) comes from `git archive HEAD`, so it always has LF line endings. The twin's own files come from the working tree, converted to LF.

## What it builds

| Piece | How |
|---|---|
| Key | A fresh Ed25519 key for each run, made with `openssl genpkey` in the base container. The device installs it under its fixed trust name `rosy-release-2026-01.pem`. The private key is copied to `<work>\localappdata\Rosy\signing\twin-d406-test.private.pem`. The operator's key in `%LOCALAPPDATA%\Rosy\signing` is never read. |
| Releases | `build_twin_release.py` runs in the base container. The payload is the real `install-native-runtime.sh` output in `deploy/robot/native`, plus `install/.rosy-release`, `rosy-packages.txt`, `source-revision.txt` (HEAD), `python-runtime.sha256` and `twin/` (the fake programs). It is then built with `build_payload_release.py build`, signed with `sign_image_release.py`, and packed with `build_payload_release.py pack --public-key`. |
| Image | `image/Dockerfile` uses `ubuntu:24.04` with systemd as PID 1. `image/install_twin.sh` adds:<ul><li>the real `/opt/rosy/native-runtime` and the real rosy units;</li><li>the users and groups the units need;</li><li>`/etc/rosy/runtime.env` in core mode with API port 18080;</li><li>the trust key and the Python runtime marker;</li><li>factory release A, unpacked by the real `rosy-release-unpack.sh`.</li></ul>The auto-update timer is not enabled: scenarios start `rosy-auto-update.service` with `systemctl`. |
| Fake ROS | Drop-ins in `rosy-{core,io,camera}.service.d/twin.conf` replace only `ExecStart`. Each one runs a program from `/opt/rosy/current/twin/`. `WorkingDirectory`, `PartOf`, `After`, `Requires`, `ExecStartPost`, the restart policy and the sandbox all stay as the real units define them. |
| Fake CORE | Serves `GET /api/v1` and `GET /api/v1/openapi.json` (`info.version` = `twin-<release id>`). Writes `/run/rosy/status-inputs.json` schema 2 every 10 s. `twin-control idle\|moving\|manual\|battery\|estop\|stale` changes what it reports. A release's `twin/variant` makes it a bad build: `crash-after-ready` or `never-ready`. |
| Fake GitHub | `fake_github.py` runs in its own container on the `rosy-twin-net` network. It serves `GET /repos/<o>/<r>/releases` (ETag/304) and asset downloads. The device's `config.json` sets `api_base` to `http://rosy-twin-github:8080` and the repo to `twin/rosy-os`. |
| Fake `gh` | `fake_gh.py` handles `api …/matching-refs/tags`, `release create`, `release upload`, `release download` and `release view` over the same store. It accepts only `twin/*` repositories. |
| Publish | `twin_publish.py` runs the real `publish_payload_release.main()` and swaps only its `gh` runner (to `fake_gh.py`) and its `ssh` runner (to `docker exec -u rosy rosy-twin bash -c …`, with `sudo -n` as on the robot). It refuses to run unless `LOCALAPPDATA` points at the twin folder. |

## Scenarios

| Key | Checks |
|---|---|
| a | The fixed activator restarts CORE into the new release (new PID, cwd). The old target-only stop/start leaves CORE on the old process, which reproduces the 2026-10-01 defect. |
| b | Real publish, with the twin as canary. Then `systemctl start rosy-auto-update.service` goes staged → applying → committed. The publish tool sets `canary_ok`, and a second run gets a 304. |
| c | `moving`, `manual`, `battery`, `estop` and `stale` each make the robot ineligible. The CORE PID does not change, and the release is still staged. |
| d | `hold` makes the robot held. `release-hold` lets the next run commit. |
| e | A `hardware.approved` that names the current release makes the robot held. |
| f | Bad release C: CORE becomes ready, then dies. Expect a rollback to B and the image-layer marker removed again. C is recorded as failed and never retried, and the publish tool withdraws it. |
| f2 | Bad release N: CORE is never ready. Expect N refused or rolled back, A restored and N withdrawn. |
| g | A withdrawn release is never applied, even after a validly signed `withdrawn:false` rollout. |
| h | SIGKILL of the updater after activate, and a container power cut (`docker kill` + `start`). Both resume and commit. |
| h3 | A power cut during activate. Boot recovery and the resume must leave one consistent release. |
| i | `rosy_claim.py acquire` by a push makes the robot ineligible. |
| j | `systemd-analyze verify` on every rosy unit. A copy of the updater's sandbox must be able to read `/proc/<rosy-core pid>/cwd`. |

## Limits

- Only ROS is fake; everything around it is real. No hardware is checked: motors, LiDAR, camera, udev devices and the LED or display units.
- The container shares the WSL2 kernel. `ProtectKernel*`, device policy and cgroup behaviour are close to the robot's but not the same.
- The twin creates `/etc/modprobe.d` and `/etc/udev/rules.d`, which the robot's Ubuntu already has. `rosy-auto-update.service` names both in `ReadWritePaths=` without `-`.
- A container restart keeps the kernel, so `/proc/sys/kernel/random/boot_id` does not change across the twin's "power cut". `/run` is a tmpfs, so the claim still vanishes as it would on a real reboot.
- A twin pass is HOST-level evidence, not DEVICE evidence.
