"""Give this PC its own SSH key on one Rosy robot, unlocked by the robot's administrator login code (D-418 1).

    python tools/ssh/rosy_ssh_enroll.py <robot-ip> [--label dev:<name>] [--days 90] [--key PATH]

1. key: makes `~/.ssh/rosy_dev_<name>` with `ssh-keygen -t ed25519` when it is missing (optional passphrase).
   The private key never leaves this PC; only the .pub is sent.
2. pair: asks for the robot's administrator login code (robot screen, or `sudo rosy-login-code --role
   administrator` on the robot) and pairs it for a token (`POST /api/v1/auth/pair`).
3. host keys: `GET /api/v1/host/ssh/host-keys`; they go into `~/.ssh/known_hosts_rosy` under the robot's
   hostname and address, so the first connection asks no trust-on-first-use question.
4. register: `POST /api/v1/host/ssh/keys` with label `dev:<name>` and an expiry (1-365 days). A 409 for the
   same label and the same key is "already enrolled"; for another key it is an error.
5. alias: a managed `Host <hostname>` block in `~/.ssh/config` (replaced in place on a re-run).
6. logout: the token is logged out in `finally`. It is never printed or written anywhere.

The API is plain HTTP on the robot's LAN (--api-port, default 8080), like the dashboard. Standard library
plus the OpenSSH client tools; runs on Windows, macOS and Linux. Contract:
docs/plans/2026-10-02-d418-robot-ssh-access.md.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePath
import platform
import re
import shutil
import struct
import subprocess
import sys
from typing import Callable, Iterator
import urllib.error
import urllib.request

API = "/api/v1/host/ssh"
LABEL = re.compile(r"[a-z0-9][a-z0-9._:-]{0,47}")
DEVICE_LABEL = re.compile(r"dev:[a-z0-9][a-z0-9._-]{0,43}")
ROBOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
#: Aliases live in the rosy- namespace only, so an enrolled robot can never shadow another Host entry.
HOSTNAME = re.compile(r"rosy-[a-z0-9][a-z0-9-]{0,57}")
KEY_BLOB = re.compile(r"[A-Za-z0-9+/]+={0,2}")
CLIENT_KEY_TYPES = ("ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
HOST_KEY_TYPES = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-rsa")
DEFAULT_DAYS = 90
DEFAULT_API_PORT = 8080
#: CORE waits up to 10 s for the root helper; this leaves room for that and a slow LAN.
DEFAULT_TIMEOUT_S = 25
PAIR_LABEL = "ssh-enroll"
CODE_PROMPT = ("Administrator login code for {robot} (robot screen, or on the robot: "
               "sudo rosy-login-code --role administrator): ")

Runner = Callable[[list[str]], "tuple[int, str, str]"]
Ask = Callable[[str], str]


class SshAccessError(RuntimeError):
    pass


def home() -> Path:
    return Path.home()


# --- CORE HTTP -----------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is answered as an error: the token must never be sent anywhere but the robot asked."""

    def redirect_request(self, *args, **kwargs):
        return None


