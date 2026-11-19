"""rosy_ml: the operator CLI for the learned-perception loop (D-373 decision 7).

  rosy_ml init --robot NAME=HOST [...]   write your per-user config (paths only)
  rosy_ml doctor [ROBOT]                 check key, known_hosts, host name, robot, sudo, runtime, store
  rosy_ml repin ROBOT                    copy the robot's address-keyed host key under its id
  rosy_ml store-status [--init]          datasets and model inbox/accepted/rejected counts
  rosy_ml status [ROBOT]                 shadow pointer, installed revisions, history
  rosy_ml deliver ROBOT REVISION         push an intake-passed model to the shadow slot (holds the robot)
  rosy_ml promote ROBOT                  active <- shadow, old active -> previous (holds; D-423)
  rosy_ml rollback ROBOT [--slot active] back to shadow.previous, or active <- previous (holds)
  rosy_ml release-hold ROBOT             remove the hold: site auto delivery resumes
  rosy_ml harvest ROBOT                  pull finished recordings (only while idle)
  rosy_ml fetch ROBOT --http             pull Pilot recordings (D-411). The URL is the robot's _rosy._tcp advertisement
  rosy_ml intake SOURCE                  check a model folder, store-inbox:<folder>
                                         or (optional HF) hf:org/repo@<sha>

Config: ROSY_ML_CONFIG, else %APPDATA%\\Rosy\\ml.yaml (Windows) or
$XDG_CONFIG_HOME/rosy/ml.yaml, ~/.config/rosy/ml.yaml. It names robots, key
and known_hosts paths, the store folder (D-373 decision 8: a local path, a NAS
mount or a Google Drive folder, same layout), optionally an HF repo, and token
*files*; never a token itself.
Robots are addressed by name; the host lives only in your config. Use a host
*name* (`<hostname>.local`, mDNS) rather than an IP: the site network renumbers. The
host key is pinned under the robot name (ssh HostKeyAlias), never under the address;
an old address-keyed pin is shown by doctor/init and moved by `rosy_ml repin ROBOT`
(it never rewrites known_hosts on its own).

The commands wrap learning/registry/perception/deliver.py, learning/curation/perception/harvest.py, learning/curation/perception/fetch_http.py and learning/registry/perception/intake.py;
they add no behaviour of their own. Exit codes are those of the wrapped tool;
doctor exits 0 only if every required check passes, 1 otherwise; 2 is a bad
config or argument. Network failures of deliver/rollback/release-hold/status exit 77
(host name does not resolve), 78 (refused, timed out, no route) or 79 (host key unknown
or changed), see learning/registry/perception/deliver.py. status and store-status with --watch-config (or a
`state_file:` in the config) also show each robot's last watcher failure."""

from __future__ import annotations

