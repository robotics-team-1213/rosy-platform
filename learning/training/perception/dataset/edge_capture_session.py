"""One edge-capture loop pass for a finished Pilot recording (re-runnable per session).

    edge_capture_session.py <session-id> --robot <robot-ip> --model-host <ssh-alias>
        --lane-model <model-PC path> --classes <model-PC classes.yaml>
        --sam3-checkpoint <model-PC sam3.pt> [--work data/perception/edge-capture]
        [--identity KEY --known-hosts FILE] [--from 1]

Steps (--from N restarts at step N; earlier outputs are reused):
  1 copy     robot -> <work>/<id>/<id>/ over operator SSH (read-only `sudo -n tar`),
             verified against the recording's sha256 manifest (fetch_http.verify);
             skipped when that folder exists
  2 video    bag_to_video -> <work>/<id>/video/
  3 frames   autolabel (D-379, LiDAR) + edge_capture.py frames
  4 prelabel model PC: lane-model masks for the edge frames (prelabel.py)
  5 drafts   v2 drafts on this PC (edge_capture.py drafts)
  6 review   model PC: verified inputs, SAM 3 v3 drafts, import into the review app
             (its systemd user unit is stopped for the import and always restarted)

The model PC runs this repo's code from --model-repo (a checkout that includes this
file). Remote relative paths are relative to the model-PC user's home. The model PC
is reached through the operator's own ssh config (an alias with its key); the robot
through operator_ssh (pinned known_hosts, key only). Nothing is approved: every
draft lands pending for a person (D-462).
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))

import fetch_http  # noqa: E402
import operator_ssh  # noqa: E402

RECORDINGS_ROOT = "/var/lib/rosy/pilot-recordings"
PYTHONPATH = ("middleware/perception", "contracts/foundation", "learning/training/perception",
              "learning/training/perception/dataset", "learning/training/perception/training")
DATASET = "learning/training/perception/dataset"


def local_env():
    paths = [str(REPO / p) for p in PYTHONPATH]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths + [os.environ.get("PYTHONPATH", "")])}


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def copy_session(args, s):
    final = s / args.session
    if final.exists():
        print(f"{final} exists: copy skipped")
        return
    try:
        opts = operator_ssh.options(*operator_ssh.resolve(args.identity, args.known_hosts), args.host_key_alias)
    except operator_ssh.SshConfigError as exc:
        sys.exit(f"refused: {exc}")
    part, staging = s / f".part-{args.session}.tar", s / f".staging-{args.session}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with part.open("wb") as out:
            run(["ssh", *opts, "--", f"{operator_ssh.USER}@{args.robot}",
                 f"sudo -n tar -C {shlex.quote(args.recordings_root)} -cf - {args.session}"], stdout=out)
        with tarfile.open(part) as archive:
            bad = [m.name for m in archive.getmembers() if m.name.split("/")[0] != args.session]
            if bad:
                sys.exit(f"refused tar members {bad[:3]}")
            archive.extractall(staging, filter="data")
        manifest = fetch_http.verify(staging / args.session, args.session)
        os.replace(staging / args.session, final)
        print("manifest ok", len(manifest["files"]))
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def ssh_model(args, script, *, stdin=None, stdout=None):
    """Run a bash script on the model PC; `abs` makes a home-relative path absolute."""
    head = 'set -euo pipefail; cd; abs(){ case "$1" in /*) echo "$1";; *) echo "$HOME/$1";; esac; }\n'
    cmd = ["ssh", "-o", "BatchMode=yes", args.model_host, "bash -c " + shlex.quote(head + script)]
    print("+ ssh", args.model_host, script.strip().splitlines()[0][:100], flush=True)
    return subprocess.Popen(cmd, stdin=stdin, stdout=stdout)


def send_dirs(args, s, names, remote):
    proc = ssh_model(args, f"E=$(abs {shlex.quote(remote)}); mkdir -p \"$E\"; tar -xf - -C \"$E\"",
                     stdin=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdin, mode="w|") as tar:
        for name in names:
            tar.add(s / name, arcname=name)
    proc.stdin.close()
    if proc.wait():
        sys.exit(f"upload of {names} failed")


def remote_vars(args):
    q = shlex.quote
    pp = ":".join(f"$C/{p}" for p in PYTHONPATH)
    return (f"C=$(abs {q(args.model_repo)}); E=$(abs {q(args.model_root)})/{args.session}; "
            f"PY=$(abs {q(args.model_python)}); export PYTHONPATH={pp}; cd \"$C/{DATASET}\"\n")


def prelabel(args, s):
    send_dirs(args, s, ["edge", "video"], f"{args.model_root}/{args.session}")
    q = shlex.quote
    script = remote_vars(args) + (
        f"rm -rf \"$E/prelabel\"\n"
        f"\"$PY\" prelabel.py \"$E/edge\" --model \"$(abs {q(args.lane_model)})\" "
        f"--classes \"$(abs {q(args.classes)})\" --out \"$E/prelabel\" >&2\n"
        f"head -4 \"$E/prelabel/ranking.csv\" >&2; tar -cf - -C \"$E/prelabel\" masks\n")
    proc = ssh_model(args, script, stdout=subprocess.PIPE)
    shutil.rmtree(s / "prelabel", ignore_errors=True)
    (s / "prelabel").mkdir()
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        tar.extractall(s / "prelabel", filter="data")
    if proc.wait():
        sys.exit("model-PC prelabel failed")


def review(args, s):
    send_dirs(args, s, ["drafts"], f"{args.model_root}/{args.session}")
    q = shlex.quote
    unit = q(args.review_unit)
    script = remote_vars(args) + (
        f"rm -rf \"$E/verified-inputs\"\n"
        f"\"$PY\" edge_capture.py verified \"$E\" --session {args.session} --classes \"$(abs {q(args.classes)})\"\n"
        f"\"$(abs {q(args.sam3_python)})\" edge_capture.py sam3 \"$E/verified-inputs\" "
        f"--checkpoint \"$(abs {q(args.sam3_checkpoint)})\"\n"
        f"export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user stop {unit}\n"
        f"trap 'systemctl --user start {unit}' EXIT\n"
        f"\"$PY\" edge_capture.py import \"$E/verified-inputs/verified-inputs-v3.jsonl\" "
        f"--state \"$(abs {q(args.review_state)})\"\n")
    if ssh_model(args, script).wait():
        sys.exit("model-PC review step failed")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="recording id, e.g. 20261006T082612Z_<robot>")
    ap.add_argument("--robot", help="robot address for step 1 (operator SSH)")
    ap.add_argument("--recordings-root", default=RECORDINGS_ROOT)
    operator_ssh.add_arguments(ap)
    ap.add_argument("--work", type=Path, default=REPO / "data" / "perception" / "edge-capture")
    ap.add_argument("--model-host", help="ssh destination of the model PC (an ssh config alias)")
    ap.add_argument("--model-repo", default="rosy-ml/repo", help="model-PC checkout of this repo")
    ap.add_argument("--model-root", default="rosy-ml/edge-capture", help="model-PC work folder")
    ap.add_argument("--model-python", default="rosy-ml/.venv/bin/python")
    ap.add_argument("--sam3-python", default="rosy-ml/sam3-venv/bin/python")
    ap.add_argument("--lane-model", help="model-PC accepted lane model folder")
    ap.add_argument("--classes", help="model-PC classes.yaml of the review workspace")
    ap.add_argument("--sam3-checkpoint", help="model-PC SAM 3.0 sam3.pt")
    ap.add_argument("--review-state", default="rosy-ml/edge-capture/review-state")
    ap.add_argument("--review-unit", default="rosy-edge-review", help="review app systemd user unit")
    ap.add_argument("--from", dest="start", type=int, default=1, choices=range(1, 7))
    args = ap.parse_args(argv)
    if not fetch_http.RECORDING_ID.fullmatch(args.session):
        ap.error(f"not a recording id: {args.session!r}")
    need = {1: ("robot",), 4: ("model_host", "lane_model", "classes"),
            6: ("model_host", "classes", "sam3_checkpoint")}
    missing = sorted({k for step, keys in need.items() if step >= args.start for k in keys
                      if not getattr(args, k)})
    if missing:
        ap.error("missing " + ", ".join("--" + k.replace("_", "-") for k in missing))
    if args.robot and not operator_ssh.safe_name(args.robot):
        ap.error(f"unsafe robot address {args.robot!r}")
    s = args.work / args.session
    s.mkdir(parents=True, exist_ok=True)
    env, ds = local_env(), str(HERE)
    py = sys.executable
    steps = {
        1: lambda: copy_session(args, s),
        2: lambda: run([py, "bag_to_video.py", s / args.session, "--out", s / "video", "--force"], cwd=ds, env=env),
        3: lambda: (run([py, "autolabel.py", s / args.session, "--out", s / "autolabel", "--min-interval", "0.5",
                         "--force"], cwd=ds, env=env),
                    run([py, "edge_capture.py", "frames", s / args.session, "--out", s / "edge"], cwd=ds, env=env)),
        4: lambda: prelabel(args, s),
        5: lambda: run([py, "edge_capture.py", "drafts", s, "--session", args.session], cwd=ds, env=env),
        6: lambda: review(args, s),
    }
    for n in range(args.start, 7):
        print(f"== {n}", flush=True)
        steps[n]()
    print("== done: drafts are pending in the review app's pixel queue")


if __name__ == "__main__":
    main()
