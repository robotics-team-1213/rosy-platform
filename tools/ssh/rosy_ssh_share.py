"""Share SSH access to Rosy robots with a revocable, passphrase-locked team key (D-418 3).

    python tools/ssh/rosy_ssh_share.py create --name <team> --robot <ip> [--robot <ip> ...] [--days 90] --out <dir>
    python tools/ssh/rosy_ssh_share.py revoke --name <team> --robot <ip> [--robot <ip> ...]
    python tools/ssh/rosy_ssh_share.py list --robot <ip> [--robot <ip> ...] [--name <team>]

create:
1. passphrase: typed twice (at least 12 characters), or, when left empty, generated and shown once at the end.
   It is never written to disk. It reaches ssh-keygen through -N, the only non-interactive way.
2. key: `ssh-keygen -t ed25519` in a work folder inside --out. The key file must be OpenSSH-encrypted
   (cipher not "none", kdf "bcrypt"), or nothing is registered and nothing is bundled.
3. register: on every robot, an administrator login code (asked per robot, or read over ssh with the operator
   key when --via-operator-key is given), then `GET /host-keys` and `POST /keys` with label `team:<name>`.
   If a later robot fails, no bundle is built and the revoke command for the robots already done is printed.
4. bundle: `<out>/rosy-<team>.zip` (flat entries: it unpacks to the `~/.ssh/rosy-<team>/` that config names) with the locked private key (mode 0600), its .pub, `config` (a Host block
   per robot), `known_hosts` (the robots' host keys) and a Korean README.md for the recipients.
   The work folder is removed. The passphrase is in no file of the bundle.

revoke deletes `team:<name>` on each robot; list prints the managed keys. Login tokens are logged out in
`finally` and never printed. Standard library plus the OpenSSH client tools; Windows, macOS and Linux.
Shares the API client with rosy_ssh_enroll.py. Contract: docs/plans/2026-10-02-d418-robot-ssh-access.md.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import getpass
import importlib.util
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import struct
import sys
import tempfile
from typing import Callable, Iterator
import zipfile


def _load_enroll():
    spec = importlib.util.spec_from_file_location("rosy_ssh_enroll", Path(__file__).with_name("rosy_ssh_enroll.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


enroll = _load_enroll()
SshAccessError = enroll.SshAccessError

TEAM = re.compile(r"[a-z0-9][a-z0-9._-]{0,42}")
PASSPHRASE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
GENERATED = re.compile(r"[2-9a-hjkmnp-z]{4}(?:-[2-9a-hjkmnp-z]{4}){4}")
MIN_PASSPHRASE = 12
PAIR_LABEL = "ssh-share"
LOGIN_CODE_COMMAND = "sudo -n rosy-login-code --role administrator --minutes 5"
LOGIN_CODE = re.compile(r"Login code ([A-Z0-9]{4}-[A-Z0-9]{4})")
OPENSSH_BEGIN = "-----BEGIN OPENSSH PRIVATE KEY-----"
OPENSSH_END = "-----END OPENSSH PRIVATE KEY-----"
OPENSSH_MAGIC = b"openssh-key-v1\0"
SCRIPT = "python tools/ssh/rosy_ssh_share.py"


# --- key checks ----------------------------------------------------------------------

def generate_passphrase() -> str:
    """Five groups of four from a 31-letter unambiguous alphabet: about 99 bits."""
    return "-".join("".join(secrets.choice(PASSPHRASE_ALPHABET) for _ in range(4)) for _ in range(5))


def key_encryption(path: Path) -> tuple[str, str]:
    """(ciphername, kdfname) from an OpenSSH private key file header."""
    try:
        lines = path.read_text(encoding="ascii").strip().splitlines()
        if len(lines) < 3 or lines[0] != OPENSSH_BEGIN or lines[-1] != OPENSSH_END:
            raise ValueError
        data = base64.b64decode("".join(lines[1:-1]), validate=True)
        if not data.startswith(OPENSSH_MAGIC):
            raise ValueError
        fields, offset = [], len(OPENSSH_MAGIC)
        for _ in range(2):
            (size,) = struct.unpack(">I", data[offset:offset + 4])
            fields.append(data[offset + 4:offset + 4 + size].decode("ascii"))
            offset += 4 + size
    except (OSError, ValueError, struct.error):
        raise SshAccessError(f"{path.name} is not an OpenSSH private key") from None
    return fields[0], fields[1]


# --- robots ----------------------------------------------------------------------------

class Deps:
    # Plain class: the tests load this file by path without a sys.modules entry.
    def __init__(self, *, get_code: Callable[[str], str], ask_passphrase, keygen, client_for):
        self.get_code, self.ask_passphrase, self.keygen, self.client_for = get_code, ask_passphrase, keygen, client_for


def operator_code(robot: str, key: Path, ssh) -> str:
    """Issue a short administrator login code on the robot over ssh with the operator key; never printed."""
    known = []
    if os.environ.get("LOCALAPPDATA"):
        known = ["-o", "UserKnownHostsFile=" + (Path(os.environ["LOCALAPPDATA"]) / "Rosy" / "known_hosts").as_posix()]
    argv = ["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=accept-new", *known, "-o", "ConnectTimeout=10",
            f"rosy@{robot}", LOGIN_CODE_COMMAND]
    code, out, err = ssh(argv)
    if code != 0:
        raise SshAccessError(f"{robot}: ssh with the operator key failed (exit {code}): {err.strip()[:300]}")
    match = LOGIN_CODE.search(out)
    if match is None:
        raise SshAccessError(f"{robot}: rosy-login-code printed no login code")
    return match.group(1)


@contextlib.contextmanager
def robot_session(robot: str, deps: Deps) -> Iterator[tuple[object, str]]:
    client = deps.client_for(robot)
    code = deps.get_code(robot)
    with enroll.admin_session(client, code, PAIR_LABEL) as token:
        yield client, token


def _clean(value: object) -> str:
    return re.sub(r"[^\x20-\x7e]", "?", str(value))[:80]


# --- create ------------------------------------------------------------------------------

class Robot:
    def __init__(self, address: str, hostname: str, host_keys: list[str]):
        self.address, self.hostname, self.host_keys = address, hostname, host_keys


def revoke_command(name: str, addresses: list[str]) -> str:
    return f"{SCRIPT} revoke --name {name} " + " ".join(f"--robot {address}" for address in addresses)


def with_revoke_hint(error: Exception, name: str, label: str, done: list[Robot]) -> SshAccessError:
    addresses = [robot.address for robot in done]
    return SshAccessError(f"{error}\nno bundle was built; {label} is already registered on {', '.join(addresses)}. "
                          f"Remove it there with:\n  {revoke_command(name, addresses)}")


def register_everywhere(args, deps: Deps, public_key: str, label: str) -> list[Robot]:
    done: list[Robot] = []
    try:
        for address in args.robot:
            with robot_session(address, deps) as (client, token):
                hostname, host_keys = enroll.fetch_host_keys(client, token)
                twin = next((robot for robot in done if robot.hostname == hostname), None)
                if twin is not None:  # two Host blocks with one alias: ssh would only ever use the first
                    raise SshAccessError(f"{address} reports the duplicate hostname {hostname}, "
                                         f"already used by {twin.address}; nothing registered on {address}")
                enroll.register_key(client, token, public_key, label, args.days)
            done.append(Robot(address, hostname, host_keys))
            print(f"{address}: {label} registered on {hostname}")
    except SshAccessError as error:
        if done:
            raise with_revoke_hint(error, args.name, label, done) from None
        raise
    return done


def bundle_config(name: str, key_name: str, robots: list[Robot]) -> str:
    folder = PurePosixPath("~/.ssh", f"rosy-{name}")
    blocks = [enroll.host_block(robot.hostname, robot.address, folder / key_name, folder / "known_hosts",
                                extra=("    AddKeysToAgent yes",)) for robot in robots]
    header = (f"# Rosy team key team:{name}. Use: ssh -F config <robot>, or put\n"
              f"# 'Include rosy-{name}/config' at the top of ~/.ssh/config.\n\n")
    return header + "\n".join(blocks)


def readme(name: str, key_name: str, robots: list[Robot], days: int, expires: dt.date, contact: str) -> str:
    rows = "\n".join(f"| `{robot.hostname}` | `{robot.address}` | "
                     + "<br>".join(f"`{key.split()[0]} {enroll.fingerprint(key)}`" for key in robot.host_keys) + " |"
                     for robot in robots)
    first = robots[0].hostname
    return f"""# Rosy 로봇 SSH 접속 묶음 — 팀 `{name}`

