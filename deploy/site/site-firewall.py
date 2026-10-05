#!/usr/bin/env python3
"""Run on the Ubuntu site host as root: keep the published HTTPS port on the LAN interface.

The filter sits in mangle PREROUTING, ahead of Docker's DNAT, where the published host
port is still the destination port. Its own chain returns loopback and the named LAN
interfaces and drops every other packet addressed to this host. It matches interface
*names*, never an address or subnet, so the site LAN can renumber without an edit.

  site-firewall.py apply [--dry-run]     # rosy-site-firewall.service, before Docker
  site-firewall.py check [--verify-certs] # stack preflight and the periodic check timer

The bind address, port, LAN interfaces and tls_host come from `docker compose config`,
so this script reads site.env exactly as Compose does.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import re
import shlex
import socket
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

CHAIN = "ROSY-SITE-INGRESS"
TABLE = "mangle"
HOOK = "PREROUTING"
KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")
IFACE = re.compile(r"^(?:[A-Za-z0-9_.-]{1,15}|[A-Za-z0-9_.-]{1,14}\+)$")
GUIDE = "see deploy/site/README.md, 'LAN access'"
DEFAULT_ENV = Path("/etc/rosy/site/site.env")
DEFAULT_COMPOSE = Path("/opt/rosy/candidate/deploy/site/compose.yaml")
DEFAULT_PUBLIC_ENV = Path("/run/rosy-site/site-public.env")


class ConfigError(ValueError):
    """The site env cannot produce a working, interface-scoped bind (exit 2)."""


def check_env_keys(path: Path) -> dict[str, str]:
    """Backstop: only plain KEY=VALUE lines, so systemd and Compose read the same file.

    Returns the values as systemd's EnvironmentFile= reads them (a matching quote pair is
    syntax). Only the D-341 pairing keys are used from it, as systemd hands them to the stack
    and advertise units; everything else comes from Compose.
    """
    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if not KEY.fullmatch(key):
            raise ConfigError(f"{path}:{number}: {stripped!r} is not a plain KEY=VALUE line "
                              "(no 'export', spaces or lowercase in the key)")
        value = stripped.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def overlay_files(env: dict[str, str]) -> list[str]:
    """The extra `-f <file>` words rosy-site-stack.service appends ($ROSY_SITE_PAIRING_COMPOSE)."""
    words = env.get("ROSY_SITE_PAIRING_COMPOSE", "").split()
    if len(words) % 2 or any(flag != "-f" for flag in words[::2]):
        raise ConfigError("ROSY_SITE_PAIRING_COMPOSE must be empty or `-f <compose file>` pairs, "
                          f"not {' '.join(words)!r}")
    return words


def compose_config(env_file: Path, compose_file: Path, project: str, run,
                   overlay: list[str] | None = None) -> dict:
    """`docker compose config` over the same -f files the stack unit passes (base + overlay)."""
    code, out, err = run(["docker", "compose", "--project-name", project, "--env-file",
                          str(env_file), "-f", str(compose_file), *(overlay or []),
                          "config", "--format", "json"])
    if code != 0:
        raise ConfigError(f"docker compose config failed: {err.strip() or out.strip()}")
    return json.loads(out)


def compose_settings(config: dict) -> dict:
    """The proxy's published binding and the site values, as Compose resolved them.

    The container listens on the published port. Both sides are ROSY_SITE_HTTPS_PORT.
    """
    ports = [entry for entry in config["services"]["proxy"].get("ports", [])
             if entry.get("protocol", "tcp") == "tcp" and entry.get("mode", "ingress") == "ingress"]
    if len(ports) != 1:
        raise ConfigError("the proxy must publish exactly one TCP port")
    try:
        published = int(ports[0]["published"])
        target = int(ports[0]["target"])
    except (KeyError, TypeError, ValueError):
        raise ConfigError("the proxy publish must name a numeric host port and container port") from None
    if published != target:
        raise ConfigError(
            f"the proxy container listens on {target}, but the published port is {published}; "
            "both must be ROSY_SITE_HTTPS_PORT")
    extension = config.get("x-rosy-site") or {}
    secrets = config.get("secrets") or {}
    profile = extension.get('camera_peer_profile')
    if profile not in (None, 'rosy.camera-peer/1'):
        raise ConfigError('unsupported configured camera peer profile')
    command = config.get('services', {}).get('fleet', {}).get('command', [])
    required = ('--pairing-ca','--pairing-tls-host','--tls-cert','--tls-key',
                '--users-file','--tasks-db','--pairing-sync-token-env')
    if profile is not None:
        if not isinstance(command, list) or not all(isinstance(word,str) for word in command):
            raise ConfigError('camera peer profile requires the resolved Fleet command')
        for flag in required:
            if command.count(flag) != 1 or command.index(flag)+1 >= len(command) or not command[command.index(flag)+1] or command[command.index(flag)+1].startswith('--'):
                raise ConfigError('camera peer profile requires complete receiver pairing configuration')
    return {"bind": ports[0].get("host_ip") or "", "port": int(ports[0]["published"]),
            'camera_peer': '1' if profile is not None else '0',
            "lan_iface": extension.get("lan_iface") or "",
            "allow_literal_bind": extension.get("allow_literal_bind") == "1",
            "tls_host": extension.get("tls_host") or "",
            "secrets": {name: secrets[name]["file"] for name in ("site_cert", "site_key", "site_ca")
                        if name in secrets}}


def address_assigned(address: str) -> bool:
    """True when this host owns `address` (a bind to it succeeds)."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((address, 0))
        except OSError as error:
            if error.errno == errno.EADDRNOTAVAIL:
                return False
            raise ConfigError(f"cannot tell whether ROSY_SITE_BIND_ADDRESS={address} is "
                              f"assigned on this host: {error}") from None
    return True


