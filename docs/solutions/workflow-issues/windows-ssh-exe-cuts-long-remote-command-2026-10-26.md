---
title: Git for Windows ssh.exe silently cuts a long remote command
date: 2026-10-26
category: workflow-issues
module: tools/remote/remote_job.py
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "a laptop tool starts ssh from Python (subprocess) with the remote command as an argument"
  - "a remote pytest job or land.py invocation carries a long ROSY_* job word or many paths"
tags: [windows, ssh, git-bash, remote-pytest, land, truncation]
---

# Git for Windows ssh.exe silently cuts a long remote command

## Symptom

A docs-only FULL landing stopped at the isolation collection gate
(`ROSY_JOB_CORES=6 ROSY_COLLECT_PATHS=<115 paths> tools/collect_alone.py`): exit 2, one pytest session that
"collected 37684 items / 11 errors", every error an `import file mismatch` between same-basename test files, and no
`test_collects_alone` item. The same command with two paths passed. The MAIN-RED rerun (env words plus 11 file ids)
collected the same 37684 items, so pytest was ignoring its path arguments in both runs.

## Cause

On this laptop `subprocess.run(["ssh", ...])` resolves to `C:\Program Files\Git\usr\bin\ssh.exe`. Started from a
native Windows process, it cuts its remote command at about 8,190 bytes and reports nothing. `remote_job.ssh_call`
sent START as `bash -c '<script>' remote <args>`; the 4 KB job body plus the 5 KB gate word made about 10 KB, so the
cut fell inside the `ROSY_COLLECT_PATHS` value. Everything after it (`tools/collect_alone.py` and the pytest options)
was gone, and pytest with no path collected the whole tree in one process. Because the cut fell in an unquoted word,
bash raised no syntax error.

Measured from Python on 2026-10-26: Git ssh.exe returned `printf %s <8150 x> end | wc -c` intact and cut the 8,200
and 12,000 versions to 8,176 x's; `C:\Windows\System32\OpenSSH\ssh.exe` passed all of them. Running the same Git
ssh.exe from Git Bash also passed (MSYS passes argv to MSYS directly), so a shell repro does not show the cut. A
padding-only run (two good paths plus a 5,200-byte dummy `ROSY_PAD=` word) reproduced the 37684-item collection, so
the cause is the length, not a path in the list.

## Fix

`remote_job.ssh_call` (START, POLL and KILL for pytest and sim jobs) runs `bash -s` and writes the command to stdin.
`remote_pytest.remote`, whose stdin can carry the git bundle, builds its command with `remote_job.argv_command`,
which refuses one longer than `ARGV_MAX` (8,000) instead of letting ssh cut it. Regression test `test/test_remote_pytest.py::test_ssh_call_keeps_a_long_job_word_whole_past_the_ssh_exe_cut`
uses a stand-in ssh that cuts at the measured length.

## Apply next time

- Before passing data of unbounded size (path lists, file lists, ids) to a remote command, send it over stdin or a
  file, not argv. Keep the argv command short and fixed.
- When a remote pytest run collects far more than its arguments name, check how long the remote command was before
  bisecting the arguments.
- Reproduce ssh transport bugs from Python, not from Git Bash.