이 묶음으로 아래 로봇에 `rosy` 계정으로 SSH 접속한다. `rosy`는 비밀번호 없이 `sudo`가 되므로
**이 접속은 로봇의 root 권한과 같다.** 조심해서 쓴다.

- 키 라벨: `team:{name}` · 만료: {days}일 뒤({expires.isoformat()}, UTC)에 로봇이 스스로 거절한다.
- 개인 키 `{key_name}`는 passphrase로 잠겨 있다. passphrase는 이 묶음에 없다. 묶음을 준 사람에게
  다른 경로(메신저, 구두 등)로 따로 받는다.

| 로봇(별칭) | 주소 | host key 지문 |
|---|---|---|
{rows}

## 1. 파일 놓기

파일들은 반드시 `~/.ssh/rosy-{name}/` 폴더 **바로 안**에 있어야 한다. `config`가 이 위치를 가리키므로
폴더 이름을 바꾸거나 한 단계 더 들어간 폴더에 두지 않는다. 압축 파일 안에는 폴더 없이 파일만 들어 있다.

- **Windows**: `rosy-{name}.zip`을 오른쪽 클릭 → **모두 압축 풀기** → 대상 폴더를
  `%USERPROFILE%\\.ssh\\rosy-{name}`로 바꾸고 압축 풀기. OpenSSH 클라이언트가 필요하다
  (Windows 10/11 기본 포함, `ssh -V`로 확인).
