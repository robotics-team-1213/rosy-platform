#!/usr/bin/env python3
"""Check that this host's control units attach to their peers through mDNS (2026-11-17).

Why: after R and CELL-A moved to separate PCs the peer links stayed broken for 8 days with
nothing logged. Rule: every ROSY host advertises <name>.local and units reach each other by
those names, so the check follows the same path a unit does.

  control_unit_check.py [--config /etc/rosy/control-unit/<unit>/control-unit.yaml ...] [--json]

Per config: avahi-daemon is active and this host's <name>.local resolves to one of its own
addresses; per peer: the url host is a .local name, it resolves, TCP connects, TLS verifies
against tls_ca_file for that name, /healthz is 200, and the authenticated overview shows the
same config_revision (and manifest_digest when both sides know it). One result per line
{unit, peer, ok, step, detail}; exit 0 only when every line is ok. Tokens are never printed.
Needs python3 + PyYAML (python3-yaml, present on Ubuntu Server); runs as root so it can read
the private unit directory. Paths inside a config are relative to the config's folder.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

OVERVIEW = "/api/fleet/control-unit/overview"


def fail(step: str, detail: str) -> tuple[bool, str, str]:
    return False, step, detail


def resolve(name: str) -> list[str]:
    """IPv4/IPv6 addresses libc (nss-mdns) gives for name; the same lookup a unit does."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror:
        return []


def local_addresses() -> set[str]:
    out = subprocess.run(["ip", "-o", "addr"], capture_output=True, text=True, timeout=10).stdout
    return {m.group(1) for m in re.finditer(r"inet6? ([0-9a-fA-F.:]+)(?:%\S+)?/", out)}


def advertised_name(conf: Path = Path("/etc/avahi/avahi-daemon.conf")) -> str:
    """The avahi host-name (what <name>.local means), not the OS hostname: R runs as rosy-fleet-r-computer."""
    try:
        match = re.search(r"^\s*host-name\s*=\s*(\S+)", conf.read_text(encoding="utf-8"), re.M)
    except OSError:
        match = None
    return match.group(1) if match else socket.gethostname().split(".")[0]


def avahi_active() -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", "avahi-daemon"], timeout=10).returncode == 0


def host_check(name: str, active=avahi_active, lookup=resolve, local=local_addresses):
    """(a): avahi runs and <name>.local resolves to an address of this host."""
    if not active():
        return fail("avahi", "avahi-daemon is not active")
    addresses = lookup(f"{name}.local")
    if not addresses:
        return fail("self-resolve", f"{name}.local does not resolve on this host")
    if not set(addresses) & local():
        return fail("self-resolve", f"{name}.local resolves to {','.join(addresses)}, none is an address of this host")
    return True, "self-resolve", f"{name}.local resolves to this host"


def manifest_digest(manifest: dict) -> str:
    """Same canonical form as control_unit_config.ControlTopology.from_mapping."""
    units = [{"id": u["id"], "parent": u.get("parent"), "resources": sorted(u.get("resources") or [])}
             for u in sorted(manifest["units"], key=lambda u: u["id"])]
    canonical = {"revision": manifest["revision"], "units": units}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get(host: str, port: int, ctx: ssl.SSLContext, path: str, token: str | None, timeout: float):
    conn = http.client.HTTPSConnection(host, port, context=ctx, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}"} if token else {})
        resp = conn.getresponse()
        return resp.status, resp.read(131072)
    finally:
        conn.close()


PARENT_CLOSED = b"CONTROL_UNIT_PARENT_INFORMATION_NOT_ENABLED"


