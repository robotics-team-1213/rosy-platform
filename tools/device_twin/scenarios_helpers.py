"""Result tracking, process helpers, and SSH scenario mixin for tools/device_twin/scenarios.py."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from twin_lib import IMAGE_BASE, NET, TWIN, UPDATES, log, run  # noqa: E402


class Result:
    def __init__(self, key: str, title: str) -> None:
        self.key, self.title = key, title
        self.checks: list[tuple[str, bool, str]] = []
        self.evidence: list[tuple[str, str]] = []
        self.error: str | None = None
        self.seconds = 0.0

    def check(self, description: str, ok: object, detail: object = "") -> bool:
        self.checks.append((description, bool(ok), str(detail)))
        log(f"  {'PASS' if ok else 'FAIL'} {description} {str(detail)[:200]}")
        return bool(ok)

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.checks) and all(ok for _d, ok, _x in self.checks)


def _ordered(items: list[str], wanted: list[str]) -> bool:
    position = 0
    for item in items:
        if position < len(wanted) and item == wanted[position]:
            position += 1
    return position == len(wanted)


def _wait(process: subprocess.Popen, timeout: float) -> object:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return "timeout"


class SshScenariosMixin:
    def _start_and_interrupt(self, steps: tuple[str, ...], how: str, timeout: float = 240,
                             wait_runtime: bool = True) -> str:
        """Start the updater, wait until its journal names one of ``steps``, then interrupt it."""
        t = self.twin
        t.x("systemctl start --no-block rosy-auto-update.service")
        probe = (f"python3 -c 'import json; a=json.load(open(\"{UPDATES}/state.json\")).get(\"applying\") or {{}}; "
                 "print(a.get(\"step\") or \"\")' 2>/dev/null || true")
        deadline = time.monotonic() + timeout
        step = ""
        while time.monotonic() < deadline:
            step = t.out(probe)
            if step in steps:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"the updater never reached {steps} (last {step!r})")
        if how == "kill":
            t.x("systemctl kill --signal=SIGKILL rosy-auto-update.service")
        else:  # a power cut: the whole container dies at once, then boots again
            run(["docker", "kill", TWIN])
            run(["docker", "start", TWIN])
            if wait_runtime:
                t.wait_runtime()
        return step

    # (ssh) --------------------------------------------------------------------------
    def ssh(self) -> None:
        """D-418 SSH access: enroll, log in, revoke, expired key, temporary password on/off/expiry, off after reboot."""
        self._ssh_with_client(socket_only=False)

    def ssh_socket(self) -> None:
        """D-418 SSH access with ssh.socket activation only: no ordering cycle, sshd -t without /run/sshd, all of (ssh)."""
        self._ssh_with_client(socket_only=True)

    def _ssh_with_client(self, *, socket_only: bool) -> None:
        client = "rosy-twin-sshclient"
        run(["docker", "rm", "-f", client], check=False)
        run(["docker", "run", "-d", "--name", client, "--network", NET, IMAGE_BASE, "sleep", "infinity"])
        # Per-step bound: a hung step is reported by name (and diagnosed) instead of ending the scenario.
        self.twin.step_timeout = 90
        try:
            self._ssh(client, socket_only)
        finally:
            self.twin.step_timeout = None
            run(["docker", "rm", "-f", client], check=False)

    def _ssh(self, client: str, socket_only: bool) -> None:
        t = self.twin
        # The robots (2026-10-02) run ssh.socket and ssh.service; Ubuntu 24.04's default is the socket alone.
        listener = "ssh.socket" if socket_only else "ssh.service"
        ssh_opts = ("-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 "
                    "-o LogLevel=ERROR")

        def diagnose(step: str) -> None:
            text = t.out("journalctl -u ssh.service -u ssh.socket -n 30 --no-pager -o short-monotonic; ss -tnp; "
                         "ps -eo pid,etime,stat,wchan:20,cmd | grep -E '[s]shd|[r]osy-ssh'; "
                         "systemctl list-jobs --no-pager", check=False, timeout=60)
            self.note(f"STEP TIMEOUT diagnostics: {step}", text)

        def on_client(command: str) -> subprocess.CompletedProcess:
            # coreutils timeout inside the client, and a bound on docker exec itself.
            argv = ["docker", "exec", client, "timeout", "60", "bash", "-c", command]
            try:
                done = run(argv, check=False, timeout=90)
            except subprocess.TimeoutExpired:
                done = subprocess.CompletedProcess(argv, 124, "", "docker exec did not return in 90 s")
            if done.returncode == 124:
                log(f"  STEP TIMEOUT on the client: {command[:160]}")
                diagnose(command[:160])
            return done

        def login_key(name: str) -> int:
            return on_client(f"ssh -i /root/{name} {ssh_opts} -o BatchMode=yes -o PreferredAuthentications=publickey "
                             f"rosy@{TWIN} true").returncode

        def login_password(password: str) -> int:
            return on_client(f"SSHPASS='{password}' sshpass -e ssh {ssh_opts} -o PreferredAuthentications=password "
                             f"-o PubkeyAuthentication=no rosy@{TWIN} true").returncode

        def request(action: str, params: dict | None = None) -> dict:
            done = t.x(f"twin-ssh-request {action} '{json.dumps(params or {})}'", user="rosy-core", check=False)
            lines = done.stdout.strip().splitlines()
            return json.loads(lines[-1]) if lines else {"stderr": done.stderr.strip()[-400:]}

        def shadow() -> str:
            return t.out("getent shadow rosy | cut -d: -f2")

        def history() -> list[dict]:
            text = t.out("cat /var/lib/rosy/ssh/history.jsonl 2>/dev/null || true")
            return [json.loads(line) for line in text.splitlines() if line.strip()]

        def password_dropin() -> bool:
            return t.x("test -e /etc/ssh/sshd_config.d/60-rosy-temp-password.conf", check=False).returncode == 0

        def sshd_says(user: str, addr: str, key: str) -> str:
            return t.out(f"sshd -T -C user={user},host=client,addr={addr},laddr=10.0.0.2,lport=22 "
                         f"| grep -i '^{key} '", check=False)

        def wait_listener() -> None:
            deadline = time.monotonic() + 60
            while t.x(f"systemctl is-active --quiet {listener}", check=False).returncode != 0 \
                    and time.monotonic() < deadline:
                time.sleep(1)

        def boot_order_checks(when: str) -> None:
            cycles = t.out("journalctl -b --no-pager | grep -i 'ordering cycle' || true", check=False)
            self.r.check(f"{when}: no ordering cycle in this boot's journal", cycles == "", cycles)
            done = t.x("systemd-analyze verify default.target", check=False)
            text = (done.stdout + done.stderr).strip()
            self.note(f"{when}: systemd-analyze verify default.target (exit {done.returncode})", text or "(no output)")
            self.r.check(f"{when}: systemd-analyze verify default.target exits 0 and finds no cycle",
                         done.returncode == 0 and "cycle" not in text.lower(), text[-600:])
            stamps = {unit: int(t.out(f"systemctl show -p ActiveEnterTimestampMonotonic --value {unit}") or 0)
                      for unit in ("rosy-ssh-access-boot.service", listener)}
            self.r.check(f"{when}: the boot cleanup finished before {listener} accepted anyone",
                         0 < stamps["rosy-ssh-access-boot.service"] <= stamps[listener], stamps)

        if socket_only:
            t.x("systemctl disable ssh.service && systemctl enable ssh.socket")
            run(["docker", "restart", TWIN], timeout=180)
            t.wait_runtime()
            wait_listener()
            self.ev("systemctl is-enabled ssh.socket ssh.service; systemctl is-active ssh.socket ssh.service; "
                    "ls -ld /run/sshd")
            # Nothing connected yet, so ssh.service (RuntimeDirectory=sshd) never ran.
            missing = t.x("test -d /run/sshd", check=False).returncode != 0
            early = request("password_on", {"minutes": 5})
            self.r.check("socket only: with /run/sshd missing, sshd -t passes and the password goes on",
                         missing and early.get("status") == 200, {"missing": missing, **early, "result": "(hidden)"})
            self.r.check("socket only: and goes off again", request("password_off").get("status") == 204)
            # Negative control: the boot unit's old default dependencies close the cycle with ssh.socket.
            t.x("mkdir -p /run/systemd/system/rosy-ssh-access-boot.service.d && printf '[Unit]\\nDefaultDependencies=yes\\n'"
                " > /run/systemd/system/rosy-ssh-access-boot.service.d/old.conf && systemctl daemon-reload")
            control = t.x("systemd-analyze verify default.target", check=False)
            control_text = (control.stdout + control.stderr).strip()
            self.note("control: DefaultDependencies=yes, systemd-analyze verify default.target", control_text)
            self.r.check("control: with default dependencies, verify finds the ordering cycle",
                         "cycle" in control_text.lower(), control_text[-600:])
            t.x("rm -rf /run/systemd/system/rosy-ssh-access-boot.service.d && systemctl daemon-reload")

        # Boot: the cleanup ran before sshd, the password is off, the keys drop-in is in place.
        self.ev(f"systemctl is-active {listener} rosy-ssh-access-boot.service rosy-ssh-access.path; "
                "ls -l /etc/ssh/sshd_config.d/; getent shadow rosy | cut -d: -f2")
        units = t.out(f"systemctl is-active {listener} rosy-ssh-access-boot.service rosy-ssh-access.path",
                      check=False).split()
        self.r.check(f"boot: {listener}, the boot cleanup and the request watch are active", units == ["active"] * 3,
                     units)
        boot_order_checks("boot")
        self.r.check("boot: rosy's shadow field is * and no password drop-in",
                     shadow() == "*" and not password_dropin(), shadow())
        self.r.check("sshd -t accepts the managed-keys drop-in", t.x("sshd -t", check=False).returncode == 0)
        # The deny drop-in the helper writes when usermod cannot lock the password (D-418 review).
        t.x("python3 -I -B -c \"import importlib.util as u; "
            "s = u.spec_from_file_location('h', '/opt/rosy/native-runtime/rosy-ssh-access.py'); "
            "m = u.module_from_spec(s); s.loader.exec_module(m); "
            "open('/etc/ssh/sshd_config.d/60-rosy-temp-password.conf', 'w').write(m.PASSWORD_DENY_TEXT)\"")
        deny_ok = t.x("sshd -t", check=False).returncode == 0
        deny_says = sshd_says("rosy", "10.1.2.3", "passwordauthentication")
        t.x("rm -f /etc/ssh/sshd_config.d/60-rosy-temp-password.conf")
        self.r.check("sshd -t accepts the deny drop-in, and it refuses rosy's password from a private address",
                     deny_ok and deny_says.endswith("no"), deny_says)
        rosy_files = sshd_says("rosy", "10.1.2.3", "authorizedkeysfile")
        root_files = sshd_says("root", "10.1.2.3", "authorizedkeysfile")
        self.r.check("the managed file is read for rosy only, beside the card's .ssh/authorized_keys",
                     "/var/lib/rosy/ssh/authorized_keys" in rosy_files and ".ssh/authorized_keys " in rosy_files + " "
                     and "/var/lib/rosy/ssh" not in root_files, f"rosy: {rosy_files} | root: {root_files}")
        self.r.check("cloud-init's global PasswordAuthentication no holds with no temporary password",
                     sshd_says("rosy", "10.1.2.3", "passwordauthentication").endswith("no")
                     and sshd_says("root", "10.1.2.3", "passwordauthentication").endswith("no"))
        self.ev("sshd -T -C user=root,host=client,addr=10.1.2.3,laddr=10.0.0.2,lport=22 "
                "| grep -iE '^(subsystem|usepam|x11forwarding|printmotd|kbdinteractiveauthentication) '")

        for name in ("k1", "k2", "k3"):
            on_client(f"ssh-keygen -q -t ed25519 -N '' -C twin-{name} -f /root/{name}")

        def pub(name: str) -> str:
            return on_client(f"cat /root/{name}.pub").stdout.strip()

        # Enroll, log in, revoke.
        added = request("add", {"public_key": pub("k1"), "label": "dev:twin-a", "expires_days": 1})
        self.note("add dev:twin-a", json.dumps(added))
        self.r.check("enroll through CORE's hand-over: 201 with a fingerprint", added.get("status") == 201
                     and str((added.get("result") or {}).get("fingerprint", "")).startswith("SHA256:"), added)
        self.r.check("the enrolled key logs in", login_key("k1") == 0)
        self.ev("cat /var/lib/rosy/ssh/authorized_keys; stat -c '%a %U %n' /var/lib/rosy/ssh /var/lib/rosy/ssh/*")
        listed = request("list")
        self.r.check("list shows it, added_by the requesting label",
                     [(row["label"], row["added_by"]) for row in (listed.get("result") or {}).get("keys", [])]
                     == [("dev:twin-a", "twin admin")], listed)
        revoked = request("revoke", {"label": "dev:twin-a"})
        self.r.check("revoke: 204", revoked.get("status") == 204, revoked)
        self.r.check("the revoked key is refused", login_key("k1") != 0)
        missing = request("revoke", {"label": "dev:twin-a"})
        self.r.check("revoking it again: 404 SSH_KEY_NOT_FOUND", (missing.get("status"), missing.get("error"))
                     == (404, "SSH_KEY_NOT_FOUND"), missing)
        bad = request("add", {"public_key": "ssh-rsa AAAAB3NzaC1yc2E=", "label": "dev:rsa", "expires_days": 1})
        self.r.check("the root helper refuses an RSA key on its own (422)", bad.get("status") == 422, bad)

        # Expiry: sshd enforces the line's expiry-time; the helper prunes the record.
        request("add", {"public_key": pub("k2"), "label": "dev:twin-b", "expires_days": 1})
        self.r.check("a second key logs in before its expiry", login_key("k2") == 0)
        t.x("sed -i -E 's/^expiry-time=\"[0-9]+Z\"(.*rosy-managed:dev:twin-b)$/expiry-time=\"202001010000Z\"\\1/' "
            "/var/lib/rosy/ssh/authorized_keys")
        self.ev("cat /var/lib/rosy/ssh/authorized_keys")
        self.r.check("a key whose expiry-time has passed is refused by sshd", login_key("k2") != 0)
        t.x("python3 -c \"import json; p='/var/lib/rosy/ssh/keys.json'; d=json.load(open(p)); "
            "[k.update(expires_at='2020-01-01T00:00:00Z') for k in d['keys'] if k['label']=='dev:twin-b']; "
            "json.dump(d, open(p, 'w'))\"")
        t.x("systemctl start rosy-ssh-password-expire.service", check=False)
        events = history()
        self.r.check("the next helper run prunes it and records expire",
                     "dev:twin-b" not in t.out("cat /var/lib/rosy/ssh/authorized_keys")
                     and any(e["event"] == "expire" and e.get("label") == "dev:twin-b" for e in events),
                     [e["event"] for e in events])

        # Temporary password on, then off.
        issued = request("password_on", {"minutes": 5})
        password = str((issued.get("result") or {}).get("password", ""))
        self.r.check("password on: 200 rosy-xxxx-xxxx-xxxx", issued.get("status") == 200
                     and len(password) == 19 and password.startswith("rosy-"), {**issued, "result": "(hidden)"})
        self.r.check("the expiry timer runs while it is on",
                     t.out("systemctl is-active rosy-ssh-password-expire.timer", check=False) == "active")
        self.r.check("password login works from the docker network", login_password(password) == 0)
        self.r.check("sshd: password yes for rosy from a private address, no from a public one, MaxAuthTries 3",
                     sshd_says("rosy", "10.1.2.3", "passwordauthentication").endswith("yes")
                     and sshd_says("rosy", "8.8.8.8", "passwordauthentication").endswith("no")
                     and sshd_says("rosy", "10.1.2.3", "maxauthtries").endswith("3"),
                     f"{sshd_says('rosy', '10.1.2.3', 'passwordauthentication')} / "
                     f"{sshd_says('rosy', '8.8.8.8', 'passwordauthentication')} / "
                     f"root: {sshd_says('root', '10.1.2.3', 'passwordauthentication')}")
        leaks = t.out(f"grep -rlF -- '{password}' /var/lib/rosy /etc/ssh /run/rosy /var/log 2>/dev/null; "
                      f"journalctl --no-pager | grep -cF -- '{password}'", check=False)
        self.r.check("the password is in no file, log or journal", leaks.split() == ["0"], leaks)
        off = request("password_off")
        self.r.check("password off: 204", off.get("status") == 204, off)
        self.r.check("after off: refused, shadow *, no drop-in, timer stopped",
                     login_password(password) != 0 and shadow() == "*" and not password_dropin()
                     and t.out("systemctl is-active rosy-ssh-password-expire.timer", check=False) != "active",
                     shadow())

        # Expiry by the timer (1 minute, checked every 30 s).
        short = request("password_on", {"minutes": 1})
        short_password = str((short.get("result") or {}).get("password", ""))
        self.r.check("a 1-minute password logs in", login_password(short_password) == 0)
        deadline = time.monotonic() + 150
        while password_dropin() and time.monotonic() < deadline:
            time.sleep(5)
        last = (history() or [{}])[-1]
        self.r.check("the timer turns it off after expiry (reason expired)",
                     not password_dropin() and last.get("event") == "password_off" and last.get("reason") == "expired"
                     and login_password(short_password) != 0 and shadow() == "*", last)
        self.ev("journalctl -u rosy-ssh-password-expire.service -u rosy-ssh-access.service -o cat --no-pager "
                "| tail -n 12")

        # Reboot with a password on and a key enrolled: the key survives, the password does not.
        request("add", {"public_key": pub("k3"), "label": "team:twin", "expires_days": 90})
        long = request("password_on", {"minutes": 30})
        long_password = str((long.get("result") or {}).get("password", ""))
        self.r.check("before the reboot: password and key both log in",
                     login_password(long_password) == 0 and login_key("k3") == 0)
        run(["docker", "restart", TWIN], timeout=180)
        t.wait_runtime()
        wait_listener()
        boot_order_checks("after the reboot")
        last = (history() or [{}])[-1]
        self.r.check("after the reboot the password is off (shadow *, no drop-in, reason boot)",
                     shadow() == "*" and not password_dropin() and last.get("reason") == "boot", last)
        self.r.check("after the reboot the password is refused", login_password(long_password) != 0)
        self.r.check("after the reboot the enrolled key still logs in", login_key("k3") == 0)
        status = request("password_status")
        self.r.check("password status after the reboot: off",
                     status.get("result") == {"enabled": False, "expires_at": None, "lock_pending": False}, status)
        self.ev("cat /var/lib/rosy/ssh/history.jsonl")

        verify = {}
        for unit in ("rosy-ssh-access.service", "rosy-ssh-access.path", "rosy-ssh-access-boot.service",
                     "rosy-ssh-password-expire.service", "rosy-ssh-password-expire.timer"):
            done = t.x(f"systemd-analyze verify /etc/systemd/system/{unit}", check=False)
            verify[unit] = (done.returncode, (done.stdout + done.stderr).strip())
        self.r.check("systemd-analyze verify: the D-418 units exit 0 with no output",
                     all(value == (0, "") for value in verify.values()),
                     {unit: value for unit, value in verify.items() if value != (0, "")})
