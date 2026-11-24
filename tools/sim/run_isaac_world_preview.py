"""Start the Isaac World preview with the registered SDK and GPU lease."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--belt-demo", action="store_true")
    args = parser.parse_args()
    run_id = os.environ.get("GZ_PARTITION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if (not re.fullmatch(r"sim-[a-z0-9-]{1,80}", run_id) or not domain.isdecimal()
            or not 0 < int(domain) <= 232 or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"):
        parser.error("requires an isolated remote_sim run")
    if not 10 <= args.seconds <= 360:
        parser.error("--seconds must be between 10 and 360")

    root = Path(__file__).resolve().parents[2]
    helpers = root / "learning/envs/isaac"
    sys.path.insert(0, str(helpers))
    from run_admission import acquire

    config = Path.home() / ".config/rosy"
    binding = json.loads((config / "isaac-sdk.json").read_bytes())
    code = json.loads((config / "model-code.json").read_bytes())
    sdk = Path(binding["python"])
    if binding["version"] != "6.2.0.0" or sha256(sdk.read_bytes()).hexdigest() != binding["python_sha256"]:
        raise RuntimeError("expected registered Isaac Sim 6.2")
    env = {
        "HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "OMNI_KIT_ACCEPT_EULA": "YES", "ACCEPT_EULA": "Y",
        "PYTHONUNBUFFERED": "1", "ROS_DISTRO": "jazzy", "ROS_DOMAIN_ID": domain, "GZ_PARTITION": run_id,
        "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST", "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        "SKIP_DEFAULT_XML": "1", "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
    }
    with acquire({"uid": os.getuid(), "model_code_root": code["root"]}) as locks:
        env["LD_LIBRARY_PATH"] = subprocess.check_output(
            [str(sdk), str(helpers / "sdk_ros.py")], env=env, text=True, timeout=12,
        ).strip()
        out = Path(os.environ["OUT"]) / "isaac-view.json"
        command = [str(sdk), "-u", str(Path(__file__).with_name("isaac_world_preview.py")),
                   "--stage", str(args.stage.resolve(strict=True)), "--out", str(out), "--seconds", str(args.seconds)]
        if args.belt_demo:
            command.append("--belt-demo")
        return subprocess.run(command, env=env, pass_fds=locks, timeout=args.seconds + 120).returncode


if __name__ == "__main__":
    raise SystemExit(main())
