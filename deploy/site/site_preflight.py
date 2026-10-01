#!/usr/bin/env python3
"""Run on the Ubuntu site host before `compose up`: check the site config agrees with itself (D-391 3).

Standard library only, so it also runs on Windows for tests. Checks, each with a
reason and a fix hint; the exit status is non-zero when any check fails:

1. site_cert is a fullchain: a leaf (not a CA) followed by a CA certificate.
2. The leaf has a DNS SAN equal to tls_host (case-insensitive, exact; a wildcard
   SAN does not count).
3. tls_host is a `<name>.local` name (the shared discovery rule), not an IP.
4. The tls_host the advertise units publish (`--tls-host`, after resolving
   `${VAR}` from the unit Environment= lines and the env file) equals tls_host,
   and the Caddyfile site address names no other host.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import re
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = "/etc/rosy/site/.env"
DEFAULT_SITE_ENV = "/etc/rosy/site/site.env"          # what the stack unit hands Compose
DEFAULT_SECRETS_DIR = "/etc/rosy/site/secrets"
DEFAULT_UNITS = ("rosy-overhead-advertise.service", "rosy-fleet-advertise.service")
FULLCHAIN_FIX = ("build it with `cat site.crt site-ca.crt > site-fullchain.crt` and point the "
                 "site_cert secret at that file (deploy/site/README.md)")

# Copy of core_common.protocol.discovery_txt.HOSTNAME (this script cannot import it);
# test/test_site_preflight.py holds the CA check below to test/fixtures/protocol/site-link.v1.json.
HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")

# Copy of core_common.protocol.site_link CA/leaf DER check (this script cannot import it).
# Minimal DER walk; it reads basicConstraints only and verifies no signature or date.
_PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----(?P<body>[A-Za-z0-9+/=\s]*?)-----END CERTIFICATE-----")
# DER encodings of OID 2.5.29.19 (basicConstraints) and 2.5.29.17 (subjectAltName).
_BASIC_CONSTRAINTS_OID = bytes.fromhex("0603551d13")
_SAN_OID = bytes.fromhex("0603551d11")


class _DerError(ValueError):
    pass


def ca_pem_reason(value: object) -> str | None:
    """bad_ca_pem unless every block parses; leaf_not_ca if any block is not a CA."""
    if not isinstance(value, str):
        return "bad_ca_pem"
    blocks = list(_PEM_BLOCK.finditer(value))
    if not blocks or _PEM_BLOCK.sub("", value).strip():
        return "bad_ca_pem"
    verdicts = []
    for block in blocks:
        try:
            der = base64.b64decode("".join(block.group("body").split()), validate=True)
            verdicts.append(_is_ca_certificate(der))
        except (binascii.Error, _DerError):
            return "bad_ca_pem"
    return None if all(verdicts) else "leaf_not_ca"


def _tlv(data: bytes, pos: int, end: int) -> tuple[int, int, int]:
    """Read one DER TLV at ``pos``; return (tag, content_start, content_end)."""
    if pos + 2 > end:
        raise _DerError("truncated")
    tag, length = data[pos], data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > end:
            raise _DerError("bad length")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    if pos + length > end:
        raise _DerError("truncated")
    return tag, pos, pos + length


def _children(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    items, pos = [], start
    while pos < end:
        item = _tlv(data, pos, end)
        items.append(item)
        pos = item[2]
    return items


def _extension_value(der: bytes, oid: bytes) -> tuple[int, int] | None:
    """Return the (start, end) of the extnValue OCTET STRING content for ``oid``, if present."""
    tag, start, end = _tlv(der, 0, len(der))
    if tag != 0x30:
        raise _DerError("certificate is not a SEQUENCE")
    parts = _children(der, start, end)
    if len(parts) != 3 or parts[0][0] != 0x30:
        raise _DerError("certificate must hold tbsCertificate, algorithm, signature")
    for tag, start, end in _children(der, parts[0][1], parts[0][2]):
        if tag != 0xA3:  # [3] EXPLICIT extensions
            continue
        seq_tag, seq_start, seq_end = _tlv(der, start, end)
        if seq_tag != 0x30:
            raise _DerError("extensions are not a SEQUENCE")
        for ext_tag, ext_start, ext_end in _children(der, seq_start, seq_end):
            fields = _children(der, ext_start, ext_end)
            if ext_tag != 0x30 or not fields:
                raise _DerError("bad extension")
            if der[ext_start:fields[0][2]] != oid:
                continue
            value_tag, value_start, value_end = fields[-1]
            if value_tag != 0x04:
                raise _DerError("extnValue is not an OCTET STRING")
            return value_start, value_end
    return None


def _is_ca_certificate(der: bytes) -> bool:
    """True when basicConstraints says cA=TRUE; absent extension means not a CA (RFC 5280)."""
    value = _extension_value(der, _BASIC_CONSTRAINTS_OID)
    if value is None:
        return False
    bc_tag, bc_start, bc_end = _tlv(der, *value)
    if bc_tag != 0x30:
        raise _DerError("basicConstraints is not a SEQUENCE")
    inner = _children(der, bc_start, bc_end)
    # cA BOOLEAN DEFAULT FALSE: present and non-zero means CA.
    return bool(inner) and inner[0][0] == 0x01 and der[inner[0][1]:inner[0][2]] != b"\x00"


def _dns_sans(der: bytes) -> list[str]:
    """dNSName entries of subjectAltName (IP and other name types are ignored on purpose)."""
    value = _extension_value(der, _SAN_OID)
    if value is None:
        return []
    names_tag, names_start, names_end = _tlv(der, *value)
    if names_tag != 0x30:
        raise _DerError("subjectAltName is not a SEQUENCE")
    return [der[start:end].decode("ascii", "replace")
            for tag, start, end in _children(der, names_start, names_end) if tag == 0x82]


def _certificates(path: Path) -> list[bytes]:
    text = path.read_text(encoding="ascii", errors="replace")
    try:
        return [base64.b64decode("".join(m.group("body").split()), validate=True)
                for m in _PEM_BLOCK.finditer(text)]
    except binascii.Error as exc:
        raise _DerError("bad base64 in a CERTIFICATE block") from exc


def _normalise(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _check(check_id: str, ok: bool, detail: str, fix: str = "") -> dict:
    return {"id": check_id, "ok": ok, "reason": detail, "fix": "" if ok else fix}


def check_site_cert(path: Path, tls_host: str) -> list[dict]:
    """Checks 1 and 2: fullchain shape and the tls_host DNS SAN."""
    chain_id, san_id = "site_cert_fullchain", "leaf_san_tls_host"
    skipped = _check(san_id, False, "not checked because the site_cert chain is unusable",
                     "fix the site_cert fullchain first")
    try:
        certs = _certificates(path)
    except OSError as exc:
        return [_check(chain_id, False, f"cannot read site_cert {path}: {exc.strerror or exc}",
                       "point --site-cert (or ROSY_SITE_SECRETS_DIR/site.crt) at the site fullchain file"),
                skipped]
    except _DerError as exc:
        return [_check(chain_id, False, f"site_cert is not valid PEM: {exc}",
                       "re-issue the site certificate; " + FULLCHAIN_FIX), skipped]
    if not certs:
        return [_check(chain_id, False, "site_cert holds no PEM CERTIFICATE block",
                       "re-issue the site certificate; " + FULLCHAIN_FIX), skipped]
    try:
        leaf_is_ca = _is_ca_certificate(certs[0])
        second_is_ca = _is_ca_certificate(certs[1]) if len(certs) > 1 else None
        sans = _dns_sans(certs[0])
    except _DerError as exc:
        return [_check(chain_id, False, f"site_cert holds a certificate that does not parse: {exc}",
                       "re-issue the site certificate; " + FULLCHAIN_FIX), skipped]
    if leaf_is_ca:
        chain = _check(chain_id, False, "the first certificate in site_cert is a CA, not the site leaf",
                       "put the leaf first and the CA after it; " + FULLCHAIN_FIX)
    elif second_is_ca is None:
        chain = _check(chain_id, False, "site_cert holds only the leaf; clients pinning the CA fail "
                       "(2026-09-30 incident), so a fullchain is required", FULLCHAIN_FIX)
    elif not second_is_ca:
        chain = _check(chain_id, False, "the certificate after the leaf is not a CA "
                       "(basicConstraints CA:TRUE missing)", FULLCHAIN_FIX)
    else:
        chain = _check(chain_id, True, f"site_cert is leaf + CA ({len(certs)} certificates)")
    wanted = _normalise(tls_host)
    if wanted in (_normalise(name) for name in sans):
        san = _check(san_id, True, f"leaf SAN contains DNS:{wanted}")
    else:
        shown = ", ".join(sans) or "no DNS SAN"
        san = _check(san_id, False, f"leaf SAN has {shown}, not DNS:{wanted} "
                     "(exact match only; a wildcard does not count)",
                     f"re-issue the leaf with DNS SAN {wanted}, or set tls_host to a name it lists")
    return [chain, san]


def check_tls_host_local(tls_host: str) -> dict:
    """Check 3: tls_host is a .local name per the shared discovery rule."""
    check_id = "tls_host_local"
    if not tls_host:
        return _check(check_id, False, "tls_host is empty",
                      "set ROSY_SITE_TLS_HOST (or --tls-host) to the site <hostname>.local name")
    try:
        ipaddress.ip_address(tls_host)
    except ValueError:
        pass
    else:
        return _check(check_id, False, f"tls_host {tls_host} is an IP address; IPs go stale on renumber",
                      "use the Ubuntu <hostname>.local name; clients find the IP through mDNS")
    if not HOSTNAME.fullmatch(_normalise(tls_host)):
        return _check(check_id, False, f"tls_host {tls_host} is not a .local name",
                      "use <hostname>.local (letters, digits, hyphens; no port, no other domain)")
    return _check(check_id, True, f"tls_host {_normalise(tls_host)} is a .local name")


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a systemd EnvironmentFile; a missing file is empty."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]          # only a matching pair of quotes is syntax
        values[key.strip()] = value
    return values


def _exec_words(unit: Path, env_file: dict[str, str]) -> list[str]:
    """The unit's final ExecStart as systemd would expand it.

    Parsed from the unit: ``Environment=KEY=VALUE`` lines set defaults, an
    ``EnvironmentFile=`` line overlays ``env_file`` at its position, and each
    ExecStart word is expanded like systemd (``${VAR}``; an empty value yields
    an empty word).
    """
    env: dict[str, str] = {}
    words: list[str] = []
    # systemd joins a line ending in a backslash with the next one.
    text = re.sub(r"\\\r?\n", " ", unit.read_text(encoding="utf-8"))
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Environment="):
            for item in shlex.split(line[len("Environment="):]):
                key, _, value = item.partition("=")
                env[key] = value
        elif line.startswith("EnvironmentFile="):
            env.update(env_file)
        elif line.startswith("ExecStart="):
            command = line[len("ExecStart="):].lstrip("-@+!:")   # systemd exec prefixes
            # An empty ExecStart= resets the list; ${VAR} and $VAR both expand.
            words = [re.sub(r"\$\{(\w+)\}|\$(\w+)",
                            lambda m: env.get(m.group(1) or m.group(2), ""), word)
                     for word in shlex.split(command)]
    return words


def published_tls_host(unit: Path, env_file: dict[str, str]) -> tuple[bool, str | None]:
    """Return (is_overhead_advertise, tls_host the unit's ExecStart would publish).

    Only ``--tls-host X`` / ``--tls-host=X`` is read.
    """
    words = _exec_words(unit, env_file)
    overhead = any(words[i:i + 2] == ["--role", "overhead"] for i in range(len(words)))
    for index, word in enumerate(words):
        if word == "--tls-host":
            value = words[index + 1] if index + 1 < len(words) else ""
            return overhead, "" if value.startswith("--") else value
        if word.startswith("--tls-host="):
            return overhead, word.partition("=")[2]
    return overhead, None


def check_txt_tls_host(units: list[Path], env_file: dict[str, str], tls_host: str) -> dict:
    """Check 4a: the TXT tls_host the advertise units publish equals the configured tls_host."""
    check_id = "txt_tls_host"
    fix = ("set the same <hostname>.local as ROSY_SITE_TLS_HOST in /etc/rosy/site/.env, then "
           "`systemctl restart rosy-overhead-advertise.service`")
    wanted, problems, seen = _normalise(tls_host), [], 0
    for unit in units:
        try:
            overhead, published = published_tls_host(unit, env_file)
        except (OSError, ValueError) as exc:
            problems.append(f"{unit.name} cannot be read: {exc}")
            continue
        if published is None:
            if overhead:
                problems.append(f"{unit.name} advertises role overhead without --tls-host")
            continue
        seen += 1
        if _normalise(published) != wanted:
            problems.append(f"{unit.name} would publish TXT tls_host={_normalise(published) or '(empty)'}")
    if not seen and not problems:
        problems.append("no advertise unit publishes a TXT tls_host")
    if problems:
        return _check(check_id, False, "; ".join(problems) + f"; configured tls_host is {wanted}", fix)
    return _check(check_id, True, f"{seen} advertise unit(s) publish TXT tls_host={wanted}")


def published_pair(unit: Path, env_file: dict[str, str]) -> tuple[bool, bool]:
    """Return (is_overhead_advertise, whether the unit would publish TXT pair=rosy-pair/1)."""
    words = _exec_words(unit, env_file)
    overhead = any(words[i:i + 2] == ["--role", "overhead"] for i in range(len(words)))
    pair = any(word == "--pair" or word == "--pair=1" for word in words)
    return overhead, pair


def check_pairing(units: list[Path], env_file: dict[str, str], site_env: dict[str, str],
                  secrets_dir: Path) -> dict:
    """D-341: one switch (ROSY_SITE_PAIRING=1) must mean Fleet pairing, the TXT key and a token."""
    check_id = "pairing_consistent"
    fix = ("set ROSY_SITE_PAIRING=1 in both /etc/rosy/site/.env and /etc/rosy/site/site.env plus "
           "ROSY_SITE_PAIRING_COMPOSE=-f <candidate>/deploy/site/compose.pairing.yaml in site.env, "
           "create secrets/pairing_sync_token (deploy/site/README.md, Camera pairing), then restart "
           "rosy-site-stack and rosy-overhead-advertise; or clear all of them to turn pairing off")
    problems = []
    values = {".env": env_file.get("ROSY_SITE_PAIRING", ""),
              "site.env": site_env.get("ROSY_SITE_PAIRING", "")}
    for name, value in values.items():
        if value not in ("", "1"):
            problems.append(f"{name} has ROSY_SITE_PAIRING={value!r}; use 1 or leave it empty")
    if values[".env"] != values["site.env"]:
        problems.append("ROSY_SITE_PAIRING in .env and site.env disagree "
                        f"(.env={values['.env'] or 'empty'}, site.env={values['site.env'] or 'empty'})")
    enabled = values["site.env"] == "1"
    overlay = "compose.pairing.yaml" in site_env.get("ROSY_SITE_PAIRING_COMPOSE", "")
    if overlay != enabled:
        problems.append("ROSY_SITE_PAIRING_COMPOSE "
                        + ("lacks compose.pairing.yaml, so Fleet would not run pairing" if enabled
                           else "names compose.pairing.yaml but ROSY_SITE_PAIRING is not 1"))
    for unit in units:
        try:
            overhead, advertised = published_pair(unit, env_file)
        except (OSError, ValueError) as exc:
            problems.append(f"{unit.name} cannot be read: {exc}")
            continue
        if overhead and advertised != (values[".env"] == "1"):
            problems.append(f"{unit.name} " + ("would advertise pair=rosy-pair/1 but pairing is off"
                                              if advertised else "does not advertise pair=rosy-pair/1"))
    if enabled:
        try:
            token = (secrets_dir / "pairing_sync_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            problems.append(f"{secrets_dir / 'pairing_sync_token'} is missing or empty")
        else:
            for name in ("registry_token", "phone_ingress_token", "fleet_sighting_token",
                         "discovery_token", "vision_preview_secret", "robot_credential_key"):
                try:
                    other = (secrets_dir / name).read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if other == token:
                    problems.append(f"pairing_sync_token must be distinct, but equals {name}")
    if problems:
        return _check(check_id, False, "; ".join(problems), fix)
    return _check(check_id, True, "pairing on: Fleet overlay, TXT pair and sync token agree"
                  if enabled else "pairing off: nothing advertised, no overlay")


def caddy_site_hosts(text: str) -> list[str] | None:
    """Host parts of every top-level site block's addresses; None when there is no site block.

    Minimal parse: skip comments and the leading global `{ ... }` options block,
    take every top-level line that ends with `{` as a site address line (snippets
    `(name) {` are skipped), split it on
    commas/spaces, drop the scheme and the port. A bare `:port` yields no host
    (a catch-all address names nothing that could disagree). Snippets, imports,
    environment placeholders and path matchers are not interpreted.
    """
    depth = 0
    hosts: list[str] = []
    found = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if depth == 0 and line.endswith("{") and line != "{" and not line.startswith("("):
            found = True
            for address in re.split(r"[,\s]+", line[:-1].strip()):
                address = re.sub(r"^[a-z][a-z0-9+.-]*://", "", address)
                address = address.split("/", 1)[0]
                if address.startswith("["):
                    host = address[1:].partition("]")[0]
                else:
                    host = address.rsplit(":", 1)[0] if ":" in address else address
                if host:
                    hosts.append(host)
        depth += line.count("{") - line.count("}")
    return hosts if found else None


def check_caddy_host(path: Path, tls_host: str) -> dict:
    """Check 4b: the Caddyfile site address names no host other than tls_host."""
    check_id = "caddy_host"
    fix = f"change the Caddyfile site address to {_normalise(tls_host)} or :<port>"
    try:
        hosts = caddy_site_hosts(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _check(check_id, False, f"cannot read Caddyfile {path}: {exc.strerror or exc}",
                      "point --caddyfile at deploy/site/Caddyfile")
    if hosts is None:
        return _check(check_id, False, "Caddyfile has no site address block", fix)
    wanted = _normalise(tls_host)
    other = [h for h in hosts if _normalise(h) != wanted]
    if other:
        return _check(check_id, False, f"Caddy site address names {', '.join(other)}, not tls_host {wanted}", fix)
    return _check(check_id, True, "Caddy site address names " + (wanted if hosts else "no host (port-only address)"))


def run_checks(args: argparse.Namespace) -> list[dict]:
    env_file = read_env_file(Path(args.env_file))
    tls_host = args.tls_host or os.environ.get("ROSY_SITE_TLS_HOST") or env_file.get("ROSY_SITE_TLS_HOST", "")
    secrets = os.environ.get("ROSY_SITE_SECRETS_DIR", "")
    site_cert = args.site_cert or (str(Path(secrets) / "site.crt") if secrets else "")
    if not site_cert:
        site_cert_checks = [
            _check("site_cert_fullchain", False, "no site_cert path given",
                   "pass --site-cert or set ROSY_SITE_SECRETS_DIR"),
            _check("leaf_san_tls_host", False, "not checked because no site_cert path was given",
                   "pass --site-cert or set ROSY_SITE_SECRETS_DIR")]
    else:
        site_cert_checks = check_site_cert(Path(site_cert), tls_host)
    units = [Path(u) for u in (args.unit or [HERE / name for name in DEFAULT_UNITS])]
    return [*site_cert_checks, check_tls_host_local(tls_host),
            check_txt_tls_host(units, env_file, tls_host),
            check_pairing(units, env_file, read_env_file(Path(args.site_env)),
                          Path(args.secrets_dir or secrets or DEFAULT_SECRETS_DIR)),
            check_caddy_host(Path(args.caddyfile or HERE / "Caddyfile"), tls_host)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Site-host consistency preflight (D-391 3). Run before `compose up`.",
        epilog=("IP SAN is deliberately not checked: IP SANs go stale when the host is renumbered. "
                "An IP SAN is needed only for a manual_host fallback link and is outside this "
                "preflight. Configuration comes from flags, else the same variables the units "
                "use: ROSY_SITE_TLS_HOST (shell, then env file) and ROSY_SITE_SECRETS_DIR/site.crt."))
    parser.add_argument("--tls-host", help="site <hostname>.local name (env ROSY_SITE_TLS_HOST)")
    parser.add_argument("--site-cert", help="site_cert fullchain file (default $ROSY_SITE_SECRETS_DIR/site.crt)")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE,
                        help=f"stand-in for the units' EnvironmentFile (default {DEFAULT_ENV_FILE}; may be absent)")
    parser.add_argument("--site-env", default=DEFAULT_SITE_ENV,
                        help=f"the env file the stack unit hands Compose (default {DEFAULT_SITE_ENV}; may be absent)")
    parser.add_argument("--secrets-dir",
                        help="secrets directory (default $ROSY_SITE_SECRETS_DIR, else " + DEFAULT_SECRETS_DIR + ")")
    parser.add_argument("--unit", action="append",
                        help="advertise unit file; repeatable (default: the two units beside this script)")
    parser.add_argument("--caddyfile", help="Caddyfile (default: the one beside this script)")
    parser.add_argument("--json", action="store_true", help="print a JSON report instead of text")
    args = parser.parse_args(argv)
    checks = run_checks(args)
    ok = all(check["ok"] for check in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    else:
        for check in checks:
            line = f"{'PASS' if check['ok'] else 'FAIL'} {check['id']}: {check['reason']}"
            print(line + (f" | fix: {check['fix']}" if check["fix"] else ""))
        print("preflight: " + ("ok" if ok else "FAILED; do not start the site stack"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
