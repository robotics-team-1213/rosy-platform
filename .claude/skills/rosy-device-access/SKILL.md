---
name: rosy-device-access
description: Use when a task needs to reach a Rosy robot (Pinky Pro, native Ubuntu image) from the Windows operator PC — running a command or Python over SSH, reading root-only files under /run/rosy-boot or /etc/rosy, rebooting and waiting for it to come back, or getting a dashboard administrator login — and ssh prompts for a password, hangs, rejects the key, or Korean output turns into mojibake.
---

# Reaching a Rosy robot from the Windows operator PC

## Overview

Every robot access from an agent is **non-interactive**: key-only SSH as `rosy`, pinned host
key, `sudo -n`. Anything that would prompt (password, host-key question, sudo password) is
a hang, not a question. Start **read-only**; change the robot only when the task says so.

The address is per site. This repo is public: write `<robot-ip>` in anything tracked and
take the real value from `private/` (gitignored) or the operator's memory.

## Quick reference

| Need | How |
|---|---|
| Account | `rosy` (passwordless sudo via `/etc/sudoers.d/60-rosy-operator`). `pinky` has no key; password auth is off on the native image |
| Key | `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519` |
| Host keys | `%LOCALAPPDATA%\Rosy\known_hosts` (`StrictHostKeyChecking=accept-new`; the path must not contain spaces) |
| Dashboard | `http://<robot-ip>:8080/dashboard` |
| Boot identity | `cat /proc/sys/kernel/random/boot_id` |
| Root-only | `/run/rosy-boot/*` (`hardware.json`, `boot-status.json`, `login-code.json`), `/etc/rosy/runtime.env` (0600): read with `sudo -n cat` |

## SSH

Git-bash (preferred: real heredocs, UTF-8 pipes):

```bash
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
R=<robot-ip>
KEY="$(cygpath -u "$LOCALAPPDATA")/Rosy/ssh/rosy-operator-ed25519"
KH="$(cygpath -u "$LOCALAPPDATA")/Rosy/known_hosts"
rssh() { ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KH" \
  -o ConnectTimeout=5 rosy@"$R" "$@"; }
rssh 'uname -r; systemctl is-active rosy-core rosy-io; sudo -n cat /etc/rosy/runtime.env'
```

Python on the robot, no temp file (quoted `'EOF'` so the PC shell expands nothing):

```bash
rssh 'sudo -n python3 -' <<'EOF'
import json; d = json.load(open("/run/rosy-boot/hardware.json"))
for row in d["devices"]: print(row["id"], row["state"], row.get("evidence", ""))
EOF
```

PowerShell 5.1: pipe a single-quoted here-string (`@'...'@ | ssh ... "sudo -n python3 -"`)
only for ASCII scripts — 5.1 pipes to native programs in `$OutputEncoding` (ASCII) and
Korean becomes `?`. Embedded double quotes in native arguments are mangled; keep remote
commands free of `"` or use Git-bash.

## Reboot and wait

```bash
before=$(rssh cat /proc/sys/kernel/random/boot_id)
rssh 'sudo -n systemctl reboot' || true          # the session drops; 255 is expected
for i in $(seq 1 36); do                          # bounded: 36 x 5 s = 3 min
  sleep 5; now=$(rssh cat /proc/sys/kernel/random/boot_id 2>/dev/null) || continue
  [ -n "$now" ] && [ "$now" != "$before" ] && { echo "rebooted: $now"; break; }
done
```

Uptime or "ssh answers again" is not proof: only a **different `boot_id`** is. After it
changes, wait for `systemctl is-active rosy-core` = `active` before testing the API.

## Dashboard administrator login (D-193)

```bash
rssh 'sudo -n rosy-login-code --role administrator --minutes 10'   # prints "Login code ABCD-EFGH"
```

- The code works **once**. Pair it for a token: `POST /api/v1/auth/pair` `{"code": "ABCD-EFGH", "label": "agent"}` → 201 with `token` (administrator: 24 h). Or type it into the dashboard login drawer.
- Every paired token is listed and revocable. When done: `POST /api/v1/auth/logout` with that token (204). Card tokens cannot log out (409).
- Never print, commit or log the code or token; keep it in a variable or a file under `X:\DevTemp`.

## Never do

- `dtoverlay -r` without a name. It removes whichever overlay was loaded last (it once took out the LED overlay). Runtime `dtoverlay` does not work on the Ubuntu raspi kernel anyway — overlays go in `config.txt` plus a reboot.
- Full I2C bus scans (`i2cdetect` on every address). A wedged bus costs ~1 s per address; read known addresses only (see rosy-hw-bringup).
- Dev overlay (D-179, `deploy/robot/dev/`) of current `main` CORE onto an older release: after the D-241–D-243 moves it crash-loops CORE and takes the dashboard down. Build a release from `main` instead.
- Password SSH, `pinky@`, `StrictHostKeyChecking=no`, or `sudo` without `-n`.
- Writing `runtime.env`, `config.txt`, or restarting `rosy-io` without the task asking for it and a backup first (`sudo -n cp -a f f.bak-$(date +%s)`).

## Common mistakes

| Symptom | Cause |
|---|---|
| `Permission denied (publickey)` | Wrong user (`pinky`) or key not passed with `IdentitiesOnly=yes` |
| ssh hangs | No `BatchMode=yes`; it is waiting on a prompt |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Card was re-flashed. Confirm with the operator, then `ssh-keygen -R <robot-ip> -f <known_hosts>`; never disable checking |
| `UnicodeEncodeError` / broken Korean | cp949 console: set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` |
| `sudo: a password is required` | Not the `rosy` account, or the image predates the sudoers drop-in |
| Path with spaces breaks | The repo is under `Rosy OS/`: quote every path in Git-bash |

Related: rosy-hw-bringup (what to read once you are in), rosy-dashboard-drive (using the token).
