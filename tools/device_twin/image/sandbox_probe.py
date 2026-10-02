#!/usr/bin/env python3
"""Device twin: what rosy-auto-update.service's sandbox can see (twin only).

Started as twin-sandbox-probe.service, a copy of the real rosy-auto-update.service
with only ExecStart replaced, so it runs under the identical sandbox. Prints one
JSON line: rosy-core's MainPID, the owner of that process, and whether
/proc/<pid>/cwd is readable from inside the sandbox (the updater's health check
depends on it).
"""

import json
import os
import subprocess

shown = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", "rosy-core.service"],
                       capture_output=True, text=True, check=False)
pid = int(shown.stdout.strip() or 0)
result = {"main_pid": pid, "uid": os.getuid()}
try:
    result["cwd"] = os.readlink(f"/proc/{pid}/cwd")
except OSError as exc:
    result["cwd_error"] = f"{type(exc).__name__}: {exc}"
try:
    result["process_uid"] = os.stat(f"/proc/{pid}").st_uid
except OSError as exc:
    result["process_uid_error"] = str(exc)
for path in ("/opt/rosy", "/var/lib/rosy/updates", "/etc/rosy", "/home"):
    result[f"writable:{path}"] = os.access(path, os.W_OK)
print("TWIN_SANDBOX_PROBE " + json.dumps(result, sort_keys=True), flush=True)
