---
title: A collection-time probe with a fixed file name races across xdist workers
date: 2026-10-28
category: workflow-issues
module: test/test_release_unpack_helper.py
problem_type: workflow_issue
component: testing_framework
severity: medium
applies_when:
  - "a test module does filesystem work at import or collection time (module-level skipif, pytestmark, constants)"
  - "that work uses a fixed name under tempfile.gettempdir(), TMPDIR or another shared directory"
  - "a land.py pretest stops with 'exited 1 without usable failure evidence' and 'Different tests were collected'"
tags: [pytest, xdist, collection, tmpdir, remote-pytest, land, flaky]
---

# A collection-time probe with a fixed file name races across xdist workers

## Symptom

On 2026-10-28 at about 03:15, a landing's `test/` pretest on the AI PC failed during collection. land.py
reported `pytest test exited 1 without usable failure evidence` and cancelled 19 other invocations. The log
showed two errors:

- `ERROR collecting test/test_release_unpack_helper.py`: `FileNotFoundError: '/tmp/rosy-pytest-XXXXXX/t/_perm_probe'`,
  raised by `probe.chmod(0o666)`.
- `ERROR gw2 - Different tests were collected between gw1 and gw2`: gw2 had lost that module's 16 tests.

The same files passed on the model PC (108 passed). The landing's own change did not touch them.

## Cause

`_filesystem_honors_posix_permission_bits(Path(tempfile.gettempdir()))` runs inside a module-level
`pytest.mark.skipif`, so every xdist worker runs it when it collects the module. All workers of one remote job
share `TMPDIR=$B/t` (`tools/remote/remote_job.py`). The probe wrote, chmodded, stat'ed and unlinked one fixed
name, `_perm_probe`. When two workers collected the module at the same moment, one unlinked the file while the
other was between write and chmod. No cleanup removed the job's TMPDIR. robot-45 checked the host storage
cleanup (it touches only `/tmp/pytest-of-<user>`) and the `remote_job.py` trap (it removes `$B` only after
pytest ends).

## Fix

The probe takes a unique name per caller: `fd, name = tempfile.mkstemp(prefix="perm_probe_", dir=tmp_path)`,
then `os.close(fd)`, then chmod, stat and unlink that path (`fix/release-probe-race`). A shared directory gets a
unique name. `tmp_path` and `tmp_path_factory` already give each test its own directory, so prefer them inside
tests. Collection-time code cannot use them, and that is where this probe ran.

## Evidence

- `test_the_permission_probe_survives_concurrent_callers_in_one_directory` calls the probe 400 times from 8
  threads in one directory. On the old code it failed remotely with the same `FileNotFoundError` (1 failed in
  0.61 s). With the fix the release suites pass: 109 passed, known_failures NEW 0.
- A search of `test/` found no other collection-time probe that writes a fixed name.

## Recovery and next time

- A landing stopped this way is not stopped by its own change. Run the named module alone remotely; if it
  passes, requeue `land.py`.
- Each such stop counts as a NEW in the rolling rate that sizes batches (D-889 addendum 4), so a flaky
  collection makes batches smaller for everyone. Fix the race instead of rerunning around it.
- When reviewing a test that probes the filesystem at module level, check the name is unique per process.