import datetime as dt
import functools
import getpass  # noqa: F401
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
for _p in (HERE, ROOT / 'learning/registry/perception', ROOT / 'learning/curation/perception'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
import slot_cli  # noqa: E402
import store  # noqa: E402
from rosy_ml_helpers import (  # noqa: E402, F401
    MODELS_DIR,
    MODELS_OWNER,
    SITE_TOKEN_FILE,
    STALE_HOLD_H,
    _browse_robots,
    _check,
    _doctor_store,
    _failure_lines,
    _foundation,
    _host,
    _init,
    _inline_secrets,
    _is_ip,
    _known,
    _pin_hint,
    _repin,
    _ssh_argv,
    _store_status,
    _writable,
    build_parser,
    config_from_watch,
    config_path,
    core_base,
    load_config,
)

LEARNED_SITE = "/opt/rosy/learned-perception/site-packages"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _hold_age_h(hold: dict) -> float | None:
    try:
        ts = dt.datetime.strptime(hold["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    return (_utcnow() - ts).total_seconds() / 3600


# --- doctor ---------------------------------------------------------------------------------

def _replay_clip_count(cfg: dict) -> int | None:
    try:
        import intake
    except ImportError:
        return None
    gate = intake.load_gate(cfg.get("gate") or intake.DEFAULT_GATE)
    return len(intake.replay_videos(gate, cfg.get("replay_root") or intake.ROOT))


def _gate_eval_set(cfg: dict) -> Path | None:
    """The gate's eval set folder (D-379 d3) under replay_root, or None when unset."""
    try:
        import intake
    except ImportError:
        return None
    rel = intake.load_gate(cfg.get("gate") or intake.DEFAULT_GATE).get("eval_set")
    return Path(cfg.get("replay_root") or intake.ROOT) / rel if rel else None


class _Report:
    def __init__(self):
        self.failed = False

    def line(self, ok, label: str, hint: str = "", required: bool = True) -> None:
        mark = "✓" if ok else ("✗" if required else "!")
        print(f"{mark} {label}" + ("" if ok or not hint else f" — fix: {hint}"))
        self.failed |= required and not ok

    def check(self, label: str, probe, hint: str, required: bool = True) -> bool:
        """probe() -> bool; any exception is a failed check with its message."""
        try:
            ok = bool(probe())
        except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
            self.line(False, f"{label} ({type(exc).__name__}: {exc})", hint, required)
            return False
        self.line(ok, label, hint, required)
        return ok


def _doctor(cfg, robots, runner, connect, find_spec, resolve=socket.getaddrinfo, backend="onnx") -> int:
    rep = _Report()
    rep.line(True, f"config readable (operator {cfg['operator']})")
    key, kh = Path(cfg["ssh"]["identity"]), cfg["ssh"]["known_hosts"]
    if not key.is_file():
        rep.line(False, f"SSH key {key}", "create your own key (ssh-keygen -t ed25519) and ask "
                 "an admin to add its .pub to rosy's authorized_keys on each robot")
    elif os.name != "nt" and key.stat().st_mode & 0o077:
        rep.line(False, f"SSH key {key} is readable by others", f"chmod 600 {key}")
    else:
        rep.line(True, f"SSH key {key}")

    def remote(host, command, name, timeout=20):
        opts = operator_ssh.options(str(key), kh, name)
        try:
            return runner(["ssh", *opts, "--", f"rosy@{host}", command], check=False,
                          capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess([], 1, "", str(exc))

    def in_known_hosts(name, host):
        """The key must be under the robot id; an address-only pin is a failure with its fix."""
        if _known(runner, kh, name):
            return True
        if _known(runner, kh, host):
            raise LookupError(f"pinned under the address only; fix: {_pin_hint(name)} "
                              "(copies it under the id; the address changes, the id does not)")
        return False

    def resolves(host):
        if _is_ip(host):
            return True
        resolve(host, 22)
        return True

    def tcp22(host):
        try:
            connect((host, 22), timeout=3).close()
        except OSError:
            return False
        return True

    for name in robots:
        host = cfg["robots"][name]
        if _is_ip(host):
            rep.line(False, f"{name}: host is an IP; it breaks when the network renumbers",
                     "set the robot's host name (<hostname>.local) in your config",
                     required=False)
        resolved = rep.check(f"{name}: host name resolves", lambda: resolves(host),
                             "the name does not resolve here: wrong name in your config, robot "
                             "off, or mDNS (avahi / Bonjour) blocked on this network")
        rep.check(f"{name}: host key pinned under {name} (in known_hosts)",
                  lambda: in_known_hosts(name, host),
                  f"record the robot's host key once from a trusted network into {kh} under "
                  f"the name {name} (see .claude/skills/rosy-device-access/SKILL.md)")
        reachable = resolved and rep.check(
            f"{name}: TCP 22 reachable", lambda: tcp22(host),
            "robot off, wrong host name in your config, or not on this network")
        checks = [
            ("ssh as rosy (BatchMode)", "true", lambda r: r.returncode == 0,
             "your key is not in rosy's authorized_keys on this robot, or known_hosts is stale"),
            ("sudo -n works", "sudo -n true", lambda r: r.returncode == 0,
             "rosy needs passwordless sudo (/etc/sudoers.d/60-rosy-operator); older image?"),
            (f"{MODELS_DIR} is {MODELS_OWNER}",
             f"sudo -n stat -c '%U:%G %a' {MODELS_DIR}",
             lambda r: r.returncode == 0 and r.stdout.strip() == MODELS_OWNER,
             "run deploy/robot/pinky_pro/dev/install-learned-perception.sh on a bench "
             "robot, or use an image with D-373"),
            # The learned backend appends its own prefix (learned/runner.py
            # LEARNED_SITE, D-373 decision 1); a plain import would miss it.
            (f"robot python3 imports {'ncnn' if backend == 'ncnn' else 'onnxruntime'}",
             "cd / && PYTHONNOUSERSITE=1 python3 -c 'import sys; "
             f"sys.path.append(\"{LEARNED_SITE}\"); import {'ncnn' if backend == 'ncnn' else 'onnxruntime'}'",
             lambda r: r.returncode == 0,
             "install the pinned onnxruntime (install-learned-perception.sh) or reflash"),
        ]
        for label, command, good, hint in checks:
            if not reachable:
                rep.line(False, f"{name}: {label} (skipped: not reachable)")
                continue
            rep.check(f"{name}: {label}", lambda: good(remote(host, command, name)), hint)
        if reachable:
            try:
                text = remote(host, f"sudo -n cat {MODELS_DIR}/hold 2>/dev/null || true",
                              name).stdout
                hold = json.loads(text) if (text or "").strip() else None
            except Exception:  # noqa: BLE001 - a malformed hold file is still a hold
                hold = {"by": "?"}
            if hold:
                who = hold.get("by") if isinstance(hold, dict) else "?"
                age = _hold_age_h(hold) if isinstance(hold, dict) else None
                since = f" for {age:.0f} h" if age is not None else ""
                stale = (f" — older than {STALE_HOLD_H} h: ask {who} whether it is still needed"
                         if age is not None and age > STALE_HOLD_H else "")
                rep.line(False, f"{name}: held by {who}{since} (site auto delivery paused){stale}",
                         f"when done testing: rosy_ml release-hold {name}", required=False)

    for line in _failure_lines(cfg, robots):
        print(line)
    if cfg.get("store"):
        _doctor_store(rep, store.Store(cfg["store"]))
    else:
        rep.line(False, "no store configured (datasets and model hand-over live there)",
                 "rosy_ml init --store <path> --force, or add `store: <path>` to your config",
                 required=False)
    if cfg.get("hf_repo"):
        tok = cfg.get("hf_token_file")
        if tok:
            rep.check(f"HF token file {tok} for {cfg['hf_repo']}", lambda: Path(tok).is_file(),
                      "put a read-only HF token in that file (never inline in the config)")
        else:
            rep.line(False, f"no hf_token_file for {cfg['hf_repo']}",
                     "fine for a public repo; a private one needs hf_token_file",
                     required=False)
    if cfg.get("store") or cfg.get("hf_repo"):
        rep.check("replay clips for intake", lambda: _replay_clip_count(cfg),
                  "copy data/teleop/learning/*.mp4 under replay_root (or the repo root); "
                  "without clips every intake stops as a setup error")
        eval_set = _gate_eval_set(cfg)
        if eval_set is not None:
            rep.check(f"intake eval set {eval_set}", lambda: (eval_set / "manifest.json").is_file(),
                      "build it with dataset/build.py --auto-labels ... --eval-set, or set "
                      "eval_set: null in the gate; without it every lane intake stops as a setup error")
    # The site watcher's intake needs both (onnx reads the graph's precision);
    # without them every inbox model stops with a config error (watch exit 6).
    site = str(cfg.get("operator", "")).startswith("site:")
    for module in (("ncnn",) if backend == "ncnn" else ("onnxruntime", "onnx")):
        rep.check(f"local {module} importable", lambda m=module: find_spec(m) is not None,
                  ("the site watcher's intake needs it: install it in /opt/rosy/model-watch/venv "
                   "(deploy/site/README.md)") if site else
                  f"needed for rosy_ml intake only: pip install {module} in your venv",
                  required=site)
    return 1 if rep.failed else 0


# --- main -----------------------------------------------------------------------------------

def main(argv=None, *, runner=subprocess.run, connect=socket.create_connection,
         find_spec=importlib.util.find_spec, resolve=socket.getaddrinfo,
         discover=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = build_parser(__doc__.splitlines()[0])
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return _init(args, runner)
    if args.cmd == "fitness":
        path = str(ROOT / "learning/evaluation/perception")
        if path not in sys.path:
            sys.path.insert(0, path)
        import road_fitness_replay
        return road_fitness_replay.execute(args)
    if args.cmd == 'object-fitness':
        path = str(ROOT / 'learning/evaluation/perception')
        if path not in sys.path:
            sys.path.insert(0, path)
        import object_fitness_replay
        return object_fitness_replay.execute(args)
    if args.cmd == 'observe':
        path = str(ROOT / 'learning/evaluation/perception')
        if path not in sys.path:
            sys.path.insert(0, path)
        import road_observation_replay
        return road_observation_replay.execute(args)
    try:
        if getattr(args, "watch_config", None):
            import watch
            cfg = config_from_watch(watch.load_config(args.watch_config), selected_robot=getattr(args, 'robot', None))
        else:
            path = config_path()
            if not path.exists():
                print(f"✗ no config at {path} — fix: run rosy_ml init")
                return 1 if args.cmd == "doctor" else 2
            cfg = load_config(path)
        robots = [args.robot] if getattr(args, "robot", None) else list(cfg["robots"])
        hosts = [_host(cfg, r) for r in robots]
    except RuntimeError as exc:
        if getattr(exc, 'kind', None) not in operator_ssh.KIND_EXIT:
            raise
        print(f"✗ network: {exc} — retry when the approved robot is reachable")
        return operator_ssh.KIND_EXIT[exc.kind]
    except (OSError, ValueError) as exc:
        print(f"✗ config — fix: {exc}")
        return 2
    if args.cmd == "doctor":
        return _doctor(cfg, robots, runner, connect, find_spec, resolve, backend=args.backend)
    if args.cmd == "repin":
        return _repin(cfg, args.robot, runner)
    if args.cmd == "store-status":
        return _store_status(cfg, args.init)
    if args.cmd in ("status", "deliver", "promote", "rollback", "release-hold"):
        import deliver
        if args.cmd == "status":
            rc = 0
            for line in _failure_lines(cfg, robots):
                print(line)
            for name, host in zip(robots, hosts):
                print(f"== {name}")
                rc = max(rc, deliver.main(["status", host, *_ssh_argv(cfg, name), "--history",
                                           str(args.history), "--task", args.task], runner=runner))
            return rc
        head = slot_cli.deliver_argv(args, hosts[0], str(cfg["intake_out"]))
        return deliver.main([*head, *_ssh_argv(cfg, robots[0]), "--operator", cfg["operator"]],
                            runner=runner)
    if args.cmd == "harvest":
        import harvest
        argv = [hosts[0], *_ssh_argv(cfg, robots[0])]
        if cfg.get("core_token_file"):
            argv += ["--core-token-file", cfg["core_token_file"]]
        if args.dest:
            argv += ["--dest", args.dest]
        if args.assume_idle:
            argv.append("--assume-idle")
        return harvest.main(argv)
    if args.cmd == "fetch":
        import fetch_http
        # The archive is Operator-only; harvest's core_token_file is a viewer token.
        if not cfg.get("core_operator_token_file"):
            print("✗ fetch --http needs an Operator token — fix: rosy_ml init --core-operator-token-file <file>")
            return 2
        try:
            base = core_base(hosts[0], (discover or _browse_robots)())
        except (ValueError, LookupError) as exc:
            print(f"✗ fetch: {exc}")
            return 2
        if base.startswith("https://") and not args.ca_file:
            print("✗ fetch: this robot advertises TLS — fix: pass --ca-file <device CA>")
            return 2
        if args.ca_file and not base.startswith("https://"):
            print("✗ fetch: this robot does not advertise TLS; --ca-file does not apply")
            return 2
        argv = [base, "--token-file", cfg["core_operator_token_file"]]
        if args.ca_file:
            argv += ["--ca-file", args.ca_file]
        if args.dest:
            argv += ["--dest", args.dest]
        if args.video_out:
            argv += ["--video-out", args.video_out]
        if args.only:
            argv += ["--only", args.only]
        return fetch_http.main(argv)
    if args.cmd == "intake":
        import intake
        downloader = None
        tok = cfg.get("hf_token_file")
        if args.source.startswith("hf:"):
            from huggingface_hub import snapshot_download
            token = Path(tok).read_text(encoding="utf-8").strip() if tok and \
                Path(tok).is_file() else False
            downloader = functools.partial(snapshot_download, token=token)
        rc, _ = intake.run(args.source, out=str(cfg["intake_out"]),
                           gate_path=cfg.get("gate") or intake.DEFAULT_GATE,
                           root=cfg.get("replay_root") or intake.ROOT, downloader=downloader,
                           store=cfg.get("store"))
        return rc
    return 2


if __name__ == "__main__":
    sys.exit(main())
