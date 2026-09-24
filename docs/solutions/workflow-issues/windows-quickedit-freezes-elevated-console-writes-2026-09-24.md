---
title: Windows console QuickEdit freezes an elevated rpi-imager write with no error, and explains an old "hang" too
date: 2026-09-24
category: workflow-issues
module: deploy/sd (write-card.ps1, Pinky Pro release 2026.09.24-010)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "rpi-imager --cli sat at 0% CPU and 0 I/O 8 MB short of the end of the write; the stall watchdog had to kill it"
  - "the elevated card-writer console window's title had changed to \"Select ...\" after being clicked"
  - "release 005's unexplained 23-minute hang (documented separately) fits the same cause"
root_cause: config_error
resolution_type: code_fix
severity: high
tags: [windows, console, quickedit, rpi-imager, sd-writer, elevated-process, stall]
---

# Windows console QuickEdit freezes an elevated rpi-imager write with no error, and explains an old "hang" too

## Problem

Writing release `2026.09.24-010` to `rosy-pinky-e4us` stalled with `rpi-imager --cli` 8 MB short
of finishing. A click inside the elevated card-writer console window had put it into QuickEdit's
"Select" mode — the window title starts with `Select` once that happens. `rpi-imager --cli` writes
its progress to that same console, and a console in Select mode blocks any process writing to it
until a key is pressed or the selection is cleared. The stall watchdog (CPU and I/O transfer counts
sampled twice, per the existing liveness check) caught it and killed the process.

## Symptoms

- `rpi-imager --cli` process CPU time and `Win32_Process.WriteTransferCount`/`ReadTransferCount`
  both flat across two samples, 8 MB before the expected end of the write.
- The console window title reading `Select deploy...` instead of the normal title.
- Release `2026.09.23-005`'s previously-unexplained 23-minute hang (see
  [long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md](long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md))
  now reads as the same defect: nothing in that session's notes rules out an incidental click.

## What Didn't Work

- Relying on the stall watchdog alone. It correctly kills the stuck process, but every stall it
  catches this way costs a full re-run of an hour-plus elevated write.

## Solution

`deploy/sd/write-card.ps1` disables QuickEdit on the console's input handle before starting the
transcript, via `SetConsoleMode`:

```powershell
function Disable-QuickEdit {
    try {
        Add-Type -Namespace RosyConsole -Name Mode -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)] public static extern System.IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetConsoleMode(System.IntPtr handle, out uint mode);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleMode(System.IntPtr handle, uint mode);
'@ -ErrorAction Stop
        $consoleInput = [RosyConsole.Mode]::GetStdHandle(-10)
        $mode = [uint32]0
        # Clear ENABLE_QUICK_EDIT_MODE (0x40); ENABLE_EXTENDED_FLAGS (0x80) makes it stick.
        $ok = [RosyConsole.Mode]::GetConsoleMode($consoleInput, [ref]$mode) -and
            [RosyConsole.Mode]::SetConsoleMode($consoleInput, (($mode -band (-bnot [uint32]0x40)) -bor [uint32]0x80))
        if (-not $ok) { Write-Warning "could not turn off QuickEdit; do not click inside this window while the card is written" }
    }
    catch {
        Write-Warning "could not turn off QuickEdit; do not click inside this window while the card is written"
    }
}
Disable-QuickEdit

Start-Transcript -LiteralPath $LogPath | Out-Null
```

Typing still works with QuickEdit off; only mouse selection is disabled. When the Win32 call fails
(no console attached, restricted environment), the script warns instead of failing, since a warning
still lets an operator avoid clicking the window. PR #37 (merged) also has the review follow-up:
warn when QuickEdit could not be turned off, rather than assuming it succeeded.

## Why This Works

QuickEdit is a per-console mode, and once a window is in "Select" mode every process that writes to
that console — including a native tool like `rpi-imager` that has no idea it is running under an
agent-launched script — blocks on the write. Clearing `ENABLE_QUICK_EDIT_MODE` before the long write
starts removes the failure mode at its source instead of only detecting it after the fact.

## Prevention

- Any unattended long-running console job on Windows that shells out to a native tool which writes
  progress to the console must either disable QuickEdit on that console or avoid writing to an
  interactive console at all (e.g. redirect to a file).
- Keep the stall watchdog regardless — it is the backstop for causes this fix does not cover.

## Related Issues

- [long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md](long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md)
- [all-zero-first-sector-reads-as-a-different-cards-identity-2026-09-24.md](all-zero-first-sector-reads-as-a-different-cards-identity-2026-09-24.md)
