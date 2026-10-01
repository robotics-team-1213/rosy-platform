#!/usr/bin/env python3
"""Run on the Ubuntu site host as root: keep the published HTTPS port on the LAN interface.

Docker-published ports are DNAT-forwarded and skip INPUT (and ufw), so the filter lives
in Docker's DOCKER-USER chain. It matches the inbound interface *name*, never an address
or subnet, so the site LAN can change its addresses without a restart or a rule edit.

  site-firewall.py apply --env-file /etc/rosy/site/site.env [--dry-run]
  site-firewall.py check --env-file /etc/rosy/site/site.env

`apply` is idempotent (rosy-site-firewall.service runs it after Docker starts).
`check` changes nothing; rosy-site-stack.service runs it before Compose and refuses to
start when the bind address cannot work or the LAN filter is missing.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import re
import shlex
import socket
import subprocess
import sys
from pathlib import Path

CHAIN = "ROSY-SITE-INGRESS"
PARENT = "DOCKER-USER"
IFACE = re.compile(r"^(?:[A-Za-z0-9_.-]{1,15}|[A-Za-z0-9_.-]{1,14}\+)$")
GUIDE = "see deploy/site/README.md, 'LAN access'"


class ConfigError(ValueError):
    """The site env cannot produce a working, interface-scoped bind."""


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines as Compose's --env-file reads them (comments and blanks skipped)."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def address_assigned(address: str) -> bool:
    """True when this host owns `address` (a bind to it succeeds)."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((address, 0))
        except OSError as error:
            if error.errno == errno.EADDRNOTAVAIL:
                return False
            raise
    return True


def site_plan(env: dict[str, str], *, assigned=address_assigned) -> dict:
    """The bind mode, port and LAN interfaces; ConfigError says why a start would fail."""
    bind = env.get("ROSY_SITE_BIND_ADDRESS", "").strip() or "127.0.0.1"
    try:
        ip = ipaddress.ip_address(bind)
    except ValueError:
        raise ConfigError(f"ROSY_SITE_BIND_ADDRESS={bind!r} is not an IP address; "
                          f"use 127.0.0.1 (local/tunnel) or 0.0.0.0 (LAN); {GUIDE}") from None
    raw_port = env.get("ROSY_SITE_HTTPS_PORT", "").strip() or "8443"
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise ConfigError(f"ROSY_SITE_HTTPS_PORT={raw_port!r} is not a TCP port")
    mode = "loopback" if ip.is_loopback else "wildcard" if ip.is_unspecified else "address"
    if mode == "address" and not assigned(bind):
        raise ConfigError(
            f"ROSY_SITE_BIND_ADDRESS={bind} is not assigned on this host (did the site LAN "
            "change?); Docker would fail with 'cannot assign requested address' and take the "
            "console, cameras, robots and discovery down together. Set "
            f"ROSY_SITE_BIND_ADDRESS=0.0.0.0 and ROSY_SITE_LAN_IFACE=<interface>; {GUIDE}")
    ifaces = [item.strip() for item in env.get("ROSY_SITE_LAN_IFACE", "").split(",")
              if item.strip()]
    bad = [item for item in ifaces if not IFACE.fullmatch(item)]
    if bad:
        raise ConfigError(f"ROSY_SITE_LAN_IFACE has an invalid interface name: {bad[0]!r}")
    if mode != "loopback" and not ifaces:
        raise ConfigError(
            f"ROSY_SITE_BIND_ADDRESS={bind} publishes port {raw_port} beyond loopback, but "
            "ROSY_SITE_LAN_IFACE is empty; name the LAN interface (e.g. wlan0 or eth0) so "
            f"other interfaces are dropped; {GUIDE}")
    return {"bind": bind, "mode": mode, "family": ip.version, "port": int(raw_port),
            "ifaces": ifaces}


def jump_rule(port: int) -> list[str]:
    """Inbound connections DNAT-ed from the published host port (any container port)."""
    return ["-p", "tcp", "-m", "conntrack", "--ctstate", "DNAT", "--ctdir", "ORIGINAL",
            "--ctorigdstport", str(port), "-j", CHAIN]


def chain_rules(ifaces: list[str]) -> list[list[str]]:
    return [["-i", iface, "-j", "RETURN"] for iface in ifaces] + [["-j", "DROP"]]


def chain_listing(ifaces: list[str]) -> list[str]:
    """`iptables -S CHAIN` text for the wanted chain (simple matches print verbatim)."""
    return [f"-N {CHAIN}"] + [f"-A {CHAIN} " + " ".join(rule) for rule in chain_rules(ifaces)]


