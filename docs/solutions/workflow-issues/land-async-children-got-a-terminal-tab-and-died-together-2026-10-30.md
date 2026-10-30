---
title: Every land_async lander died in the same second because its land.py got a console, a tab of the default terminal
date: 2026-10-30
category: workflow-issues
module: tools/land_async.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: config_error
resolution_type: code_fix
symptoms:
  - "many landings end within seconds of each other with 'did not land (exit 3221225786)' and no STOP line"
  - "8 landers on 2026-10-28 16:54:45, 12 on 2026-10-30 18:58:06-15; the queue lost its tickets at once"
  - "the supervisor survived (it wrote the 'did not land' line); only its land.py child was killed"
applies_when:
  - "a landing log ends with exit 3221225786 (0xC000013A, STATUS_CONTROL_C_EXIT)"
  - "a detached Windows process starts a console program (python, git, ssh) without creationflags"
tags: [land-async, windows, console, windows-terminal, ctrl-close, detached-process]
---

# Every land_async lander died in the same second because its land.py got a console, a tab of the default terminal

## Problem

`land_async.py` starts its supervisor with `DETACHED_PROCESS`, so the supervisor has no console. The supervisor
then ran `tools/land.py` with plain `subprocess.call`. A console program whose parent has no console gets a new
console. On Windows 11 the new console is handed to the default terminal (Windows Terminal) as a tab. When that
terminal window closed, every land.py in it got `CTRL_CLOSE_EVENT` and exited with `0xC000013A`. The supervisors
had no console and survived. They marked each snapshot `.stopped`.

The 2026-10-28 record (`Rosy/docs/workspace-records/2026-10-28/fleet-arm-current-state.md`) saw the same exit
code on 8 landers and left the cause unresolved.

## Evidence

- On 2026-10-30, 22 landing logs ended with exit 3221225786: 8 on 10-28 16:54:45 and 12 on 10-30 18:58:06-15. No
  reboot happened (last boot 10-20). A new `WindowsTerminal` process started at 19:00:15, right after the kill.
- Three land.py processes that land_async started at 19:00:14, 19:00:22 and 19:00:42 each had their own
  `conhost.exe` child, and an `OpenConsole` appeared at each of those times.
- Laptop experiment: a detached parent started `python -c "time.sleep(25)"`. Without flags, one new `OpenConsole`
  appeared. With `CREATE_NO_WINDOW` (0x08000000), none did. After the fix, 6 relaunched landers opened no new
  `OpenConsole` or `WindowsTerminal`.

## Solution

`supervise()` runs land.py with `creationflags=CREATE_NO_WINDOW` on Windows (`NO_WINDOW` in
`tools/land_async.py`). The child still has a console, so its git and ssh children share it, but the console has
no window that anyone can close. `test/test_land_async.py::test_supervise_cleans_up_only_a_landed_snapshot` pins
the flag.

## Recovery

A lander killed this way left no STOP line, so nothing needs fixing on its branch:

1. Check that the hidden tree is clean, holds no queue ticket, and has no live land.py.
2. If land.py had moved it onto a batch candidate (`...-batch<n>-k2`), check out its own snapshot branch again.
3. Relaunch the supervisor on the existing tree and snapshot:
   `land_async.py --supervise <tree> <snapshot> --tests auto`, detached, logging to a new file.
4. Remove the old `.stopped` marker, because a supervisor that lands does not remove it.

On 2026-10-30, 6 killed landings from other sessions were resumed this way.

## Prevention

- From a detached process on Windows, start every console child with `CREATE_NO_WINDOW` or `DETACHED_PROCESS`.
- When several landings stop together with no STOP line, look for the shared cause (a closed console, the
  network, a test host) before rerunning each one.
