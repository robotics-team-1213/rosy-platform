---
title: test/conftest.py silently repaired PATH, so signing tests stayed green while the real writer failed "openssl not found"
date: 2026-09-24
category: workflow-issues
module: deploy/release/signing.py (Windows operator path, Pinky Pro release 2026.09.24-010)
problem_type: test_failure
component: development_workflow
symptoms:
  - "prepare-rosy-sd.ps1 -PlanOnly failed with \"openssl not found; release signatures cannot be verified without it\" on a non-elevated operator PC"
  - "pytest for the signing module passed on the same machine with no changes to product code"
  - "only test/conftest.py, not deploy/release/signing.py, prepended Git for Windows' openssl to PATH"
root_cause: test_isolation
resolution_type: code_fix
severity: high
framework_version: "openssl 3 (Git for Windows bundled build)"
tags: [openssl, windows, path, conftest, test-isolation, sd-writer, release-signing]
---

# test/conftest.py silently repaired PATH, so signing tests stayed green while the real writer failed "openssl not found"

## Problem

`deploy/release/signing.py` shells out to `openssl` rather than adding a Python crypto dependency
(the device already has `openssl` in its base OS). Windows operator PCs, however, often carry
`openssl` only inside Git for Windows, which a plain PowerShell `PATH` does not include. The test
suite passed because `test/conftest.py` prepended Git for Windows' `openssl` folders to `PATH` for
every test process — a repair that lived only in the test harness. The real, non-elevated
`prepare-rosy-sd.ps1 -PlanOnly` run, invoked directly by an operator with no such `PATH` fixup,
failed with "openssl not found".

## Symptoms

- `prepare-rosy-sd.ps1 -PlanOnly` failed release-signature verification with "openssl not found"
  on a Windows operator PC.
- `pytest` for the signing module was green on the same machine, same day, no code changes needed
  to make it pass.

## What Didn't Work

- Trusting the passing pytest run as evidence the writer's signing path worked on a real operator
  PC. It only proved the path worked inside a process whose `PATH` the test harness had already
  patched.

## Solution

The fallback moved into `deploy/release/signing.py` itself, so the product code repairs its own
environment rather than depending on the test harness to have done it first:

```python
# Windows operator PCs often carry OpenSSL only inside Git for Windows, which a
# plain PowerShell PATH does not include. 2026-09-24: the card writer's release
# check failed with "openssl not found" while pytest passed, because only
# test/conftest.py knew these folders.
_WINDOWS_OPENSSL_DIRS = (
    r"C:\Program Files\Git\usr\bin",
    r"C:\Program Files\Git\mingw64\bin",
)


def _openssl() -> str:
    path = shutil.which("openssl")
    if path is None and os.name == "nt":
        for folder in _WINDOWS_OPENSSL_DIRS:
            candidate = os.path.join(folder, "openssl.exe")
            if os.path.isfile(candidate):
                path = candidate
                break
    if path is None:
        raise SigningToolMissing(
            "openssl not found; release signatures cannot be verified without it"
        )
    return path
```

Only fixed `Program Files` locations are searched — never a user-writable directory — so the
fallback cannot be used to smuggle in an attacker-controlled `openssl.exe`. PR #37 (merged).

## Why This Works

The fix lives in the same module that needs it at runtime, so every caller — the real
`prepare-rosy-sd.ps1` invocation and the test suite alike — goes through the identical discovery
logic. There is no longer a second, test-only source of truth for where `openssl` lives that the
production path does not share.

## Prevention

- When a test needs to repair the environment (PATH, missing binaries, config defaults) before the
  code under test will pass, treat that as a signal the repair belongs in the product code, not the
  test fixture. A fixture-only repair makes the test suite describe an environment the real
  deployment target does not have.
- Environment repairs belong in product code; tests exist to verify the repair works, not to stand
  in for it.

## Related Issues

- [windows-quickedit-freezes-elevated-console-writes-2026-09-24.md](windows-quickedit-freezes-elevated-console-writes-2026-09-24.md)
