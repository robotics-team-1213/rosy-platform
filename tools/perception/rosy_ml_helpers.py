"""Configuration, SSH host-key repinning, store status, discovery, and CLI parser for rosy_ml."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
for _p in (
    HERE,
    ROOT / "learning/registry/perception",
    ROOT / "learning/curation/perception",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
import slot_cli  # noqa: E402
import store  # noqa: E402

SITE_TOKEN_FILE = "/etc/rosy/site-secrets/hf_token"
STALE_HOLD_H = 24
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


# --- init & store ---------------------------------------------------------------------------

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


def _writable(folder: Path) -> bool:
    probe = folder / f".rosy_ml-probe-{os.getpid()}"
    probe.write_text("", encoding="utf-8")
    probe.unlink()
    return True


def _doctor_store(rep, st) -> None:
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


def build_parser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rosy_ml", description=description)
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
    p = sub.add_parser("fitness", help="D-666: offline paired road diagnostics, always HOLD")
    p.add_argument("model")
    for option in ("store", "road-eval", "region-eval", "inputs", "out"):
        p.add_argument("--" + option, required=True)
    p.add_argument("--max-age-ns", required=True, type=int)
    p = sub.add_parser('object-fitness', help='D-682: offline fixed object diagnostics, always HOLD')
    p.add_argument('model')
    for option in ('store', 'eval', 'inputs', 'out'):
        p.add_argument('--' + option, required=True)
    p.add_argument('--max-age-ns', required=True, type=int)
    p = sub.add_parser('observe', help='D-673: truth-free road observation artifact, always HOLD')
    p.add_argument('model')
    for option in ('inputs', 'out'):
        p.add_argument('--' + option, required=True)
    p.add_argument('--max-age-ns', required=True, type=int)
    p = sub.add_parser("store-status")
    p.add_argument("--init", action="store_true", help="create the layout folders")
    p.add_argument("--watch-config", help="read the site watcher's config (and its failures)")
    return ap