def fresh_commands(plan: dict) -> list[list[str]]:
    """The full install on a host without our chain; what --dry-run prints."""
    tool = "ip6tables" if plan["family"] == 6 else "iptables"
    commands = [[tool, "-w", "-N", CHAIN], [tool, "-w", "-F", CHAIN]]
    commands += [[tool, "-w", "-A", CHAIN, *rule] for rule in chain_rules(plan["ifaces"])]
    commands.append([tool, "-w", "-I", PARENT, "1", *jump_rule(plan["port"])])
    return commands


def _run(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout


def _port_of(line: str) -> str | None:
    tokens = line.split()
    return tokens[tokens.index("--ctorigdstport") + 1] if "--ctorigdstport" in tokens else None


def _jumps(listing: str) -> list[str]:
    return [line for line in listing.splitlines()
            if line.startswith(f"-A {PARENT} ") and line.split()[-2:] == ["-j", CHAIN]]


def _parent_listing(tool: str, run) -> str:
    code, listing = run([tool, "-w", "-S", PARENT])
    if code != 0:
        raise RuntimeError(f"{tool} has no {PARENT} chain: start Docker first; a Docker "
                           "nftables firewall backend is not supported by this helper")
    return listing


def apply(plan: dict, run=_run) -> list[list[str]]:
    """Make the live rules match the plan; returns the mutating commands it ran."""
    if plan["mode"] == "loopback":
        return []
    tool = "ip6tables" if plan["family"] == 6 else "iptables"
    done = []

    def mutate(*argv: str) -> None:
        command = [tool, "-w", *argv]
        code, _ = run(command)
        if code != 0:
            raise RuntimeError("failed: " + shlex.join(command))
        done.append(command)

    listing = _parent_listing(tool, run)
    code, current = run([tool, "-w", "-S", CHAIN])
    if code != 0:
        mutate("-N", CHAIN)
        current = f"-N {CHAIN}\n"
    if current.splitlines() != chain_listing(plan["ifaces"]):
        mutate("-F", CHAIN)
        for rule in chain_rules(plan["ifaces"]):
            mutate("-A", CHAIN, *rule)
    jumps = _jumps(listing)
    port = str(plan["port"])
    if not any(_port_of(line) == port for line in jumps):
        mutate("-I", PARENT, "1", *jump_rule(plan["port"]))
    kept = False
    for line in jumps:  # a changed port leaves an old jump; drop it and any duplicate
        if _port_of(line) == port and not kept:
            kept = True
            continue
        mutate("-D", *shlex.split(line)[1:])
    return done


def check(plan: dict, run=_run) -> None:
    """Raise unless the live rules already match the plan (changes nothing)."""
    if plan["mode"] == "loopback":
        return
    tool = "ip6tables" if plan["family"] == 6 else "iptables"
    hint = "run: systemctl restart rosy-site-firewall.service"
    listing = _parent_listing(tool, run)
    code, current = run([tool, "-w", "-S", CHAIN])
    if code != 0 or current.splitlines() != chain_listing(plan["ifaces"]):
        raise RuntimeError(f"{CHAIN} does not allow only {','.join(plan['ifaces'])}; {hint}")
    port = str(plan["port"])
    lines, jumps = listing.splitlines(), _jumps(listing)
    jump = next((index for index, line in enumerate(lines)
                 if line in jumps and _port_of(line) == port), None)
    early_return = next((index for index, line in enumerate(lines)
                         if line == f"-A {PARENT} -j RETURN"), None)
    if jump is None or (early_return is not None and early_return < jump):
        raise RuntimeError(f"{PARENT} does not send port {port} to {CHAIN}; {hint}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("apply", "check"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rules a fresh host would get; touch nothing")
    args = parser.parse_args(argv)
    try:
        plan = site_plan(read_env(args.env_file))
    except (ConfigError, OSError) as error:
        print(f"rosy-site preflight: {error}", file=sys.stderr)
        return 2
    if plan["mode"] == "loopback":
        print(f"bind {plan['bind']}:{plan['port']} is loopback-only; no LAN filter needed")
        return 0
    if plan["mode"] == "address":
        print(f"warning: ROSY_SITE_BIND_ADDRESS={plan['bind']} pins the proxy to one "
              "address and breaks when the site LAN changes; prefer 0.0.0.0", file=sys.stderr)
    try:
        if args.dry_run:
            for command in fresh_commands(plan):
                print(shlex.join(command))
        elif args.command == "apply":
            changed = apply(plan)
            print(f"port {plan['port']} allowed only on {','.join(plan['ifaces'])}"
                  f" ({len(changed)} rule change(s))")
        else:
            check(plan)
            print(f"port {plan['port']} is limited to {','.join(plan['ifaces'])}")
    except RuntimeError as error:
        print(f"rosy-site firewall: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