def peer_check(url: str, token_file: Path, ca_file: Path, revision: str, digest: str | None,
               lookup=resolve, timeout: float = 5.0, request=get, is_parent: bool = False):
    """(b): one peer, stopping at the first failing step."""
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or 443
    if parts.scheme != "https" or not host.endswith(".local"):
        return fail("mdns-name", "peer url is not an mDNS name (https://<host>.local:<port> required)")
    if not lookup(host):
        return fail("resolve", f"{host} does not resolve (is the peer host up and advertising?)")
    try:
        ctx = ssl.create_default_context(cafile=str(ca_file))
    except (OSError, ssl.SSLError) as exc:
        return fail("tls", f"cannot load tls_ca_file: {exc}")
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host):
                pass
    except ssl.SSLError as exc:
        return fail("tls", f"handshake for {host} not verified: {exc.reason or exc}")
    except OSError as exc:
        return fail("connect", f"{host}:{port}: {exc}")
    try:
        status, _ = request(host, port, ctx, "/healthz", None, timeout)
        if status != 200:
            return fail("healthz", f"/healthz answered {status}")
        token = token_file.read_text(encoding="utf-8").strip()
        status, body = request(host, port, ctx, OVERVIEW, token, timeout)
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        return fail("request", str(exc))
    if is_parent and status == 403 and PARENT_CLOSED in body:
        # A child may not read its parent's overview (by design); the 403 comes after the token was
        # accepted. Revision and manifest are compared from the parent's side.
        return True, "ok", "parent reached: name, TLS and auth agree (parent checks revision and manifest)"
    if status in (401, 403):
        return fail("auth",f"overview answered {status} (token rejected by the peer)")
    if status != 200:
        return fail("overview", f"overview answered {status}")
    try:
        doc = json.loads(body)
    except ValueError:
        return fail("overview", "overview is not JSON")
    if doc.get("config_revision") != revision:
        return fail("revision", f"peer revision {doc.get('config_revision')!r} != ours {revision!r}")
    theirs = doc.get("manifest_digest")  # absent on peers that predate the field
    if theirs and digest and theirs != digest:
        return fail("manifest", "same revision but different manifest (digest mismatch)")
    return True, "ok", "peer attached: name, TLS, auth, revision and manifest agree"


def check_config(path: Path, name: str, **kw) -> list[dict]:
    import yaml  # PyYAML: python3-yaml on Ubuntu

    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        unit, manifest = cfg["unit_id"], cfg["manifest"]
        revision, digest = manifest["revision"], manifest_digest(manifest)
        peers = cfg.get("peers") or {}
        ca = path.parent / cfg["tls_ca_file"]
        parent = next((u.get("parent") for u in manifest["units"] if u["id"] == unit), None)
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        return [dict(unit=path.parent.name, peer="-", ok=False, step="config", detail=f"{path}: {type(exc).__name__}")]
    rows = []
    ok, step, detail = host_check(name, **{k: v for k, v in kw.items() if k in ("active", "local")})
    rows.append(dict(unit=unit, peer="-", ok=ok, step=step, detail=detail))
    for peer, entry in sorted(peers.items()):
        try:
            ok, step, detail = peer_check(entry["url"], path.parent / entry["token_file"], ca, revision, digest,
                                          is_parent=peer == parent,
                                          **{k: v for k, v in kw.items() if k in ("lookup", "request")})
        except (KeyError, TypeError, OSError) as exc:
            ok, step, detail = fail("config", f"peer entry unusable: {type(exc).__name__}")
        rows.append(dict(unit=unit, peer=peer, ok=ok, step=step, detail=detail))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", action="append", type=Path,
                    help="control-unit.yaml (repeatable; default: every one under /etc/rosy/control-unit)")
    ap.add_argument("--name", default=None, help="advertised host name (default: avahi host-name, else hostname)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    configs = args.config or sorted(Path("/etc/rosy/control-unit").glob("**/control-unit.yaml"))
    name = args.name or advertised_name()
    rows = [row for cfg in configs for row in check_config(cfg, name)] or [
        dict(unit="-", peer="-", ok=False, step="config", detail="no control-unit.yaml found under /etc/rosy/control-unit")]
    for row in rows:
        print(json.dumps(row) if args.json else
              f"{'ok  ' if row['ok'] else 'FAIL'} {row['unit']} -> {row['peer']} [{row['step']}] {row['detail']}")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
