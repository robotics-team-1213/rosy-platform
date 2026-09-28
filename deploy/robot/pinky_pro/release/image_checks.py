"""What BUILD_GO actually checks, run against a mounted image tree (WP-6).

The design lists the image inspections in section 12.2, and they are the
difference between "an image was produced" and "an image that is safe to
write to a card". Every one of them is a question about a directory tree, so
they run here against a fabricated tree in a test and against a real
``losetup``/``mount`` on the build host — same code, same verdicts.

This does not build anything and cannot. Producing the image needs a native
ARM64 host; this is the gate that decides whether what came out is shippable.

Two checks are worth calling out because they encode decisions made
elsewhere and would otherwise be forgotten in the image:

* ``rosy-release-recover.service`` must be enabled *and* the runtime unit must
  require it. With ``Wants=`` a held device boots its runtime anyway and the
  hold becomes advisory.
* The account CORE runs as must not be the login account. SO_PEERCRED proves
  "a process with this uid", so if that uid is the Pi's default login user,
  the Host Agent's authentication is worth no more than an SSH session.
"""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path

#: Units the image must ship and enable.
REQUIRED_UNITS = (
    "rosy-release-recover.service",
    "rosy-runtime.service",
)

#: Units that must exist but must NOT be enabled: hardware stays off until a
#: separate field approval says otherwise.
FORBIDDEN_ENABLED_UNITS = (
    "rosy-motor.service",
    "rosy-io.service",
)

REQUIRED_PATHS = (
    "etc/rosy/trusted-release-keys",
    "opt/rosy/deploy/robot/compose.yaml",
    "opt/rosy/deploy/robot/runtime-mode.sh",
    "opt/rosy/deploy/robot/release-recover.sh",
    "opt/rosy/deploy/release",
    "opt/rosy/deploy/robot/config/board.yaml",
    "opt/rosy/deploy/robot/config/resolve-mode.sh",
    "opt/rosy/deploy/robot/config/capabilities.core.yaml",
    "opt/rosy/deploy/robot/config/capabilities.motor.yaml",
    "opt/rosy/deploy/robot/config/capabilities.hardware.yaml",
    "opt/rosy/deploy/robot/config/profile.core.yaml",
    "opt/rosy/deploy/robot/config/profile.motor.yaml",
    "opt/rosy/deploy/robot/config/profile.hardware.yaml",
)

#: The OCI archives the first boot imports locally. Without them the first
#: boot needs the internet, which section 7.3 forbids.
REQUIRED_OCI_ARCHIVES = (
    "opt/rosy/images/rosy-core.oci.tar",
    "opt/rosy/images/rosy-io.oci.tar",
)

PRIVATE_KEY_SUFFIXES = (".key", ".p12", ".pfx")
PRIVATE_KEY_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa")

_UART_OVERLAY = re.compile(r"^\s*dtoverlay=uart4", re.MULTILINE)

#: uid 1000 is the Pi's default interactive login account.
LOGIN_UID = 1000


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.detail}"


def _enabled_units(root: Path) -> set[str]:
    """Units systemd would start, by the symlinks `systemctl enable` leaves."""
    enabled: set[str] = set()
    for wants in (root / "etc/systemd/system").rglob("*.wants"):
        for link in wants.iterdir():
            enabled.add(link.name)
    return enabled


def check_units(root: Path) -> list[Finding]:
    """Required units present and enabled; hardware units present and not."""
    findings: list[Finding] = []
    unit_dir = root / "etc/systemd/system"
    enabled = _enabled_units(root)

    for unit in REQUIRED_UNITS:
        path = unit_dir / unit
        if not path.is_file():
            findings.append(Finding("IMAGE_UNIT_MISSING", unit, "not present in the image"))
            continue
        if unit not in enabled:
            findings.append(
                Finding("IMAGE_UNIT_NOT_ENABLED", unit, "present but not enabled; it will not run")
            )

    for unit in FORBIDDEN_ENABLED_UNITS:
        if unit in enabled:
            findings.append(
                Finding(
                    "IMAGE_HARDWARE_UNIT_ENABLED",
                    unit,
                    "hardware must stay off until a separate field approval",
                )
            )
    return findings