class CoreClient:
    """JSON over plain HTTP to one robot's CORE. Proxies from the environment are ignored (LAN only);
    redirects are not followed."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("Authorization", "Bearer " + token)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            # urllib wraps connect/send failures in URLError; a bare timeout came while waiting for the answer.
            if isinstance(error, TimeoutError) and not isinstance(error, urllib.error.URLError):
                raise SshAccessError(f"{self.base_url} did not answer {method} {path} within {self.timeout:g} s; "
                                     "the change may have been applied on the robot anyway, check with "
                                     "rosy_ssh_share.py list before retrying") from None
            raise SshAccessError(f"{self.base_url} is not reachable ({reason})") from None
        try:
            return status, (json.loads(raw) if raw else None)
        except ValueError:
            return status, None


def api_error(what: str, status: int, body: object) -> SshAccessError:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return SshAccessError(f"{what}: HTTP {status} {error.get('code')}: {error.get('message')}")
    return SshAccessError(f"{what}: HTTP {status}")


def pair(client: CoreClient, code: str, label: str) -> dict:
    status, body = client.call("POST", "/api/v1/auth/pair", {"code": code, "label": label})
    if status == 201 and isinstance(body, dict) and isinstance(body.get("token"), str) and body["token"]:
        return body
    error = api_error("pairing the login code", status, body)
    if status == 401:
        error = SshAccessError(f"{error} (the login code is wrong, used or expired; ask for a new one)")
    raise error


def logout(client: CoreClient, token: str) -> None:
    try:
        status, _ = client.call("POST", "/api/v1/auth/logout", token=token)
    except SshAccessError:
        status = None
    if status != 204:
        print(f"warning: the login token was not logged out (HTTP {status}); it expires on its own, "
              "or remove it in the dashboard token list", file=sys.stderr)


@contextlib.contextmanager
def admin_session(client: CoreClient, code: str, label: str = PAIR_LABEL) -> Iterator[str]:
    """Pair the code, insist on the administrator role, and always log the token out."""
    if not code:
        raise SshAccessError("no login code was given")
    paired = pair(client, code, label)
    token = paired["token"]
    try:
        role = paired.get("role")
        if role != "administrator":
            raise SshAccessError(f"that is a {role!s:.20} login code; SSH keys need an administrator code "
                                 "(sudo rosy-login-code --role administrator)")
        yield token
    finally:
        logout(client, token)


def fetch_host_keys(client: CoreClient, token: str) -> tuple[str, list[str]]:
    """(hostname, ["<type> <base64>", ...]) checked so nothing can inject into known_hosts or ssh config."""
    status, body = client.call("GET", API + "/host-keys", token=token)
    if status != 200 or not isinstance(body, dict):
        raise api_error("reading the robot host keys", status, body)
    hostname = body.get("hostname")
    if not isinstance(hostname, str) or not HOSTNAME.fullmatch(hostname):
        raise SshAccessError(f"the robot reported an unusable hostname {hostname!r:.80}")
    lines = body.get("host_keys")
    if not isinstance(lines, list) or not lines:
        raise SshAccessError("the robot reported no host keys")
    return hostname, [_key_line(line, HOST_KEY_TYPES, "host key") for line in lines]


def list_keys(client: CoreClient, token: str) -> list[dict]:
    status, body = client.call("GET", API + "/keys", token=token)
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("keys"), list):
        raise api_error("listing the managed keys", status, body)
    return [key for key in body["keys"] if isinstance(key, dict)]


def register_key(client: CoreClient, token: str, public_key: str, label: str, days: int) -> tuple[str, str]:
    """('added' | 'already', expires_at). 'already' when this very key holds the label; its expiry is kept."""
    status, body = client.call("POST", API + "/keys",
                               {"public_key": public_key, "label": label, "expires_days": days}, token=token)
    if status == 201:
        return "added", str(body.get("expires_at") if isinstance(body, dict) else "?")
    if status == 409:
        holder = next((key for key in list_keys(client, token) if key.get("label") == label), None)
        if holder is not None and holder.get("fingerprint") == fingerprint(public_key):
            return "already", str(holder.get("expires_at"))
        if holder is not None:
            raise SshAccessError(f"HTTP 409: label {label} is already used on the robot by another key; "
                                 "revoke it there first or choose another label")
    raise api_error(f"adding key {label}", status, body)


# --- keys --------------------------------------------------------------------------

def _key_line(line: object, allowed: tuple[str, ...], what: str) -> str:
    if not isinstance(line, str) or any(ch in line for ch in "\r\n\0"):
        raise SshAccessError(f"unusable {what} {line!r:.80}")
    fields = line.split()
    if len(fields) < 2 or fields[0] not in allowed or not KEY_BLOB.fullmatch(fields[1]):
        raise SshAccessError(f"unusable {what} {line!r:.80} (allowed types: {', '.join(allowed)})")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except ValueError:
        raise SshAccessError(f"unusable {what}: the key data is not base64") from None
    if not blob.startswith(struct.pack(">I", len(fields[0])) + fields[0].encode("ascii")):
        raise SshAccessError(f"unusable {what}: the key data is not a {fields[0]} key")
    return f"{fields[0]} {fields[1]}"


def fingerprint(public_key: str) -> str:
    """OpenSSH SHA256 fingerprint of a public key line."""
    blob = base64.b64decode(public_key.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def read_public_key(path: Path) -> str:
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise SshAccessError(f"cannot read {path}: {type(error).__name__}") from None
    if not text or "\n" in text:
        raise SshAccessError(f"{path} is not a one-line OpenSSH public key")
    _key_line(text, CLIENT_KEY_TYPES, f"public key {path.name}")
    return text


def run_tool(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", f"{type(error).__name__}: {error}"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def ssh_keygen() -> str:
    return shutil.which("ssh-keygen") or "ssh-keygen"


def generate_key(path: Path, comment: str, passphrase: str, keygen: Runner) -> None:
    """ssh-keygen -t ed25519. The passphrase goes in argv (-N): ssh-keygen reads nothing else non-interactively."""
    if path.exists() or Path(str(path) + ".pub").exists():
        raise SshAccessError(f"{path} already exists")
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
        if os.name != "nt":
            path.parent.chmod(0o700)
    code, _out, err = keygen([ssh_keygen(), "-q", "-t", "ed25519", "-a", "100", "-C", comment,
                              "-N", passphrase, "-f", str(path)])
    if code != 0 or not Path(str(path) + ".pub").is_file():
        raise SshAccessError(f"ssh-keygen failed (exit {code}): {err.strip()[:300]}")


def ask_new_passphrase(ask: Ask, prompt: str) -> str:
    first = ask(prompt)
    if not first:
        return ""
    if ask("Same passphrase again: ") != first:
        raise SshAccessError("the two passphrases did not match")
    return first


def ensure_key(path: Path, comment: str, keygen: Runner, ask_passphrase: Ask) -> bool:
    pub = Path(str(path) + ".pub")
    if path.exists() or pub.exists():
        if not pub.exists():
            raise SshAccessError(f"{path} exists without {pub.name}; recreate it with ssh-keygen -y -f <key>")
        return False
    passphrase = ask_new_passphrase(ask_passphrase, "Passphrase for the new key (empty for none): ")
    generate_key(path, comment, passphrase, keygen)
    return True


# --- known_hosts and ssh config ----------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_private_text(path: Path, text: str) -> None:
    """Atomic replace; 0600 on POSIX (ssh refuses a config others can write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".rosy-tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)


KNOWN_HOSTS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")


def plan_known_hosts(path: Path, names: list[str], keys: list[str]) -> tuple[str | None, str, list[str]]:
    """(new text or None, state, old key lines). Other hosts' lines are kept.

    state: 'unchanged'; 'added' (no line for these names yet); 'renamed' (same keys, other names);
    'changed' (the robot now presents other host keys, which the caller must not accept silently).
    """
    for name in names:
        if not KNOWN_HOSTS_NAME.fullmatch(name):
            raise SshAccessError(f"refusing to write an invalid known_hosts name {name!r:.80}")
    lines = _read(path).splitlines()

    def ours(line: str) -> bool:
        fields = line.split()
        return bool(fields) and not line.lstrip().startswith(("#", "@")) and \
            bool(set(fields[0].split(",")) & set(names))

    old = [line for line in lines if ours(line)]
    new = [f"{','.join(names)} {key}" for key in keys]
    if old == new:
        return None, "unchanged", []
    old_keys = [" ".join(line.split()[1:3]) for line in old]
    kept = [line for line in lines if not ours(line)]
    state = "added" if not old else ("renamed" if sorted(old_keys) == sorted(keys) else "changed")
    return "\n".join(kept + new) + "\n", state, old_keys


def _fingerprints(lines: list[str]) -> str:
    shown = []
    for line in lines:
        try:
            shown.append(f"{line.split()[0]} {fingerprint(line)}")
        except (IndexError, ValueError):
            shown.append(f"{line[:40]!r} (unreadable)")
    return ", ".join(shown)


#: The only lines a managed block may contain. Every option has a non-empty value without control
#: characters, % or $ (ssh expands those as tokens and environment variables), so nothing like a bare
#: `ProxyCommand` can ever reach an ssh config (2026-10-02 incident).
CONFIG_HOST = re.compile(r"Host rosy-[a-z0-9][a-z0-9-]{0,57}")
CONFIG_OPTION = re.compile(r"    (HostName [A-Za-z0-9][A-Za-z0-9.-]{0,252}|User rosy|IdentitiesOnly yes|AddKeysToAgent yes"
                           r"|(?:IdentityFile|UserKnownHostsFile) \"[^\"%$\x00-\x1f\x7f]+\")")


def _quoted(path: PurePath) -> str:
    if not path.name:
        raise SshAccessError(f"invalid ssh config value: empty path {path}")
    text = path.as_posix()
    if "%" in text or "$" in text:
        raise SshAccessError(f"invalid ssh config value: a path with % or $ is expanded by ssh: {text}")
    return f'"{text}"'


def host_block(alias: str, address: str, identity: PurePath, known_hosts: PurePath,
               extra: tuple[str, ...] = ()) -> str:
    lines = [f"Host {alias}", f"    HostName {address}", "    User rosy", f"    IdentityFile {_quoted(identity)}",
             f"    UserKnownHostsFile {_quoted(known_hosts)}", "    IdentitiesOnly yes", *extra]
    if not CONFIG_HOST.fullmatch(lines[0]):
        raise SshAccessError(f"refusing to write an invalid ssh config line {lines[0]!r:.80}")
    for line in lines[1:]:
        if not CONFIG_OPTION.fullmatch(line):
            raise SshAccessError(f"refusing to write an invalid ssh config line {line!r:.80}")
    return "\n".join(lines) + "\n"


def backup_file(path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    copy = path.with_name(f"{path.name}.rosy-backup-{stamp}")
    shutil.copy2(path, copy)
    return copy


def ssh_client() -> str:
    return shutil.which("ssh") or "ssh"


def _same_path(printed: str, ours: PurePath) -> bool:
    def norm(text: str) -> str:
        text = text.strip().replace("\\", "/")
        return text.lower() if os.name == "nt" else text
    return norm(printed) == norm(ours.as_posix())


def check_resolved(out: str, address: str, identity: Path, known_hosts: Path) -> str | None:
    """What `ssh -G` resolved differently from the managed block, or None when ours wins."""
    values: dict[str, list[str]] = {}
    for line in out.splitlines():
        words = line.split(None, 1)
        if len(words) == 2:
            values.setdefault(words[0].lower(), []).append(words[1].strip())
    if [value.lower() for value in values.get("hostname", [])] != [address.lower()]:
        return f"hostname {values.get('hostname')}"
    if values.get("user") != ["rosy"]:
        return f"user {values.get('user')}"
    if not any(_same_path(item, identity) for item in values.get("identityfile", [])):
        return f"identityfile {values.get('identityfile')}"
    known = values.get("userknownhostsfile", [""])[0].replace("\\", "/")
    ours = known_hosts.as_posix()
    if not (known.lower() if os.name == "nt" else known).startswith(ours.lower() if os.name == "nt" else ours):
        return f"userknownhostsfile {values.get('userknownhostsfile')}"
    return None


def install_ssh_config(path: Path, text: str, alias: str, address: str, identity: Path, known_hosts: Path,
                       ssh: Runner) -> Path | None:
    """Back up, replace atomically, then let OpenSSH resolve the alias (`ssh -G`); roll back unless it
    resolves to our HostName, User, IdentityFile and UserKnownHostsFile."""
    backup = backup_file(path) if path.exists() else None
    write_private_text(path, text)
    code, out, err = ssh([ssh_client(), "-G", "-F", str(path), alias])
    problem = err.strip()[:300] if code != 0 else check_resolved(out, address, identity, known_hosts)
    if problem is None:
        return backup
    if backup is not None:
        shutil.copy2(backup, path)
        undo = f"restored the previous file from {backup.name}"
    else:
        path.unlink()
        undo = "removed it again (restored: there was none before)"
    raise SshAccessError(f"ssh -G could not use the new {path} ({problem}); {undo}")


_HOSTNAME_LINE = re.compile(r"\s*HostName\s+(\S+)\s*", re.IGNORECASE)


def plan_ssh_config(path: Path, alias: str, block: str, address: str, replace: bool = False) -> str | None:
    """New config text with the managed block for alias first (before any Host, Match or Include line, so
    its values win), or None when nothing changes. Markers must be exactly one pair or none."""
    begin, end = f"# >>> rosy-ssh {alias} >>>", f"# <<< rosy-ssh {alias} <<<"
    managed = f"{begin}\n{block}{end}\n"
    text = _read(path)
    lines = text.splitlines(keepends=True)
    stripped = [line.strip() for line in lines]
    begins, ends = stripped.count(begin), stripped.count(end)
    if (begins, ends) not in ((0, 0), (1, 1)) or (begins and stripped.index(end) < stripped.index(begin)):
        raise SshAccessError(f"{path} has damaged rosy-ssh markers for {alias} ({begins} begin, {ends} end); "
                             "fix them by hand (or restore a config.rosy-backup-* copy), then run again")
    if begins:
        start, stop = stripped.index(begin), stripped.index(end)
        old_hosts = [m.group(1) for line in lines[start:stop] if (m := _HOSTNAME_LINE.fullmatch(line))]
        if old_hosts and old_hosts != [address] and not replace:
            raise SshAccessError(f"{path}: {alias} already points at {old_hosts[0]}, not {address}; "
                                 "check the robot screen, then run again with --replace")
        rest = lines[stop + 1:]
        if rest and not rest[0].strip():
            rest = rest[1:]  # the blank line written after the block
        lines = lines[:start] + rest
    else:
        for line in stripped:
            words = line.split()
            if len(words) >= 2 and words[0].lower() == "host" and alias in words[1:]:
                raise SshAccessError(f"{path} already has a 'Host {alias}' entry this tool did not write; "
                                     "remove it, then run again")
    first = next((index for index, line in enumerate(lines)
                  if line.split()[:1] and line.split()[0].lower() in ("host", "match", "include")), len(lines))
    head, tail = "".join(lines[:first]), "".join(lines[first:])
    if head and not head.endswith("\n"):
        head += "\n"
    updated = head + managed + ("\n" if tail and not tail.startswith("\n") else "") + tail
    return None if updated == text else updated


# --- command ---------------------------------------------------------------------------

def default_label(node: str | None = None) -> str:
    node = node if node is not None else platform.node()
    name = re.sub(r"[^a-z0-9._-]+", "-", node.lower())
    suffix = ""
    if not node.isascii():  # 회의실PC and 연구실PC must not both become dev:pc
        suffix = "-" + hashlib.sha256(node.encode("utf-8")).hexdigest()[:6]
    name = name.strip("._-")[:44 - len(suffix)].rstrip("._-") or "pc"
    return "dev:" + name + suffix


def _device_label(value: str) -> str:
    if not DEVICE_LABEL.fullmatch(value):
        raise argparse.ArgumentTypeError("expected dev:<name>, lowercase a-z 0-9 . _ - (at most 48 characters)")
    return value


def robot_address(value: str) -> str:
    if not ROBOT.fullmatch(value):
        raise argparse.ArgumentTypeError("expected an IPv4 address or a host name")
    return value


def expiry_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a whole number of days") from None
    if not 1 <= days <= 365:
        raise argparse.ArgumentTypeError("must be 1-365")
    return days


def api_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a port number") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be 1-65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("robot", type=robot_address, help="robot IP address (or host name)")
    parser.add_argument("--label", type=_device_label, help="dev:<name> (default: dev:<this PC's name>)")
    parser.add_argument("--days", type=expiry_days, default=DEFAULT_DAYS, help=f"expiry, 1-365 (default {DEFAULT_DAYS})")
    parser.add_argument("--key", type=Path, help="private key path (default ~/.ssh/rosy_dev_<name>)")
    parser.add_argument("--known-hosts", type=Path, help="default ~/.ssh/known_hosts_rosy")
    parser.add_argument("--ssh-config", type=Path, help="default ~/.ssh/config")
    parser.add_argument("--api-port", type=api_port, default=DEFAULT_API_PORT, help="CORE HTTP port (default 8080)")
    parser.add_argument("--replace", action="store_true",
                        help="the alias already points at another address; point it at this one")
    parser.add_argument("--accept-new-host-keys", action="store_true",
                        help="the robot presents other host keys than known_hosts has (card re-flashed); "
                             "accept them after checking on the robot's screen or console")
    return parser


def _absolute(path: Path) -> Path:
    """~ expanded and made absolute; symlinks resolved, so a linked ~/.ssh/config is edited at its target."""
    return path.expanduser().resolve()


def enroll(args, *, ask_code: Ask, ask_passphrase: Ask, keygen: Runner, client: CoreClient, ssh: Runner) -> int:
    label = args.label or default_label()
    ssh_dir = home() / ".ssh"
    key = _absolute(args.key or ssh_dir / ("rosy_" + label.replace(":", "_")))
    known_hosts = _absolute(args.known_hosts or ssh_dir / "known_hosts_rosy")
    config = _absolute(args.ssh_config or ssh_dir / "config")
    _quoted(key), _quoted(known_hosts)  # refuse an unusable path before anything is created or sent

    if ensure_key(key, label, keygen, ask_passphrase):
        print(f"created key {key}")
    public_key = read_public_key(Path(str(key) + ".pub"))
    print(f"key {label} {fingerprint(public_key)}")

    code = ask_code(CODE_PROMPT.format(robot=args.robot)).strip()
    with admin_session(client, code) as token:
        hostname, host_keys = fetch_host_keys(client, token)
        names = [hostname] if hostname == args.robot else [hostname, args.robot]
        known_text, known_state, old_keys = plan_known_hosts(known_hosts, names, host_keys)
        if known_state == "changed" and not args.accept_new_host_keys:
            raise SshAccessError(
                f"{hostname} now presents other host keys than {known_hosts}:\n"
                f"  old: {_fingerprints(old_keys)}\n  new: {_fingerprints(host_keys)}\n"
                "This is expected only after the card was re-flashed. These keys came over plain HTTP, so they are "
                "only as trustworthy as this LAN. Compare them on the robot's screen or console "
                "(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub), then run again with --accept-new-host-keys")
        block = host_block(hostname, args.robot, key, known_hosts)
        config_text = plan_ssh_config(config, hostname, block, args.robot, replace=args.replace)
        state, expires_at = register_key(client, token, public_key, label, args.days)

    if state == "already":
        print(f"{hostname}: already enrolled as {label}, expires {expires_at} "
              "(to renew: revoke the label, then enroll again)")
    else:
        print(f"{hostname}: key added as {label}, expires {expires_at}")
    if known_text is not None:
        write_private_text(known_hosts, known_text)
    if known_state == "changed":
        print(f"{hostname}: replaced its host keys in {known_hosts} ({_fingerprints(host_keys)})")
    if config_text is not None:
        backup = install_ssh_config(config, config_text, hostname, args.robot, key, known_hosts, ssh)
        print(f"updated {config}" + (f" (backup {backup})" if backup else ""))
    print("connect with:")
    print(f"  ssh {hostname}" if args.ssh_config is None else f'  ssh -F "{config}" {hostname}')
    return 0


def main(argv: list[str] | None = None, *, ask_code: Ask | None = None, ask_passphrase: Ask | None = None,
         keygen: Runner | None = None, client_for: Callable[[str], CoreClient] | None = None,
         ssh: Runner | None = None) -> int:
    args = _parser().parse_args(argv)
    client = (client_for or (lambda robot: CoreClient(f"http://{robot}:{args.api_port}")))(args.robot)
    try:
        return enroll(args, ask_code=ask_code or getpass.getpass, ask_passphrase=ask_passphrase or getpass.getpass,
                      keygen=keygen or run_tool, client=client, ssh=ssh or run_tool)
    except SshAccessError as error:
        print(f"rosy_ssh_enroll: {error}", file=sys.stderr)
    except UnicodeDecodeError as error:
        print(f"rosy_ssh_enroll: a file is not UTF-8 text ({error.reason}); nothing was changed", file=sys.stderr)
    except OSError as error:
        print(f"rosy_ssh_enroll: {type(error).__name__}: {error.strerror or error} "
              f"({error.filename or 'no file name'})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
