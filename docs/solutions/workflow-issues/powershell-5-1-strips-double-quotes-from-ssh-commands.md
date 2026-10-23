---
title: PowerShell 5.1 drops the double quotes inside an ssh command, so the remote line arrives mangled
date: 2026-10-23
category: workflow-issues
module: robot ssh operations
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "an ssh one-liner that works from a Linux shell fails on Windows PowerShell with a shell syntax or 'command not found' error naming a fragment of the command"
  - "the remote error points at a word that should have been one quoted argument, so the far shell split it"
  - "the same line succeeds when the remote text is sent as base64 instead of as a quoted argument"
root_cause: environment
resolution_type: workflow_improvement
severity: medium
tags: [ssh, powershell, quoting, windows, remote-command]
---

# PowerShell 5.1 drops the double quotes inside an ssh command

## Problem

2026-10-23, driving an OMX cell over `ssh robttt@<host> "<remote command>"` from Windows PowerShell
5.1, two remote commands arrived at the far shell with their inner double quotes removed. The quoted
fragments then split into separate words and the far shell reported an error about a fragment of the
command rather than about what the command was meant to do. Both times the remote line itself was
correct; only the transport had rewritten it.

The same session had already hit one Windows-layer encoding problem, so the first reaction was to
blame the remote shell or the service. The actual loss happened before `ssh` started.

## Symptoms

- The far shell reports a syntax error or "command not found" for a token that was written inside
  quotes locally, so the message points at a fragment instead of the command.
- Sending the same text as base64 instead of as a quoted argument makes it run, which clears the
  remote program and the far shell.
- A command with no embedded double quotes behaves normally, so the fault looks intermittent.
- Editing the remote line to make the error go away works once and fails again on the next command,
  because the transport strips the quotes from whatever is sent.

## What Did Not Work

- Re-typing the same quoting more carefully. PowerShell 5.1 strips embedded `"` when it builds the
  native-command line; being careful does not change that.
- Adding escapes by hand. Two attempts produced the same stripped result, and the surviving form
  depends on the PowerShell version, so it is not worth re-deriving per command.
- Assuming the far shell mangled it and rewriting the remote line. Two iterations were spent editing a
  correct remote command.

## Solution

Send the script as data, not as a quoted argument:

```powershell
$cmd = @'
systemctl --user status "rosy-omx-observer@arm_a.service"
'@
$b = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($cmd))
ssh robttt@<host> ("echo $b | base64 -d | bash")
```

The outer command contains no double quotes inside a quoted argument, so nothing is stripped. The far
side decodes the exact bytes and runs them under `bash`, which also makes multi-line commands and
Korean text safe. For a single short command with no inner double quotes, writing it without them
(e.g. `ssh host systemctl --user restart rosy-omx-observer@arm_a.service`) is enough.

## Why This Works

The loss is in PowerShell's argument serialization for native executables, not in `ssh` or the target
shell. Passing one base64 token removes every quote, space and newline from the argument PowerShell has
to serialize, so the serialization step has nothing to rewrite. `base64 -d | bash` then reconstructs
the original text byte for byte.

## Prevention

- Before blaming the remote host, run the same command through base64. If it succeeds, the fault was
  the transport.
- Treat any `ssh` failure that names a token from inside quotes as a quoting fault, not a remote-host
  fault, and do not tune the remote command to compensate.
- Prefer the base64 wrapper by default for multi-line remote work and for anything with quotes,
  `$`, `!` or non-ASCII. Keep plain `ssh host cmd` for one-word commands.
- Related Windows-layer traps that produced misleading remote symptoms:
  [pkill -f over ssh kills its own shell](../workflow-issues/pkill-f-over-ssh-kills-its-own-shell-2026-10-10.md),
  [PowerShell UTF-8 append mangles Korean journals](../workflow-issues/powershell-utf8-append-mangles-korean-journals.md).