def check_recovery_gate(root: Path) -> list[Finding]:
    """The runtime must *require* the recovery gate, not merely want it.

    With Wants= a device held for recovery starts its runtime anyway and the
    hold is advisory — which is the entire failure the gate exists to prevent.
    """
    path = root / "etc/systemd/system/rosy-runtime.service"
    if not path.is_file():
        return [Finding("IMAGE_UNIT_MISSING", "rosy-runtime.service", "not present in the image")]

    parser = configparser.ConfigParser(strict=False, allow_no_value=True)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except configparser.Error as exc:
        return [Finding("IMAGE_UNIT_UNREADABLE", "rosy-runtime.service", str(exc))]

    unit = parser["Unit"] if parser.has_section("Unit") else {}
    requires = " ".join(unit.get(key, "") for key in ("Requires", "RequiresOverridable"))
    after = unit.get("After", "")

    findings: list[Finding] = []
    if "rosy-release-recover.service" not in requires:
        findings.append(
            Finding(
                "IMAGE_RECOVERY_GATE_NOT_REQUIRED",
                "rosy-runtime.service",
                "does not Require= rosy-release-recover.service; a recovery hold "
                "would not stop the runtime",
            )
        )
    if "rosy-release-recover.service" not in after:
        findings.append(
            Finding(
                "IMAGE_RECOVERY_GATE_UNORDERED",
                "rosy-runtime.service",
                "does not order After= rosy-release-recover.service; the runtime "
                "could start while the gate is still deciding",
            )
        )
    return findings


def check_release_keys(root: Path) -> list[Finding]:
    """A public key to verify releases, and no private key anywhere."""
    findings: list[Finding] = []
    key_dir = root / "etc/rosy/trusted-release-keys"

    public = [p for p in key_dir.glob("*.pem")] if key_dir.is_dir() else []
    if not public:
        findings.append(
            Finding(
                "IMAGE_RELEASE_KEY_MISSING",
                "etc/rosy/trusted-release-keys",
                "no trusted release public key; the device could not verify any update",
            )
        )

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        relative = path.relative_to(root).as_posix()
        if name in PRIVATE_KEY_NAMES or path.suffix in PRIVATE_KEY_SUFFIXES:
            findings.append(
                Finding("IMAGE_PRIVATE_KEY_PRESENT", relative, "key material must not ship")
            )
            continue
        if path.suffix == ".pem":
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:200]
            except OSError:
                continue
            if "PRIVATE KEY" in head:
                findings.append(
                    Finding("IMAGE_PRIVATE_KEY_PRESENT", relative, "a .pem holding a private key")
                )
    return findings


def check_runtime_defaults(root: Path) -> list[Finding]:
    """First boot comes up core-only, and the UART overlay is present but idle."""
    findings: list[Finding] = []

    env = root / "opt/rosy/deploy/robot/.env"
    if not env.is_file():
        findings.append(
            Finding("IMAGE_ENV_MISSING", "opt/rosy/deploy/robot/.env", "no runtime environment file")
        )
    else:
        text = env.read_text(encoding="utf-8")
        # 신원을 이미지에 구우면 그 이미지로 만든 모든 기기가 같은 도메인과 같은
        # namespace 로 뜬다 — D-33 이 없앤 결함을 이미지 규모로 되살리는 것이다.
        # 이미지 문서도 "같은 이미지를 여러 장비에 복제할 때 자격증명은 장비마다
        # 다르게" 라고 이미 말하고 있다. 신원도 같은 부류이므로 첫 부팅
        # 프로비저닝의 몫이고, 여기서는 구워져 있지 않은지만 본다.
        for key in ("ROS_DOMAIN_ID", "ROSY_NAMESPACE"):
            if any(line.strip().startswith(f"{key}=") for line in text.splitlines()):
                findings.append(
                    Finding(
                        "IMAGE_IDENTITY_BAKED",
                        "opt/rosy/deploy/robot/.env",
                        f"{key} is baked into the image; every unit flashed from it "
                        f"would share one identity (ADR D-33)",
                    )
                )
        if "ROSY_RUNTIME_MODE=core" not in text:
            findings.append(
                Finding(
                    "IMAGE_RUNTIME_MODE_NOT_CORE",
                    "opt/rosy/deploy/robot/.env",
                    "the image must boot core-only",
                )
            )

    config = root / "boot/firmware/config.txt"
    if not config.is_file():
        config = root / "boot/config.txt"
    if not config.is_file():
        findings.append(Finding("IMAGE_BOOT_CONFIG_MISSING", "boot/config.txt", "not present"))
    elif not _UART_OVERLAY.search(config.read_text(encoding="utf-8")):
        findings.append(
            Finding(
                "IMAGE_UART_OVERLAY_MISSING",
                config.relative_to(root).as_posix(),
                "the motor UART overlay must be present even though the service is off",
            )
        )
    return findings