def iface_exists(name: str) -> bool:
    return Path("/sys/class/net", name).exists()


def site_plan(settings: dict, *, assigned=address_assigned, exists=iface_exists) -> dict:
    """Mode, port and interfaces; ConfigError says why a start would fail."""
    bind, port = settings["bind"], settings["port"]
    if not bind:
        raise ConfigError("the proxy would publish on every IPv4 and IPv6 address; set "
                          f"ROSY_SITE_BIND_ADDRESS to 127.0.0.1 or 0.0.0.0; {GUIDE}")
    try:
        ip = ipaddress.ip_address(bind)
    except ValueError:
        raise ConfigError(f"ROSY_SITE_BIND_ADDRESS={bind!r} is not an IP address; "
                          f"use 127.0.0.1 (local/tunnel) or 0.0.0.0 (LAN); {GUIDE}") from None
    if ip.version == 6 and not ip.is_loopback:
        raise ConfigError(f"ROSY_SITE_BIND_ADDRESS={bind} is not supported: the LAN filter and "
                          f"robot discovery are IPv4; use 0.0.0.0; {GUIDE}")
    mode = "loopback" if ip.is_loopback else "wildcard" if ip.is_unspecified else "address"
    if mode == "address":
        if not assigned(bind):
            raise ConfigError(
                f"ROSY_SITE_BIND_ADDRESS={bind} is not assigned on this host (did the site LAN "
                "change?); Docker would fail with 'cannot assign requested address' and take the "
                "console, cameras, robots and discovery down together. Set "
                f"ROSY_SITE_BIND_ADDRESS=0.0.0.0 and ROSY_SITE_LAN_IFACE=<interface>; {GUIDE}")
        if not settings["allow_literal_bind"]:
            raise ConfigError(
                f"ROSY_SITE_BIND_ADDRESS={bind} pins the proxy to one LAN address: it breaks when "
                "the site LAN changes and the discovery bridge cannot reach it on loopback. Use "
                f"0.0.0.0, or set ROSY_SITE_ALLOW_LITERAL_BIND=1 to accept that; {GUIDE}")
    ifaces = [item.strip() for item in settings["lan_iface"].split(",") if item.strip()]
    bad = [item for item in ifaces if not IFACE.fullmatch(item) or item == "lo"]
    if bad:
        raise ConfigError(f"ROSY_SITE_LAN_IFACE has an invalid interface name: {bad[0]!r}")
    if mode != "loopback" and not ifaces:
        raise ConfigError(
            f"ROSY_SITE_BIND_ADDRESS={bind} publishes port {port} beyond loopback, but "
            "ROSY_SITE_LAN_IFACE is empty; name the LAN interface (e.g. wlan0, eth0, or br0 "
            f"for a bridged LAN) so other interfaces are dropped; {GUIDE}")
    warnings = [f"interface {name} does not exist now; the filter still admits it by name "
                "(a bridged LAN needs the bridge name, e.g. br0)"
                for name in ifaces if not name.endswith("+") and not exists(name)]
    return {"bind": bind, "mode": mode, "port": port, "ifaces": ifaces, "warnings": warnings}


def chain_rules(ifaces: list[str]) -> list[list[str]]:
    """Loopback (the discovery bridge) and the LAN pass; anything else to this host drops.

    After that, only container-to-container traffic on Docker bridges (br_netfilter) passes;
    a packet routed straight to a container IP from any other interface drops too.
    """
    return ([["-i", name, "-j", "RETURN"] for name in ["lo", *ifaces]]
            + [["-m", "addrtype", "--dst-type", "LOCAL", "-j", "DROP"],
               ["-i", "br+", "-j", "RETURN"], ["-i", "docker0", "-j", "RETURN"], ["-j", "DROP"]])


