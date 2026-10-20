"""Prepare committed native OMX inputs; activate only into provisioned user seats."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sysconfig
import tarfile
import tempfile
import uuid

from native_sim_inputs import (dependency_inventory, inventory, load_config, read_json,
                               run_identity, verify_bindings, verify_inventory, write_json)


def environment(config):
    quote = shlex.quote
    lines = ["set -eo pipefail", "export PYTHONDONTWRITEBYTECODE=1",
             "export PATH=/usr/bin:/bin:$PATH", "source " + quote(config["ros_setup"]),
             "source " + quote(str(Path(config["overlay"]) / "setup.bash"))]
    prefix = config.get("dependency_prefix")
    if prefix:
        for variable, suffix in (("AMENT_PREFIX_PATH", ""), ("CMAKE_PREFIX_PATH", ""),
                                 ("LD_LIBRARY_PATH", "/lib")):
            lines.append("export " + variable + "=" + quote(prefix + suffix) + ":${" + variable + "-}")
    lines += ["export PYTHONPATH=" + quote(config["python_site"]) + ":${PYTHONPATH-}",
              "export OMX_CELL_ROS_SETUP=" + quote(config["ros_setup"]),
              "export OMX_CELL_OVERLAY=" + quote(config["overlay"]),
              "export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST", "unset ROS_LOCALHOST_ONLY",
              "export ROS_LOG_DIR=\"$OMX_NATIVE_STATE/logs\"",
              "export HOME=\"$OMX_NATIVE_STATE/home\"", "export TMPDIR=\"$OMX_NATIVE_STATE/tmp\"",
              "export XDG_CACHE_HOME=\"$OMX_NATIVE_STATE/cache\"",
              "export GZ_PARTITION=\"rosy-native-$OMX_NATIVE_RUN_ID\"", "set -u"]
    return "\n".join(lines) + "\n"


def run_script(source, *, experiment="g2"):
    if experiment not in {"g2", "pick-place"}:
        raise ValueError("unknown native simulation experiment")
    entry = "g2_runner.py" if experiment == "g2" else "sim_pick_place_task.py"
    runner = str(Path(source) / "deploy/robot/omx" / entry)
    mode = " --mode run" if experiment == "g2" else ""
    return ("#!/bin/bash\nset -eo pipefail\n"
            "source \"$OMX_NATIVE_STATE/environment.sh\"\n"
            "exec /usr/bin/python3 -B " + shlex.quote(runner) +
            mode + " --evidence \"$OMX_NATIVE_STATE/" + experiment + "\""
            " --approve-isolated-simulation --approve-startup-home\n")


def export_source(source, revision, destination):
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise ValueError("source HEAD does not match requested run revision")
    destination.mkdir(mode=0o700)
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["git", "-C", str(source), "archive", "--format=tar", revision],
                       stdout=archive, check=True, timeout=120)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as bundle:
            for item in bundle.getmembers():
                if item.issym() or item.islnk() or item.name.startswith("/") or ".." in Path(item.name).parts:
                    raise ValueError("unsafe committed source archive member")
            bundle.extractall(destination, filter="data")


def sdk_preflight(source, state):
    probe = state / "sdk_probe.py"
    probe.write_text("import sys\nfrom pathlib import Path\n"
                     "sys.path.insert(0, str(Path(sys.argv[1]) / 'deploy/robot/omx'))\n"
                     "from g2_runner import preflight\n"
                     "preflight(Path(sys.argv[2]), sdk=True)\n", encoding="utf-8")
    (state / "sdk").mkdir(mode=0o700)
    command = 'source "$OMX_NATIVE_STATE/environment.sh"; exec /usr/bin/python3 -B "$1" "$2" "$3"'
    env = dict(os.environ, OMX_NATIVE_STATE=str(state), OMX_NATIVE_RUN_ID="sdk-preflight",
               PYTHONDONTWRITEBYTECODE="1")
    with (state / "sdk.stdout").open("xb") as stdout, (state / "sdk.stderr").open("xb") as stderr:
        subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", command, "sdk",
                        str(probe), str(source), str(state / "sdk")],
                       env=env, stdout=stdout, stderr=stderr, check=True, timeout=180)
    receipt = read_json(state / "sdk/preflight.json")
    if receipt.get("sdk_imports_verified") is not True or receipt.get("source_import_closure") != "VERIFIED":
        raise ValueError("SDK imports or source origins were not verified")


def prepare(source, config_path, staging, run_id, *, experiment="g2"):
    script = run_script(Path(staging).absolute() / "source", experiment=experiment)
    revision = run_identity(run_id)
    config = load_config(config_path)
    staging = Path(staging).absolute()
    staging.mkdir(mode=0o700)  # Never recycle a partially prepared attempt.
    source_out, state = staging / "source", staging / "state"
    export_source(Path(source), revision, source_out)
    state.mkdir(mode=0o700)
    for name in ("home", "tmp", "logs", "cache"):
        (state / name).mkdir(mode=0o700)
    (state / "environment.sh").write_text(environment(config), encoding="utf-8")
    (state / "run.sh").write_text(script, encoding="utf-8")
    roots = [str(Path(config["ros_setup"]).parent), config["overlay"], config["python_site"],
             "/usr/bin/python3", "/usr/lib/python3/dist-packages", sysconfig.get_paths()["stdlib"]]
    if config.get("dependency_prefix"):
        roots.append(config["dependency_prefix"])
    roots = sorted(set(roots))
    # Hash before AND after SDK imports; changing artifacts cannot earn a PASS receipt.
    dependencies = dependency_inventory(roots)
    source_hashes = inventory(source_out)
    sdk_preflight(source_out, state)
    if dependency_inventory(roots) != dependencies:
        raise ValueError("dependency input drift during SDK preflight")
    verify_inventory(source_out, source_hashes)
    metadata = {"schema": "rosy.omx-native-sim-prepared/1", "revision": revision, "experiment": experiment,
                "run_id": run_id, "role": config["role"], "source": str(source_out), "state": str(state),
                "source_hashes": source_hashes, "dependency_roots": roots, "dependency_hashes": dependencies,
                "state_hashes": inventory(state, exclude={"home", "tmp", "logs", "cache"}),
                "sdk_status": "PASS", "runtime": "NOT_RUN"}
    write_json(staging / "prepared.json", metadata)
    return metadata


def activation_result(manifest):
    return {key: manifest[key] for key in ("revision", "run_id", "role", "release", "state", "unit")}


def activate(prepared, state_root):
    prepared, state_root = Path(prepared).absolute(), Path(state_root).absolute()
    document = read_json(prepared / "prepared.json")
    source, staged_state = Path(document["source"]), Path(document["state"])
    if source != prepared / "source" or staged_state != prepared / "state":
        raise ValueError("prepared path bindings mismatch")
    verify_bindings(document, source, staged_state)
    for anchor in (state_root, state_root / "releases", state_root / "state"):
        if not anchor.is_dir() or anchor.is_symlink() or anchor.resolve() != anchor:
            raise PermissionError("native host needs provisioned directory anchors")
    revision = run_identity(document["run_id"])
    release = state_root / "releases" / revision
    state = state_root / "state" / document["run_id"][-12:]
    if release.exists():
        if release.is_symlink():
            raise ValueError("release path drift")
        verify_inventory(release, document["source_hashes"])
    else:
        pending = release.with_name(".pending-" + uuid.uuid4().hex)
        shutil.copytree(source, pending)
        verify_inventory(pending, document["source_hashes"])
        os.rename(pending, release)
    if state.exists():
        from native_sim_job import validate_state
        existing = validate_state(state)
        if (any(existing[key] != document[key] for key in
                ("revision", "run_id", "source_hashes", "dependency_roots", "dependency_hashes", "role"))
                or existing.get("prepared_state_hashes") != document["state_hashes"]):
            raise ValueError("immutable input drift on activation reuse")
        return activation_result(existing)
    pending = state.with_name(".pending-" + uuid.uuid4().hex)
    shutil.copytree(staged_state, pending)
    verify_inventory(pending, document["state_hashes"], exclude={"home", "tmp", "logs", "cache"})
    (pending / "run.sh").write_text(run_script(release, experiment=document.get("experiment", "g2")), encoding="utf-8")
    # SDK probe is preparation evidence; execution uses the newly bound release path.
    manifest = {**document, "schema": "rosy.omx-native-sim-state/1", "source": str(release),
                "release": str(release), "state": str(state),
                "unit": "rosy-native-sim-" + document["run_id"],
                "prepared_state_hashes": document["state_hashes"],
                "state_hashes": inventory(pending, exclude={"home", "tmp", "logs", "cache"})}
    write_json(pending / "manifest.json", manifest)
    os.rename(pending, state)
    from native_sim_job import validate_state
    return activation_result(validate_state(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment", choices=("g2", "pick-place"), default="g2")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    if args.activate and args.state_root is None:
        parser.error("--activate requires the provisioned --state-root")
    result = prepare(args.source, args.config, args.staging, args.run_id, experiment=args.experiment)
    if args.activate:
        result = activate(args.staging, args.state_root)
    summary = {key: value for key, value in result.items() if not key.endswith("_hashes")
               and key != "dependency_roots"}
    summary.update(prepared=str(args.staging / "prepared.json"))
    if not args.activate:
        summary.update(source_file_count=len(result["source_hashes"]),
                       dependency_file_count=len(result["dependency_hashes"]))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