def check_core_account(root: Path, *, login_uid: int = LOGIN_UID) -> list[Finding]:
    """CORE must not run as the account a person logs in with.

    The Host Agent authenticates by SO_PEERCRED, which proves "a process with
    this uid". If that uid is the Pi's login account then an SSH session as
    that user can drive release.install and system.reboot, and the socket's
    authentication is worth nothing.
    """
    passwd = root / "etc/passwd"
    if not passwd.is_file():
        return [Finding("IMAGE_PASSWD_MISSING", "etc/passwd", "not present")]

    accounts: dict[str, int] = {}
    for line in passwd.read_text(encoding="utf-8").splitlines():
        parts = line.split(":")
        if len(parts) > 2 and parts[2].isdigit():
            accounts[parts[0]] = int(parts[2])

    if "rosy" not in accounts:
        return [
            Finding(
                "IMAGE_CORE_ACCOUNT_MISSING",
                "etc/passwd",
                "no 'rosy' account; the Host Agent contract requires CORE to run "
                "as a system user distinct from the login account",
            )
        ]

    findings: list[Finding] = []
    if accounts["rosy"] == login_uid:
        findings.append(
            Finding(
                "IMAGE_CORE_ACCOUNT_IS_LOGIN_USER",
                "etc/passwd",
                f"'rosy' has uid {login_uid}, the interactive login account; "
                "SO_PEERCRED would prove nothing more than an SSH session",
            )
        )
    return findings


def check_offline_boot(root: Path) -> list[Finding]:
    """Everything the first boot imports must already be in the image."""
    findings = []
    for relative in REQUIRED_OCI_ARCHIVES:
        if not (root / relative).is_file():
            findings.append(
                Finding(
                    "IMAGE_OCI_ARCHIVE_MISSING",
                    relative,
                    "the first boot must not need the internet",
                )
            )
    for relative in REQUIRED_PATHS:
        if not (root / relative).exists():
            findings.append(Finding("IMAGE_PATH_MISSING", relative, "not present in the image"))
    return findings


def check_no_device_secrets(root: Path) -> list[Finding]:
    """Reuse the repository scanner over the image tree (section 12.2)."""
    from secret_scan import scan_files

    findings = []
    for hit in scan_files((p for p in root.rglob("*") if p.is_file()), root=root):
        findings.append(Finding("IMAGE_SECRET_PRESENT", hit.path, f"{hit.kind}: {hit.excerpt}"))
    return findings


def inspect_image(root: Path, *, login_uid: int = LOGIN_UID) -> list[Finding]:
    """Every section 12.2 check, in one pass.

    Returns findings rather than raising: a build host wants the whole list,
    not the first problem.
    """
    return [
        *check_units(root),
        *check_recovery_gate(root),
        *check_release_keys(root),
        *check_runtime_defaults(root),
        *check_core_account(root, login_uid=login_uid),
        *check_offline_boot(root),
        *check_no_device_secrets(root),
    ]
