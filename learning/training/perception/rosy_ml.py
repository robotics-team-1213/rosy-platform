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

The commands wrap model/deliver.py, dataset/harvest.py, dataset/fetch_http.py and model/intake.py;
they add no behaviour of their own. Exit codes are those of the wrapped tool;
doctor exits 0 only if every required check passes, 1 otherwise; 2 is a bad
config or argument. Network failures of deliver/rollback/release-hold/status exit 77
(host name does not resolve), 78 (refused, timed out, no route) or 79 (host key unknown
or changed), see model/deliver.py. status and store-status with --watch-config (or a
`state_file:` in the config) also show each robot's last watcher failure."""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import getpass
import importlib.util
import json
import os
import ipaddress
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (HERE, HERE / "model", HERE / "dataset"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
import slot_cli  # noqa: E402
import store  # noqa: E402

SITE_TOKEN_FILE = "/etc/rosy/site-secrets/hf_token"
STALE_HOLD_H = 24


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _hold_age_h(hold: dict) -> float | None:
    try:
        ts = dt.datetime.strptime(hold["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    return (_utcnow() - ts).total_seconds() / 3600


LEARNED_SITE = "/opt/rosy/learned-perception/site-packages"  # == learned/runner.py
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
    if cfg.get("store") is not None and (not isinstance(cfg["store"], str)
                                         or not cfg["store"].strip()):
        raise ValueError("store: a folder path")
    cfg.setdefault("operator", getpass.getuser())
    cfg.setdefault("intake_out", str(ROOT / "data" / "perception" / "models"))
    return cfg


def load_config(path) -> dict:
    import yaml
    return _check(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def config_from_watch(watch_cfg: dict, hostname: str | None = None, *, selected_robot=None) -> dict:
    """The site watcher's config seen as an operator config (doctor on the site PC)."""
    import peer_targets
    roster = [r for r in watch_cfg['robots'] if selected_robot is None or r['name'] == selected_robot]
    if not roster:
        raise ValueError(f'unknown robot {selected_robot!r}')
    cfg = {"operator": f"site:{hostname or socket.gethostname()}",
           "robots": {r["name"]: peer_targets.resolve(r) for r in roster},
           "ssh": dict(watch_cfg["ssh"]), "intake_out": watch_cfg["intake_out"]}
    if watch_cfg.get("state_file"):
        cfg["state_file"] = watch_cfg["state_file"]
    if watch_cfg.get("backend", "inbox") == "hf":
        cfg["hf_repo"] = watch_cfg["repo"]
        cfg["hf_token_file"] = watch_cfg.get("hf_token_file") or SITE_TOKEN_FILE
    for key in ("store", "replay_root", "gate"):
        if watch_cfg.get(key):
            cfg[key] = watch_cfg[key]
    return _check(cfg)


def _ssh_argv(cfg: dict, name: str) -> list[str]:
    """Key, known_hosts and the host-key alias (the robot id) for one robot."""
    return ["--identity", cfg["ssh"]["identity"], "--known-hosts", cfg["ssh"]["known_hosts"],
            "--host-key-alias", name]


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _known(runner, kh: str, key: str) -> list[str]:
    """The known_hosts lines (marker-free) ssh-keygen finds for key (an alias or a host)."""
    try:
        r = runner(["ssh-keygen", "-F", key, "-f", kh], check=False, capture_output=True,
                   text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    return [ln for ln in (r.stdout or "").splitlines()
            if ln.strip() and not ln.startswith(("#", "@"))]


def _pin_hint(name: str) -> str:
    return f"rosy_ml repin {name}"


def _repin(cfg: dict, name: str, runner) -> int:
    """Copy the host key found under the robot's address to the robot id (explicit; the
    old entry stays). Strict checking is untouched: this only re-labels a key that was
    already pinned."""
    host, kh = _host(cfg, name), cfg["ssh"]["known_hosts"]
    if _known(runner, kh, name):
        print(f"✓ {name}: host key already pinned under {name}")
        return 0
    found = [ln.split(" ", 1)[1] for ln in _known(runner, kh, host) if " " in ln]
    if not found:
        print(f"✗ {name}: no host key pinned for {host!r} in {kh} — fix: record the robot's "
              "key from a trusted network under its id "
              f"(ssh-keyscan -t ed25519 <address> with the address replaced by {name!r})")
        return 1
    path = Path(kh)
    text = path.read_text(encoding="utf-8")
    sep = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + sep + "".join(f"{name} {rest}\n" for rest in found),
                    encoding="utf-8", newline="\n")
    print(f"✓ {name}: pinned {len(found)} host key(s) under {name} (copied from {host!r}; "
          "the old entry is left in place)")
    return 0


def _failure_lines(cfg: dict, robots: list[str]) -> list[str]:
    """The watcher's last network failure per robot, from its state file (if any)."""
    path = cfg.get("state_file")
    if not path or not Path(path).is_file():
        return []
    try:
        failures = json.loads(Path(path).read_text(encoding="utf-8")).get("robot_failures") or {}
    except (OSError, ValueError):
        return [f"! cannot read the watcher state {path}"]
    return [f"✗ {name}: last watcher failure: {f.get('kind')} (exit {f.get('exit')}) at "
            f"{f.get('at')}, {f.get('count')} in a row"
            for name in robots if isinstance(f := failures.get(name), dict)]


def _host(cfg: dict, name: str) -> str:
    try:
        return cfg["robots"][name]
    except KeyError:
        raise ValueError(f"unknown robot {name!r}; configured: {', '.join(cfg['robots'])}")


# --- init -----------------------------------------------------------------------------------

def _init(args, runner=subprocess.run) -> int:
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
    for key in ("store", "hf_repo", "hf_token_file", "intake_out", "core_token_file",
                "core_operator_token_file", "replay_root"):
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
    for name, host in robots.items():
        if _is_ip(host):
            print(f"! {name}: {host} is an IP; it breaks when the network renumbers — "
                  "use the robot's host name (<hostname>.local) instead")
        if not _known(runner, known_hosts, name) and _known(runner, known_hosts, host):
            print(f"! {name}: its host key is pinned under the address only — "
                  f"fix: {_pin_hint(name)}")
    return 0


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


def _writable(folder: Path) -> bool:
    probe = folder / f".rosy_ml-probe-{os.getpid()}"
    probe.write_text("", encoding="utf-8")
    probe.unlink()
    return True


def _doctor_store(rep: _Report, st) -> None:
    root = st.root
    if not rep.check(f"store {root} exists", root.is_dir,
                     "create the folder, or mount the NAS / start Google Drive for desktop; "
                     "the path in your config must be the mounted path"):
        return
    rep.check(f"store {root} is writable", lambda: _writable(root),
              "give your user (or rosy-model-watch on the site PC) write access")
    missing = [str(d.relative_to(root)) for d in st.layout() if not d.is_dir()]
    if missing:
        rep.line(False, f"store layout: missing {', '.join(missing)}",
                 "rosy_ml store-status --init creates them")
        return
    s = st.status()
    rep.line(True, f"store layout; {s['inbox_ready']} ready in the inbox, "
                   f"{s['inbox_waiting']} incomplete (no matching READY)")


def _store_status(cfg: dict, init: bool) -> int:
    for line in _failure_lines(cfg, list(cfg["robots"])):
        print(line)
    if not cfg.get("store"):
        print("✗ no store configured — fix: rosy_ml init --store <path> --force "
              "(or add `store: <path>` to your config)")
        return 2
    st = store.Store(cfg["store"])
    if not st.root.is_dir():
        print(f"✗ store {st.root} does not exist — fix: create or mount it")
        return 1
    if init:
        st.ensure_layout()
    s = st.status()
    print(f"store: {s['root']}")
    print("datasets:" if s["datasets"] else "datasets: none")
    for name, shas in s["datasets"].items():
        for sha in shas:
            print(f"  store:{name}@{sha}")
    for name, shas in s["evalsets"].items():
        for sha in shas:
            print(f"  evalset {name}@{sha}")
    print(f"inbox: {s['inbox_ready']} ready, {s['inbox_waiting']} waiting (no matching READY)")
    print(f"accepted: {s['accepted']}")
    print(f"rejected: {s['rejected']}")
    missing = [str(d.relative_to(st.root)) for d in st.layout() if not d.is_dir()]
    if missing:
        print(f"✗ missing {', '.join(missing)} — fix: rosy_ml store-status --init")
        return 1
    return 0


def _foundation():
    path = ROOT / "contracts" / "foundation"
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _browse_robots():
    """Current `_rosy._tcp` records. Host, port and TLS are whatever the robot advertises."""
    _foundation()
    from core_common import discover
    from core_common.protocol.discovery_txt import ROBOT
    return discover.get_shared_cache().wait(ROBOT, timeout_s=3)


def core_base(configured_host, rows) -> str:
    """CORE origin for one robot.

    ``configured_host`` only picks the advertisement (its `.local` name). The
    scheme, name and port come from that `_rosy._tcp` record: `tls=required`
    uses `tls_host`, anything else uses the advertised host. Nothing here
    fills in a port or an address the advertisement did not carry.
    """
    _foundation()
    from core_common.protocol.discovery_txt import ROBOT, HOSTNAME, Accepted, classify, normalize_host
    wanted = normalize_host(str(configured_host))
    if not HOSTNAME.fullmatch(wanted):
        raise ValueError("fetch selects a robot by its mDNS name (<hostname>.local), "
                         f"not {configured_host!r}")
    chosen = []
    for row in rows:
        accepted = classify(getattr(row, "service_type", ""), getattr(row, "host", None),
                            None, getattr(row, "port", None), list(getattr(row, "txt", ()) or ()))
        if not isinstance(accepted, Accepted) or accepted.service_type != ROBOT or not accepted.host:
            continue
        names = {accepted.host}
        tls_host = accepted.txt.get("tls_host")
        if isinstance(tls_host, str):
            names.add(normalize_host(tls_host))
        if wanted in names:
            chosen.append((accepted, row.port))
    if not chosen:
        raise LookupError(f"no _rosy._tcp advertisement for {wanted}")
    if len(chosen) > 1:
        raise LookupError(f"more than one _rosy._tcp advertisement for {wanted}")
    accepted, port = chosen[0]
    if accepted.txt.get("tls") == "required":
        tls_host = accepted.txt.get("tls_host")
        if not isinstance(tls_host, str) or normalize_host(tls_host) != accepted.host:
            raise LookupError(f"{wanted} advertises tls=required without a matching tls_host")
        return f"https://{normalize_host(tls_host)}:{port}"
    return f"http://{accepted.host}:{port}"


# --- main -----------------------------------------------------------------------------------

def main(argv=None, *, runner=subprocess.run, connect=socket.create_connection,
         find_spec=importlib.util.find_spec, resolve=socket.getaddrinfo,
         discover=None) -> int:
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
    p.add_argument("--store", help="store folder: local path, NAS mount or Drive folder")
    p.add_argument("--hf-repo")
    p.add_argument("--hf-token-file")
    p.add_argument("--intake-out")
    p.add_argument("--core-token-file", help="viewer token file (harvest idle check)")
    p.add_argument("--core-operator-token-file", help="Operator token file (fetch --http)")
    p.add_argument("--replay-root")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("doctor")
    p.add_argument("--backend", choices=("onnx", "ncnn"), default="onnx")
    p.add_argument("robot", nargs="?")
    p.add_argument("--watch-config", help="check the site watcher's config instead")
    p = sub.add_parser("status")
    p.add_argument("robot", nargs="?")
    p.add_argument("--history", type=int, default=10)
    p.add_argument("--task", default="lane_seg")
    p.add_argument("--watch-config", help="read the site watcher's config (and its failures)")
    p = sub.add_parser("repin")
    p.add_argument("robot")
    p.add_argument("--watch-config", help="read the site watcher's config")
    slot_cli.add_parsers(sub)  # deliver, promote, rollback, release-hold (D-423 --task/--slot)
    p = sub.add_parser("harvest")
    p.add_argument("robot")
    p.add_argument("--dest")
    p.add_argument("--assume-idle", action="store_true")
    p = sub.add_parser("fetch", help="D-411: pull Pilot recordings over CORE")
    p.add_argument("robot")
    p.add_argument("--http", action="store_true", required=True,
                   help="CORE archive; the SSH path stays `harvest`")
    p.add_argument("--dest")
    p.add_argument("--video-out")
    p.add_argument("--only", help="one recording id")
    p.add_argument("--ca-file", help="device CA; required when the advertisement says tls=required")
    sub.add_parser("intake").add_argument("source")
    p = sub.add_parser("store-status")
    p.add_argument("--init", action="store_true", help="create the layout folders")
    p.add_argument("--watch-config", help="read the site watcher's config (and its failures)")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        return _init(args, runner)
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
