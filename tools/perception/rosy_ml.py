"""rosy_ml: the operator CLI for the learned-perception loop (D-373 decision 7).

  rosy_ml init --robot NAME=HOST [...]   write your per-user config (paths only)
  rosy_ml doctor [ROBOT]                 check key, known_hosts, robot, sudo, runtime
  rosy_ml status [ROBOT]                 shadow pointer, installed revisions, history
  rosy_ml deliver ROBOT REVISION         push an intake-passed model to the shadow slot (holds the robot)
  rosy_ml rollback ROBOT                 back to shadow.previous (holds the robot)
  rosy_ml release-hold ROBOT             remove the hold: site auto delivery resumes
  rosy_ml harvest ROBOT                  pull finished recordings (only while idle)
  rosy_ml intake SOURCE                  check a model folder or hf:org/repo@<sha>

Config: ROSY_ML_CONFIG, else %APPDATA%\\Rosy\\ml.yaml (Windows) or
$XDG_CONFIG_HOME/rosy/ml.yaml, ~/.config/rosy/ml.yaml. It names robots, key
and known_hosts paths, the HF repo, and token *files*; never a token itself.
Robots are addressed by name; the host lives only in your config.

The commands wrap model/deliver.py, dataset/harvest.py and model/intake.py;
they add no behaviour of their own. Exit codes are those of the wrapped tool;
doctor exits 0 only if every required check passes, 1 otherwise; 2 is a bad
config or argument."""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import getpass
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (HERE, HERE / "model", HERE / "dataset"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402

SITE_TOKEN_FILE = "/etc/rosy/site/secrets/hf_token"
STALE_HOLD_H = 24


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _hold_age_h(hold: dict) -> float | None:
    try:
        ts = dt.datetime.strptime(hold["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    return (_utcnow() - ts).total_seconds() / 3600
MODELS_DIR, MODELS_OWNER = "/var/lib/rosy/models", "root:rosy-camera 750"


# --- config ---------------------------------------------------------------------------------

def config_path(env=None, platform=None) -> Path:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if env.get("ROSY_ML_CONFIG"):
        return Path(env["ROSY_ML_CONFIG"])
    if platform == "win32":
        return Path(env.get("APPDATA") or Path.home()) / "Rosy" / "ml.yaml"
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "rosy" / "ml.yaml"


def _inline_secrets(node, path="") -> list[str]:
    """Keys anywhere in the config that look like a secret value, not a file path."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            where = f"{path}.{key}" if path else str(key)
            if any(w in str(key).lower() for w in ("token", "secret", "password")) \
                    and not str(key).endswith("_file"):
                found.append(where)
            found += _inline_secrets(value, where)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _inline_secrets(value, f"{path}[{i}]")
    return found


def _check(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError("config must be a mapping")
    inline = _inline_secrets(cfg)
    if inline:
        raise ValueError(f"{inline[0]}: put secrets in a file and name it as *_file")
    robots = cfg.get("robots")
    if not isinstance(robots, dict) or not robots:
        raise ValueError("robots: at least one NAME: HOST")
    for name, host in robots.items():
        if not (operator_ssh.safe_name(name) and operator_ssh.safe_name(host)):
            raise ValueError(f"robots: unsafe entry {name!r}: {host!r}")
    ssh = cfg.get("ssh") or {}
    if not ssh.get("identity") or not ssh.get("known_hosts"):
        raise ValueError("ssh.identity and ssh.known_hosts are required")
    cfg.setdefault("operator", getpass.getuser())
    cfg.setdefault("intake_out", str(ROOT / "data" / "perception" / "models"))
    return cfg


def load_config(path) -> dict:
    import yaml
    return _check(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def config_from_watch(watch_cfg: dict, hostname: str | None = None) -> dict:
    """The site watcher's config seen as an operator config (doctor on the site PC)."""
    cfg = {"operator": f"site:{hostname or socket.gethostname()}",
           "robots": {r["name"]: r["host"] for r in watch_cfg["robots"]},
           "ssh": dict(watch_cfg["ssh"]), "hf_repo": watch_cfg["repo"],
           "hf_token_file": watch_cfg.get("hf_token_file") or SITE_TOKEN_FILE,
           "intake_out": watch_cfg["intake_out"]}
    if watch_cfg.get("replay_root"):
        cfg["replay_root"] = watch_cfg["replay_root"]
    return _check(cfg)


def _ssh_argv(cfg: dict) -> list[str]:
    return ["--identity", cfg["ssh"]["identity"], "--known-hosts", cfg["ssh"]["known_hosts"]]


def _host(cfg: dict, name: str) -> str:
    try:
        return cfg["robots"][name]
    except KeyError:
        raise ValueError(f"unknown robot {name!r}; configured: {', '.join(cfg['robots'])}")


# --- init -----------------------------------------------------------------------------------

def _init(args) -> int:
    import yaml
    path = config_path()
    if path.exists() and not args.force:
        print(f"refused: {path} exists (use --force to overwrite)", file=sys.stderr)
        return 2
    robots = {}
    for item in args.robot or []:
        name, sep, host = item.partition("=")
        if not sep:
            print(f"refused: --robot NAME=HOST, got {item!r}", file=sys.stderr)
            return 2
        robots[name] = host
    try:
        identity, known_hosts = operator_ssh.resolve(args.identity, args.known_hosts)
    except operator_ssh.SshConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    cfg = {"operator": args.operator or getpass.getuser(), "robots": robots,
           "ssh": {"identity": identity, "known_hosts": known_hosts}}
    for key in ("hf_repo", "hf_token_file", "intake_out", "core_token_file", "replay_root"):
        if getattr(args, key):
            cfg[key] = getattr(args, key)
    try:
        _check(dict(cfg))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"wrote {path}; next: rosy_ml doctor")
    return 0


# --- doctor ---------------------------------------------------------------------------------

def _replay_clip_count(cfg: dict) -> int | None:
    try:
        import intake
    except ImportError:
        return None
    gate = intake.load_gate(cfg.get("gate") or intake.DEFAULT_GATE)
    return len(intake.replay_videos(gate, cfg.get("replay_root") or intake.ROOT))


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


def _doctor(cfg, robots, runner, connect, find_spec) -> int:
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
    opts = operator_ssh.options(str(key), kh)

    def remote(host, command, timeout=20):
        try:
            return runner(["ssh", *opts, "--", f"rosy@{host}", command], check=False,
                          capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess([], 1, "", str(exc))

    def in_known_hosts(host):
        try:
            return runner(["ssh-keygen", "-F", host, "-f", kh], check=False,
                          capture_output=True, text=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return Path(kh).is_file() and host in Path(kh).read_text(encoding="utf-8")

    def tcp22(host):
        try:
            connect((host, 22), timeout=3).close()
        except OSError:
            return False
        return True

    for name in robots:
        host = cfg["robots"][name]
        rep.check(f"{name}: {host} in known_hosts", lambda: in_known_hosts(host),
                  f"record the robot's host key once from a trusted network into {kh} "
                  "(see .claude/skills/rosy-device-access/SKILL.md)")
        reachable = rep.check(f"{name}: TCP 22 reachable", lambda: tcp22(host),
                              "robot off, wrong address in your config, or not on this network")
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
            ("robot python3 imports onnxruntime",
             "cd / && PYTHONNOUSERSITE=1 python3 -c 'import onnxruntime'",
             lambda r: r.returncode == 0,
             "install the pinned onnxruntime (install-learned-perception.sh) or reflash"),
        ]
        for label, command, good, hint in checks:
            if not reachable:
                rep.line(False, f"{name}: {label} (skipped: not reachable)")
                continue
            rep.check(f"{name}: {label}", lambda: good(remote(host, command)), hint)
        if reachable:
            try:
                text = remote(host, f"sudo -n cat {MODELS_DIR}/hold 2>/dev/null || true").stdout
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

    if cfg.get("hf_repo"):
        tok = cfg.get("hf_token_file")
        if tok:
            rep.check(f"HF token file {tok} for {cfg['hf_repo']}", lambda: Path(tok).is_file(),
                      "put a read-only HF token in that file (never inline in the config)")
        else:
            rep.line(False, f"no hf_token_file for {cfg['hf_repo']}",
                     "fine for a public repo; a private one needs hf_token_file",
                     required=False)
        rep.check("replay clips for intake", lambda: _replay_clip_count(cfg),
                  "copy data/teleop/learning/*.mp4 under replay_root (or the repo root); "
                  "without clips every intake stops as a setup error")
    rep.check("local onnxruntime importable", lambda: find_spec("onnxruntime") is not None,
              "needed for rosy_ml intake only: pip install onnxruntime in your venv",
              required=False)
    return 1 if rep.failed else 0


# --- main -----------------------------------------------------------------------------------

def main(argv=None, *, runner=subprocess.run, connect=socket.create_connection,
         find_spec=importlib.util.find_spec) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="rosy_ml", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--operator")
    p.add_argument("--robot", action="append", metavar="NAME=HOST")
    p.add_argument("--identity")
    p.add_argument("--known-hosts")
    p.add_argument("--hf-repo")
    p.add_argument("--hf-token-file")
    p.add_argument("--intake-out")
    p.add_argument("--core-token-file")
    p.add_argument("--replay-root")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("doctor")
    p.add_argument("robot", nargs="?")
    p.add_argument("--watch-config", help="check the site watcher's config instead")
    p = sub.add_parser("status")
    p.add_argument("robot", nargs="?")
    p.add_argument("--history", type=int, default=10)
    p = sub.add_parser("deliver")
    p.add_argument("robot")
    p.add_argument("revision")
    for name in ("rollback", "release-hold"):
        sub.add_parser(name).add_argument("robot")
    p = sub.add_parser("harvest")
    p.add_argument("robot")
    p.add_argument("--dest")
    p.add_argument("--assume-idle", action="store_true")
    sub.add_parser("intake").add_argument("source")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return _init(args)
    try:
        if args.cmd == "doctor" and args.watch_config:
            import watch
            cfg = config_from_watch(watch.load_config(args.watch_config))
        else:
            path = config_path()
            if not path.exists():
                print(f"✗ no config at {path} — fix: run rosy_ml init")
                return 1 if args.cmd == "doctor" else 2
            cfg = load_config(path)
        robots = [args.robot] if getattr(args, "robot", None) else list(cfg["robots"])
        hosts = [_host(cfg, r) for r in robots]
    except (OSError, ValueError) as exc:
        print(f"✗ config — fix: {exc}")
        return 2
    if args.cmd == "doctor":
        return _doctor(cfg, robots, runner, connect, find_spec)
    ssh = _ssh_argv(cfg)
    if args.cmd in ("status", "deliver", "rollback", "release-hold"):
        import deliver
        if args.cmd == "status":
            rc = 0
            for name, host in zip(robots, hosts):
                print(f"== {name}")
                rc = max(rc, deliver.main(["status", host, *ssh, "--history",
                                           str(args.history)], runner=runner))
            return rc
        head = (["push", hosts[0], args.revision, "--models", str(cfg["intake_out"])]
                if args.cmd == "deliver" else [args.cmd, hosts[0]])
        return deliver.main([*head, *ssh, "--operator", cfg["operator"]], runner=runner)
    if args.cmd == "harvest":
        import harvest
        argv = [hosts[0], *ssh]
        if cfg.get("core_token_file"):
            argv += ["--core-token-file", cfg["core_token_file"]]
        if args.dest:
            argv += ["--dest", args.dest]
        if args.assume_idle:
            argv.append("--assume-idle")
        return harvest.main(argv)
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
                           root=cfg.get("replay_root") or intake.ROOT, downloader=downloader)
        return rc
    return 2


if __name__ == "__main__":
    sys.exit(main())
