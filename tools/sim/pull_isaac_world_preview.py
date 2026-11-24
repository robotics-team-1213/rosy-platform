"""Forward one owned remote_sim viewport feed to a local World bundle."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


READ_REMOTE = """
import json, time
from pathlib import Path

path = Path.home() / "rosy-test/runs" / (RUN + "-out") / "isaac-view.json"
previous = None
deadline = time.monotonic() + SECONDS
while time.monotonic() < deadline:
    try:
        raw = path.read_bytes()
        if len(raw) <= 700000:
            item = json.loads(raw)
            stamp = item["observed_at_ms"]
            if item["run_id"] == RUN and stamp != previous and 0 <= time.time_ns() // 1000000 - stamp < 3000:
                print(raw.decode().strip(), flush=True)
                previous = stamp
    except (FileNotFoundError, ValueError, KeyError):
        pass
    time.sleep(.2)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", required=True, help="registered simulation SSH host or alias")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=360)
    args = parser.parse_args()
    if (not re.fullmatch(r"sim-[a-z0-9-]{1,80}", args.run_id)
            or not re.fullmatch(r"[a-zA-Z0-9._@-]+", args.ssh_host) or args.ssh_host.startswith("-")
            or not 10 <= args.seconds <= 900):
        parser.error("expected a simulation run ID, SSH host, and a bounded duration")
    output = args.bundle.resolve(strict=True) / "data" / "isaac-view.json"
    if not output.parent.is_dir() or not (output.parent.parent / "manifest.json").is_file():
        parser.error("expected a built World bundle")
    reader = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10",
         "-o", "ServerAliveCountMax=2", args.ssh_host, "python3 -u -"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    try:
        reader.stdin.write(f"RUN = {args.run_id!r}\nSECONDS = {args.seconds}\n".encode() + READ_REMOTE.encode())
        reader.stdin.close()
        count = 0
        for packet in reader.stdout:
            item = json.loads(packet)
            if (item.get("schema") != "rosy.world.isaac-view.v1" or item.get("run_id") != args.run_id
                    or not -1000 <= time.time_ns() // 1_000_000 - item["observed_at_ms"] < 3000):
                continue
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
                staged = Path(stream.name)
                stream.write(packet)
            try:
                staged.replace(output)
                count += 1
                if count == 1:
                    print(f"{args.run_id}: receiving live Isaac frames", flush=True)
            except PermissionError:
                if os.name != "nt":
                    raise
            finally:
                staged.unlink(missing_ok=True)
        code = reader.wait(timeout=5)
        return code if code else int(count == 0)
    finally:
        if reader.poll() is None:
            reader.terminate()
            reader.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