- **macOS**: zip을 더블 클릭하면 같은 폴더에 `rosy-{name}` 폴더가 생긴다(보통 `~/Downloads`). 그 폴더를 옮긴다.

  ```sh
  mkdir -p ~/.ssh && mv ~/Downloads/rosy-{name} ~/.ssh/
  ```
- **Linux**: `unzip rosy-{name}.zip -d ~/.ssh/rosy-{name}`
- **macOS / Linux** 공통으로 권한을 좁힌다.

  ```sh
  chmod 700 ~/.ssh/rosy-{name}
  chmod 600 ~/.ssh/rosy-{name}/{key_name}
  ```

확인: `~/.ssh/rosy-{name}/config` 파일이 있어야 한다.

## 2. 접속

macOS / Linux:

```sh
cd ~/.ssh/rosy-{name}
ssh -F config {first}
```

Windows PowerShell:

```powershell
cd $HOME\\.ssh\\rosy-{name}
ssh -F config {first}
```

처음 접속할 때 passphrase를 묻는다. 입력하는 동안 화면에 아무것도 보이지 않는 것이 정상이다.
host key를 묻는 질문은 나오지 않아야 한다(`known_hosts`가 함께 들어 있다). 묻는다면 접속을 멈추고
묶음을 준 사람에게 알린다.

어디서든 `ssh {first}`로 쓰려면 `~/.ssh/config` **맨 위**에 이 한 줄을 넣는다.

```
Include rosy-{name}/config
```

## 3. passphrase를 매번 치지 않기 (ssh-agent)

- **Windows** (관리자 PowerShell에서 한 번): `Get-Service ssh-agent | Set-Service -StartupType Automatic; Start-Service ssh-agent`
  그다음 `ssh-add $HOME\\.ssh\\rosy-{name}\\{key_name}`
- **macOS**: `ssh-add --apple-use-keychain ~/.ssh/rosy-{name}/{key_name}`
- **Linux**: `eval "$(ssh-agent -s)"` 후 `ssh-add ~/.ssh/rosy-{name}/{key_name}`

`config`에 `AddKeysToAgent yes`가 있어, agent가 켜져 있으면 처음 한 번 입력한 뒤로는 묻지 않는다.

## 4. 휴대폰 SSH 앱 (Termius 등)

- 키 메뉴에서 `{key_name}` 파일을 가져오고 passphrase를 입력한다.
- 호스트: 위 표의 주소, 포트 22, 사용자 `rosy`, 인증은 그 키.
- 처음 접속 때 앱이 보여 주는 host key 지문(`SHA256:…`)이 위 표와 같은지 확인한다. 다르면 접속하지 않는다.
- 휴대폰에 키를 넣었다면 화면 잠금을 켜 둔다.

## 5. 지켜 줄 것

- **이 묶음, 키 파일, passphrase를 다른 사람에게 넘기지 않는다.** 오래 쓸 사람은 자기 기기를
  `rosy_ssh_enroll.py`로 따로 등록받는다(기기마다 라벨이 남고 따로 회수된다).
- 저장소, 공유 드라이브, 채팅방에 올리지 않는다.
- 잃어버렸거나 샌 것 같으면 바로 알린다. 회수는 로봇마다 라벨 `team:{name}`을 지우는 것이며,
  그 순간부터 이 키는 어느 로봇에도 접속되지 않는다.