def chain_listing(ifaces: list[str]) -> list[str]:
    """`iptables -t mangle -S CHAIN` text for the wanted chain."""
    return [f"-N {CHAIN}"] + [f"-A {CHAIN} " + " ".join(rule) for rule in chain_rules(ifaces)]


def restore_payload(ifaces: list[str]) -> str:
    """One iptables-restore --noflush transaction; declaring the chain flushes it atomically."""
    lines = [f"*{TABLE}", f":{CHAIN} - [0:0]"]
    lines += [f"-A {CHAIN} " + " ".join(rule) for rule in chain_rules(ifaces)]
    return "\n".join([*lines, "COMMIT", ""])


def jump_rules(port: int) -> dict[tuple[str, bool], list[str]]:
    """One jump for the published port. The proxy listens on that same port.

    A packet to the host and a packet routed straight to the container IP share this
    destination port, so one rule covers both. A jump for any other port is not wanted.
    """
    return {(str(port), False): ["-p", "tcp", "--dport", str(port), "-j", CHAIN]}


def _run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(argv, input=stdin, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def _key(line: str) -> tuple[str | None, bool]:
    tokens = line.split()
    port = tokens[tokens.index("--dport") + 1] if "--dport" in tokens else None
    return port, "--dst-type" in tokens


def _jumps(listing: str) -> list[str]:
    return [line for line in listing.splitlines()
            if line.startswith(f"-A {HOOK} ") and line.split()[-2:] == ["-j", CHAIN]]


def _hook_listing(run) -> str:
    code, listing, err = run(["iptables", "-w", "-t", TABLE, "-S", HOOK])
    if code != 0:
        raise RuntimeError(f"cannot read {TABLE} {HOOK}: {err.strip()}")
    return listing


def apply(plan: dict, run=_run) -> list[str]:
    """Make the live rules match the plan; returns the changes it made."""
    if plan["mode"] == "loopback":
        return []
    done = []
    code, current, _ = run(["iptables", "-w", "-t", TABLE, "-S", CHAIN])
    if code != 0 or current.splitlines() != chain_listing(plan["ifaces"]):
        code, _, err = run(["iptables-restore", "-w", "--noflush"], restore_payload(plan["ifaces"]))
        if code != 0:
            raise RuntimeError(f"iptables-restore failed: {err.strip()}")
        done.append("iptables-restore -w --noflush")

    def mutate(*argv: str) -> None:
        command = ["iptables", "-w", "-t", TABLE, *argv]
        code, _, err = run(command)
        if code != 0:
            raise RuntimeError(f"failed: {shlex.join(command)}: {err.strip()}")
        done.append(shlex.join(command))

    jumps, wanted = _jumps(_hook_listing(run)), jump_rules(plan["port"])
    present = {_key(line) for line in jumps}
    for key, rule in wanted.items():  # new jumps first, so no gap opens while old ones go
        if key not in present:
            mutate("-I", HOOK, "1", *rule)
    kept = set()
    for line in jumps:  # a changed port leaves an old jump; drop it and any duplicate
        if _key(line) in wanted and _key(line) not in kept:
            kept.add(_key(line))
            continue
        mutate("-D", *shlex.split(line)[1:])
    return done


def check(plan: dict, run=_run) -> None:
    """Raise unless the live rules already match the plan (changes nothing)."""
    if plan["mode"] == "loopback":
        return
    hint = "run: systemctl restart rosy-site-firewall.service"
    code, current, _ = run(["iptables", "-w", "-t", TABLE, "-S", CHAIN])
    if code != 0 or current.splitlines() != chain_listing(plan["ifaces"]):
        raise RuntimeError(f"{CHAIN} does not admit only lo,{','.join(plan['ifaces'])}; {hint}")
    lines = _hook_listing(run).splitlines()
    jumps = _jumps("\n".join(lines))
    bypass = next((index for index, line in enumerate(lines)
                   if line in (f"-A {HOOK} -j ACCEPT", f"-A {HOOK} -j RETURN")), None)
    for key in jump_rules(plan["port"]):
        jump = next((index for index, line in enumerate(lines)
                     if line in jumps and _key(line) == key), None)
        if jump is None or (bypass is not None and bypass < jump):
            raise RuntimeError(f"{TABLE} {HOOK} does not send port {key[0]} to {CHAIN}; {hint}")


def docker_engine_warning(run=_run) -> str | None:
    """Docker < 28 accepts packets routed straight to container IPs; warn when it can be read."""
    code, out, _ = run(["docker", "version", "--format", "{{.Server.Version}}"])
    major = out.strip().split(".", 1)[0]
    if code != 0 or not major.isdigit():
        return None  # dockerd not up (e.g. before docker.service); nothing to read
    if int(major) < 28:
        return (f"Docker Engine {out.strip()} is older than 28; upgrade (README 'LAN access'): "
                "older engines accept traffic routed directly to container addresses")
    return None


def verify_site_certificate(cert: Path, key: Path, ca: Path, tls_host: str) -> None:
    """In-memory TLS handshake with VERIFY_X509_STRICT, as the bridge and phones verify."""
    if not tls_host:
        raise ConfigError("ROSY_SITE_TLS_HOST is empty; it must be the certificate DNS name")
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(str(cert), str(key))
    client = ssl.create_default_context(cafile=str(ca))
    client.verify_flags |= ssl.VERIFY_X509_STRICT
    pipes = [ssl.MemoryBIO() for _ in range(4)]
    tls_client = client.wrap_bio(pipes[0], pipes[1], server_hostname=tls_host)
    tls_server = server.wrap_bio(pipes[2], pipes[3], server_side=True)
    done = {"client": False, "server": False}
    for _ in range(10):
        for name, side in (("client", tls_client), ("server", tls_server)):
            if done[name]:
                continue
            try:
                side.do_handshake()
                done[name] = True
            except ssl.SSLWantReadError:
                pass
            except ssl.SSLCertVerificationError as error:
                raise ConfigError(f"site certificate fails strict verification for {tls_host}: "
                                  f"{error.verify_message}; see deploy/site/README.md, "
                                  "'Site certificate profile'") from None
            except ssl.SSLError as error:
                if name == "client":
                    raise ConfigError(f"site TLS handshake failed: {error}") from None
                done[name] = True  # the server sees the client's alert; the client decides
        pipes[2].write(pipes[1].read())
        pipes[0].write(pipes[3].read())
        if done["client"]:
            return
    raise ConfigError("site certificate check did not complete")


def write_public_env(settings: dict, path: Path) -> None:
    """The public values the host units need (bridge, advertisers), as Compose resolved them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"ROSY_SITE_TLS_HOST={settings['tls_host']}\nROSY_SITE_HTTPS_PORT={settings['port']}\n"
            f"ROSY_SITE_PAIRING={settings.get('pairing', '0')}\n"
            f"ROSY_SITE_CAMERA_PEER={settings.get('camera_peer', '0') if settings.get('pairing') == '1' else '0'}\n")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as out:
        out.write(text)
    Path(out.name).chmod(0o644)
    Path(out.name).replace(path)


def main(argv: list[str] | None = None, run=_run) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("apply", "check"))
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--project-name", default="rosy-site")
    parser.add_argument("--public-env", type=Path, default=DEFAULT_PUBLIC_ENV,
                        help="apply writes ROSY_SITE_TLS_HOST and ROSY_SITE_HTTPS_PORT here")
    parser.add_argument("--dry-run", action="store_true",
                        help="apply: print the iptables-restore payload and the jump; touch nothing")
    parser.add_argument("--verify-certs", action="store_true",
                        help="check: also verify the site certificate strictly against tls_host")
    args = parser.parse_args(argv)
    try:
        env = check_env_keys(args.env_file)
        settings = compose_settings(compose_config(args.env_file, args.compose_file,
                                                   args.project_name, run, overlay_files(env)))
        settings["pairing"] = "1" if env.get("ROSY_SITE_PAIRING") == "1" else "0"
        plan = site_plan(settings)
        if args.command == "check" and args.verify_certs:
            secrets = settings["secrets"]
            verify_site_certificate(Path(secrets["site_cert"]), Path(secrets["site_key"]),
                                    Path(secrets["site_ca"]), settings["tls_host"])
    except (ConfigError, OSError, KeyError, ValueError) as error:
        print(f"rosy-site preflight: {error}", file=sys.stderr)
        return 2
    warnings = list(plan["warnings"])
    if args.command == "check" and plan["mode"] != "loopback":
        warnings += [text for text in [docker_engine_warning(run)] if text]
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    try:
        if args.dry_run:
            if plan["mode"] == "loopback":
                print(f"# bind {plan['bind']}:{plan['port']} is loopback-only; no LAN filter")
            else:
                print("# iptables-restore -w --noflush <<EOF")
                print(restore_payload(plan["ifaces"]) + "# EOF")
                for rule in jump_rules(plan["port"]).values():
                    print(shlex.join(["iptables", "-w", "-t", TABLE, "-I", HOOK, "1", *rule]))
        elif args.command == "apply":
            changed = apply(plan, run)
            write_public_env(settings, args.public_env)
            where = "loopback only" if plan["mode"] == "loopback" else ",".join(plan["ifaces"])
            print(f"port {plan['port']}: {where} ({len(changed)} change(s))")
        else:
            check(plan, run)
            print(f"port {plan['port']} is limited to "
                  f"{'loopback' if plan['mode'] == 'loopback' else ','.join(plan['ifaces'])}")
    except (RuntimeError, OSError) as error:
        print(f"rosy-site firewall: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