회수·문의: {contact}
"""


def write_bundle(bundle: Path, work: Path, key: Path, public_key: str, robots: list[Robot], args,
                 today: dt.date) -> None:
    entries = [
        (key.name, key.read_bytes(), 0o600),
        (key.name + ".pub", (public_key + "\n").encode("ascii"), 0o644),
        ("config", bundle_config(args.name, key.name, robots).encode("utf-8"), 0o644),
        ("known_hosts", "".join(f"{robot.hostname},{robot.address} {line}\n"
                                for robot in robots for line in robot.host_keys).encode("ascii"), 0o644),
        ("README.md", readme(args.name, key.name, robots, args.days, today + dt.timedelta(days=args.days),
                             args.contact).encode("utf-8"), 0o644),
    ]
    temporary = work / bundle.name
    with zipfile.ZipFile(temporary, "w") as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, date_time=dt.datetime.now().timetuple()[:6])
            info.create_system = 3  # unix, so unzip on macOS/Linux applies the mode
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    os.replace(temporary, bundle)


def robots_listing(name: str, label: str, public_key: str, robots: list[Robot], expires: dt.date) -> str:
    """Non-secret record kept beside the zip: where the team key is registered and how to remove it."""
    lines = [f"# Rosy team key {label} {enroll.fingerprint(public_key)}, expires {expires.isoformat()} (UTC)",
             "# robot address, hostname, host key fingerprints"]
    lines += [f"{robot.address} {robot.hostname} " + " ".join(enroll.fingerprint(key) for key in robot.host_keys)
              for robot in robots]
    lines += ["# revoke:", revoke_command(name, [robot.address for robot in robots])]
    return "\n".join(lines) + "\n"


def show_passphrase(passphrase: str) -> None:
    """On stderr (the terminal), never on stdout that might be piped into a file."""
    if not sys.stderr.isatty():
        print("warning: stderr is not a terminal; the passphrase below may be captured in a log", file=sys.stderr)
    print(f"Passphrase (shown once, saved nowhere): {passphrase}", file=sys.stderr)


def create(args, deps: Deps) -> int:
    label = f"team:{args.name}"
    bundle = args.out / f"rosy-{args.name}.zip"
    listing = args.out / f"rosy-{args.name}.robots.txt"
    if bundle.exists():
        raise SshAccessError(f"{bundle} already exists; move it away first")
    typed = enroll.ask_new_passphrase(deps.ask_passphrase, "Passphrase for the team key (empty = generate one): ")
    if typed and len(typed) < MIN_PASSPHRASE:
        raise SshAccessError(f"the passphrase needs at least {MIN_PASSPHRASE} characters")
    passphrase = typed or generate_passphrase()

    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".rosy-ssh-share-", dir=args.out))
    try:
        key = work / f"id_ed25519_rosy_{args.name}"
        enroll.generate_key(key, label, passphrase, deps.keygen)
        cipher, kdf = key_encryption(key)
        if cipher == "none" or kdf != "bcrypt":
            raise SshAccessError(f"ssh-keygen wrote a key that is not encrypted ({cipher}/{kdf}); "
                                 "nothing was registered or bundled")
        public_key = enroll.read_public_key(Path(str(key) + ".pub"))
        robots = register_everywhere(args, deps, public_key, label)
        today = dt.datetime.now(dt.timezone.utc).date()
        try:
            write_bundle(bundle, work, key, public_key, robots, args, today)
            enroll.write_private_text(listing, robots_listing(args.name, label, public_key, robots,
                                                              today + dt.timedelta(days=args.days)))
        except (OSError, SshAccessError) as error:
            bundle.unlink(missing_ok=True)
            raise with_revoke_hint(error, args.name, label, robots) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"bundle: {bundle}")
    print(f"{label} {enroll.fingerprint(public_key)} on {len(robots)} robot(s), expires in {args.days} days")
    print(f"robots and revoke command: {listing}")
    print(f"revoke: {revoke_command(args.name, [robot.address for robot in robots])}")
    print("Hand over the zip and the passphrase by two different channels.")
    if typed:
        print("The passphrase you typed was not written anywhere.")
    else:
        show_passphrase(passphrase)
    return 0


# --- revoke and list -------------------------------------------------------------------

def revoke(args, deps: Deps) -> int:
    label, failed = (args.label or f"team:{args.name}"), False
    for robot in args.robot:
        try:
            with robot_session(robot, deps) as (client, token):
                status, body = client.call("DELETE", f"{enroll.API}/keys/{label}", token=token)
            if status == 204:
                print(f"{robot}: revoked {label}")
            elif status == 404:
                print(f"{robot}: {label} was not present")
            else:
                raise enroll.api_error(f"revoking {label}", status, body)
        except SshAccessError as error:
            print(f"rosy_ssh_share: {robot}: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def list_keys(args, deps: Deps) -> int:
    label, failed = (f"team:{args.name}" if args.name else None), False
    for robot in args.robot:
        try:
            with robot_session(robot, deps) as (client, token):
                keys = enroll.list_keys(client, token)
        except SshAccessError as error:
            print(f"rosy_ssh_share: {robot}: {error}", file=sys.stderr)
            failed = True
            continue
        keys = [key for key in keys if label is None or key.get("label") == label]
        if not keys:
            print(f"{robot}: no managed keys" + (f" labelled {label}" if label else ""))
            continue
        print(f"{robot}:")
        for key in keys:
            print(f"  {_clean(key.get('label')):<24} {_clean(key.get('type')):<20} {_clean(key.get('fingerprint'))}"
                  f"  expires {_clean(key.get('expires_at'))}  added {_clean(key.get('added_at'))}"
                  f" by {_clean(key.get('added_by'))}")
    return 1 if failed else 0


# --- command -----------------------------------------------------------------------------

def team_name(value: str) -> str:
    if not TEAM.fullmatch(value):
        raise argparse.ArgumentTypeError("expected lowercase a-z 0-9 . _ - (at most 43 characters)")
    return value


def managed_label(value: str) -> str:
    if not enroll.LABEL.fullmatch(value) or not value.startswith(("dev:", "team:")):
        raise argparse.ArgumentTypeError("expected dev:<name> or team:<name>, lowercase a-z 0-9 . _ -")
    return value


OPERATOR_DEFAULT = "<operator default>"


def operator_key(value: Path | str) -> Path:
    if value != OPERATOR_DEFAULT:
        return Path(value)
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise SshAccessError("--via-operator-key needs a key path here (LOCALAPPDATA is not set)")
    return Path(base) / "Rosy" / "ssh" / "rosy-operator-ed25519"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--robot", action="append", required=True, type=enroll.robot_address,
                        help="robot IP address; repeat for more robots")
    common.add_argument("--api-port", type=enroll.api_port, default=enroll.DEFAULT_API_PORT)
    common.add_argument("--via-operator-key", nargs="?", type=Path, const=OPERATOR_DEFAULT, default=None,
                        metavar="KEY", help="read each robot's login code over ssh with the operator key "
                                            "(default %%LOCALAPPDATA%%\\Rosy\\ssh\\rosy-operator-ed25519)")
    make = sub.add_parser("create", parents=[common], help="make a team key, register it, build the bundle")
    make.add_argument("--name", type=team_name, required=True)
    make.add_argument("--days", type=enroll.expiry_days, default=90, help="expiry, 1-365 (default 90)")
    make.add_argument("--out", type=Path, required=True, help="folder for rosy-<team>.zip and rosy-<team>.robots.txt (not the repo)")
    make.add_argument("--contact", default="이 묶음을 준 운영자", help="who recipients ask for revocation")
    gone = sub.add_parser("revoke", parents=[common], help="delete team:<name> (or one dev:/team: label) on each robot")
    target = gone.add_mutually_exclusive_group(required=True)
    target.add_argument("--name", type=team_name, help="team name: revokes team:<name>")
    target.add_argument("--label", type=managed_label, help="any managed label, e.g. dev:<name> from rosy_ssh_enroll")
    show = sub.add_parser("list", parents=[common], help="show the managed keys on each robot")
    show.add_argument("--name", type=team_name)
    return parser


def main(argv: list[str] | None = None, *, ask_code=None, ask_passphrase=None, keygen=None, client_for=None,
         ssh=None) -> int:
    args = _parser().parse_args(argv)
    args.robot = list(dict.fromkeys(args.robot))
    ask_code = ask_code or getpass.getpass

    def get_code(robot: str) -> str:
        if args.via_operator_key is not None:
            return operator_code(robot, operator_key(args.via_operator_key), ssh or enroll.run_tool)
        return ask_code(enroll.CODE_PROMPT.format(robot=robot)).strip()

    deps = Deps(get_code=get_code, ask_passphrase=ask_passphrase or getpass.getpass, keygen=keygen or enroll.run_tool,
                client_for=client_for or (lambda robot: enroll.CoreClient(f"http://{robot}:{args.api_port}")))
    try:
        return {"create": create, "revoke": revoke, "list": list_keys}[args.command](args, deps)
    except SshAccessError as error:
        print(f"rosy_ssh_share: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
