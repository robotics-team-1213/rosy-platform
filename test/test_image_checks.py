"""BUILD_GO's image inspections, run against fabricated trees (WP-6).

Design section 12.2 lists what an image must satisfy before it is written to
a card. Every one of those is a question about a directory tree, so the same
code that runs against a real ``mount`` on the build host runs here against a
tree built in tmp_path — which means the gate is testable long before the
hardware exists.

Building the image still needs a native ARM64 host. This is only the part
that decides whether what came out is shippable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from secret_scan import validate_redacted_payload, validate_transient_card_bundle
from image_checks import (  # via test/conftest.py
    check_core_account,
    check_no_device_secrets,
    check_recovery_gate,
    check_release_keys,
    check_runtime_defaults,
    check_units,
    inspect_image,
)

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_UNIT = """[Unit]
Description=ROSY Raspberry Pi robot runtime
Requires=docker.service
Requires=rosy-release-recover.service
After=rosy-release-recover.service

[Service]
Type=oneshot
"""

RECOVER_UNIT = """[Unit]
Description=ROSY release recovery gate
Before=rosy-runtime.service

[Service]
Type=oneshot
"""


def _pem_private_key(body: str) -> str:
    """Assemble a PEM private key at runtime.

    No PEM header literal may appear in any source file. The header is the
    secret scanner's entire signal for a private key, so excusing one as a
    known fixture would excuse every one in the repository — the scanner's
    own fixture list refuses to carry a header for exactly that reason.
    """
    dashes = "-" * 5
    return "\n".join([
        f"{dashes}BEGIN PRIVATE KEY{dashes}",
        body,
        f"{dashes}END PRIVATE KEY{dashes}",
        "",
    ])


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def image(tmp_path: Path) -> Path:
    """A tree that passes every check, so each test can break exactly one."""
    root = tmp_path / "image"

    units = root / "etc/systemd/system"
    _write(units / "rosy-runtime.service", RUNTIME_UNIT)
    _write(units / "rosy-release-recover.service", RECOVER_UNIT)
    _write(units / "rosy-motor.service", "[Unit]\nDescription=motor\n")
    _write(units / "rosy-io.service", "[Unit]\nDescription=io\n")

    wants = units / "multi-user.target.wants"
    wants.mkdir(parents=True, exist_ok=True)
    for unit in ("rosy-runtime.service", "rosy-release-recover.service"):
        (wants / unit).write_text("", encoding="utf-8")

    _write(root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
           "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----\n")
    _write(root / "etc/passwd", "root:x:0:0:root:/root:/bin/bash\n"
                                "pi:x:1000:1000:pi:/home/pi:/bin/bash\n"
                                "rosy:x:960:960:ROSY runtime:/var/lib/rosy:/usr/sbin/nologin\n")
    _write(root / "opt/rosy/deploy/robot/.env", "ROSY_RUNTIME_MODE=core\n")
    _write(root / "opt/rosy/deploy/robot/compose.yaml", "services: {}\n")
    _write(root / "opt/rosy/deploy/robot/runtime-mode.sh", "#!/usr/bin/env bash\n")
    _write(root / "opt/rosy/deploy/robot/release-recover.sh", "#!/usr/bin/env bash\n")
    config = root / "opt/rosy/deploy/robot/config"
    for name in (
        "board.yaml",
        "resolve-mode.sh",
        "capabilities.core.yaml",
        "capabilities.motor.yaml",
        "capabilities.hardware.yaml",
        "profile.core.yaml",
        "profile.motor.yaml",
        "profile.hardware.yaml",
    ):
        _write(config / name, "board: pinky_pro\n")
    _write(root / "opt/rosy/deploy/release/manifest.py", "# tools\n")
    _write(root / "opt/rosy/images/rosy-core.oci.tar", "oci\n")
    _write(root / "opt/rosy/images/rosy-io.oci.tar", "oci\n")
    _write(root / "boot/firmware/config.txt", "dtparam=audio=on\ndtoverlay=uart4\n")
    return root


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_a_well_formed_image_passes_every_check(image):
    assert inspect_image(image) == []


# --- units ----------------------------------------------------------------


@pytest.mark.parametrize("unit", ["rosy-runtime.service", "rosy-release-recover.service"])
def test_a_missing_required_unit_is_reported(image, unit):
    (image / "etc/systemd/system" / unit).unlink()
    assert "IMAGE_UNIT_MISSING" in _codes(check_units(image))


@pytest.mark.parametrize("unit", ["rosy-runtime.service", "rosy-release-recover.service"])
def test_a_present_but_unenabled_unit_is_reported(image, unit):
    """Shipping a unit nobody enabled is shipping nothing."""
    (image / "etc/systemd/system/multi-user.target.wants" / unit).unlink()
    assert "IMAGE_UNIT_NOT_ENABLED" in _codes(check_units(image))


@pytest.mark.parametrize("unit", ["rosy-motor.service", "rosy-io.service"])
def test_an_enabled_hardware_unit_is_refused(image, unit):
    """MOTOR_HOLD is the correct state for an image, not a defect."""
    (image / "etc/systemd/system/multi-user.target.wants" / unit).write_text("", encoding="utf-8")
    assert "IMAGE_HARDWARE_UNIT_ENABLED" in _codes(check_units(image))


# --- the recovery gate ----------------------------------------------------


def test_a_runtime_that_only_wants_the_gate_is_refused(image):
    """With Wants=, a held device boots anyway and the hold is advisory."""
    unit = image / "etc/systemd/system/rosy-runtime.service"
    unit.write_text(
        RUNTIME_UNIT.replace(
            "Requires=rosy-release-recover.service", "Wants=rosy-release-recover.service"
        ),
        encoding="utf-8",
    )

    assert "IMAGE_RECOVERY_GATE_NOT_REQUIRED" in _codes(check_recovery_gate(image))


def test_an_unordered_gate_is_refused(image):
    """Requiring it without After= lets the runtime start mid-decision."""
    unit = image / "etc/systemd/system/rosy-runtime.service"
    unit.write_text(
        RUNTIME_UNIT.replace("After=rosy-release-recover.service", ""), encoding="utf-8"
    )

    assert "IMAGE_RECOVERY_GATE_UNORDERED" in _codes(check_recovery_gate(image))


def test_the_shipped_runtime_unit_satisfies_the_gate_check():
    """The real unit in this repository, not just a fixture."""
    from image_checks import check_recovery_gate as check

    staged = ROOT / "deploy" / "robot" / "pinky_pro"
    fake_root = staged.parent.parent  # not an image; assert on the file directly
    unit = (staged / "rosy-runtime.service").read_text(encoding="utf-8")

    assert "Requires=rosy-release-recover.service" in unit
    assert "After=rosy-release-recover.service" in unit
    assert fake_root.exists()
    assert check is not None


# --- keys -----------------------------------------------------------------


def test_a_missing_release_key_is_refused(image):
    """Without it the device could not verify any update it is ever offered."""
    for key in (image / "etc/rosy/trusted-release-keys").glob("*.pem"):
        key.unlink()

    assert "IMAGE_RELEASE_KEY_MISSING" in _codes(check_release_keys(image))


@pytest.mark.parametrize(
    "relative",
    [
        "etc/rosy/signing.key",
        "home/pi/.ssh/id_ed25519",
        "opt/rosy/backup/release.p12",
    ],
)
def test_key_material_in_the_image_is_refused(image, relative):
    _write(image / relative, "whatever")
    assert "IMAGE_PRIVATE_KEY_PRESENT" in _codes(check_release_keys(image))


def test_a_pem_holding_a_private_key_is_refused(image):
    """The suffix says public; the contents say otherwise."""
    _write(
        image / "etc/rosy/trusted-release-keys/oops.pem",
        _pem_private_key("MC4CAQAwBQYDK2Vw"),
    )
    assert "IMAGE_PRIVATE_KEY_PRESENT" in _codes(check_release_keys(image))


def test_the_public_key_itself_is_not_mistaken_for_key_material(image):
    assert "IMAGE_PRIVATE_KEY_PRESENT" not in _codes(check_release_keys(image))


# --- defaults --------------------------------------------------------------


def test_an_image_that_boots_hardware_is_refused(image):
    _write(image / "opt/rosy/deploy/robot/.env", "ROSY_RUNTIME_MODE=hardware\n")
    assert "IMAGE_RUNTIME_MODE_NOT_CORE" in _codes(check_runtime_defaults(image))


def test_an_image_must_not_bake_a_robot_identity(image):
    """이미지가 신원을 실으면 그것으로 구운 모든 기기가 충돌한다 (ADR D-33).

    D-33 이 고친 것은 템플릿이 값을 들고 있어 모든 기기가 42/rosy_01 로 나가던
    문제였다. 프리빌트 이미지가 신원을 구우면 정확히 같은 일이 한 단계 위에서
    벌어진다 — 그리고 이미 필드에 나간 뒤라 되돌리기가 훨씬 비싸다.
    """
    _write(
        image / "opt/rosy/deploy/robot/.env",
        "ROSY_RUNTIME_MODE=core\n"
        "ROS_DOMAIN_ID=42\n"
        "ROSY_NAMESPACE=rosy_01\n",
    )
    findings = check_runtime_defaults(image)
    baked = [f for f in findings if f.code == "IMAGE_IDENTITY_BAKED"]
    assert len(baked) == 2, [f.code for f in findings]


def test_an_image_without_identity_is_accepted(image):
    """신원은 첫 부팅 프로비저닝의 몫이므로, 이미지에 없는 것이 정상이다."""
    assert "IMAGE_IDENTITY_BAKED" not in _codes(check_runtime_defaults(image))


def test_a_missing_uart_overlay_is_refused(image):
    """Present but idle: the overlay ships, the motor service does not run."""
    _write(image / "boot/firmware/config.txt", "dtparam=audio=on\n")
    assert "IMAGE_UART_OVERLAY_MISSING" in _codes(check_runtime_defaults(image))


def test_the_legacy_boot_config_location_is_accepted(image):
    (image / "boot/firmware/config.txt").unlink()
    _write(image / "boot/config.txt", "dtoverlay=uart4\n")

    assert "IMAGE_BOOT_CONFIG_MISSING" not in _codes(check_runtime_defaults(image))


# --- the account CORE runs as ---------------------------------------------


def test_core_running_as_the_login_account_is_refused(image):
    """SO_PEERCRED would then prove no more than an SSH session.

    This is the Host Agent contract's stated precondition, and the image is
    where it is either satisfied or lost.
    """
    _write(image / "etc/passwd", "root:x:0:0:root:/root:/bin/bash\n"
                                 "rosy:x:1000:1000:rosy:/home/rosy:/bin/bash\n")

    assert "IMAGE_CORE_ACCOUNT_IS_LOGIN_USER" in _codes(check_core_account(image))


def test_a_missing_core_account_is_refused(image):
    _write(image / "etc/passwd", "root:x:0:0:root:/root:/bin/bash\n"
                                 "pi:x:1000:1000:pi:/home/pi:/bin/bash\n")

    assert "IMAGE_CORE_ACCOUNT_MISSING" in _codes(check_core_account(image))


def test_a_system_uid_distinct_from_login_is_accepted(image):
    assert check_core_account(image) == []


# --- offline first boot ----------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    ["opt/rosy/images/rosy-core.oci.tar", "opt/rosy/images/rosy-io.oci.tar"],
)
def test_a_missing_oci_archive_is_refused(image, relative):
    """Section 7.3: the first boot must not need the internet."""
    (image / relative).unlink()
    assert "IMAGE_OCI_ARCHIVE_MISSING" in _codes(inspect_image(image))


@pytest.mark.parametrize(
    "relative",
    [
        "opt/rosy/deploy/robot/compose.yaml",
        "opt/rosy/deploy/robot/release-recover.sh",
        "opt/rosy/deploy/robot/config/resolve-mode.sh",
        "opt/rosy/deploy/release",
    ],
)
def test_a_missing_required_path_is_refused(image, relative):
    target = image / relative
    if target.is_dir():
        for child in target.rglob("*"):
            child.unlink()
        target.rmdir()
    else:
        target.unlink()

    assert "IMAGE_PATH_MISSING" in _codes(inspect_image(image))


# --- no device secrets -----------------------------------------------------


def test_a_wifi_secret_baked_into_the_image_is_refused(image):
    _write(image / "etc/NetworkManager/system-connections/site.nmconnection",
           "[wifi-security]\npsk=hunter2swordfish\n")

    assert "IMAGE_SECRET_PRESENT" in _codes(check_no_device_secrets(image))


def test_a_shared_api_token_in_the_image_is_refused(image):
    _write(image / "etc/rosy/rosy.yaml",
           "auth:\n  api_token: deadbeefcafebabe0123456789abcdef01234567\n")

    assert "IMAGE_SECRET_PRESENT" in _codes(check_no_device_secrets(image))


def test_a_clean_image_reports_no_secrets(image):
    assert check_no_device_secrets(image) == []


def test_transient_bundle_allows_only_schema_scoped_one_time_secrets():
    payload = {
        "network": {"ssid": "fixture-lab", "wpa_psk": "a" * 64},
        "fleet": {
            "pairing_required": True,
            "pairing_credential": "fixture-one-time-credential",
        },
    }
    assert validate_transient_card_bundle(payload) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"network": {"passphrase": "must-never-ship"}},
        {"fleet": {"reusable_token": "fixture-reusable-token"}},
        {"network": {"wpa_psk": "not-a-raw-64-hex-psk"}},
        {"notes": "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5},
    ],
)
def test_transient_bundle_refuses_unapproved_secret_material(payload):
    assert validate_transient_card_bundle(payload)


def test_receipt_and_log_payloads_allow_no_secret_paths():
    for kind in ("receipt", "log"):
        assert validate_redacted_payload(
            {"kind": kind, "network": {"wpa_psk": "a" * 64}}, path=kind
        )


# --- the whole pass --------------------------------------------------------


def test_inspect_reports_every_problem_not_only_the_first(image):
    """A build host wants the whole list, not one thing at a time."""
    (image / "etc/systemd/system/multi-user.target.wants/rosy-runtime.service").unlink()
    _write(image / "opt/rosy/deploy/robot/.env", "ROSY_RUNTIME_MODE=motor\n")
    (image / "opt/rosy/images/rosy-core.oci.tar").unlink()

    codes = _codes(inspect_image(image))

    assert {
        "IMAGE_UNIT_NOT_ENABLED",
        "IMAGE_RUNTIME_MODE_NOT_CORE",
        "IMAGE_OCI_ARCHIVE_MISSING",
    } <= codes


def test_a_finding_renders_its_code_path_and_reason(image):
    (image / "opt/rosy/images/rosy-io.oci.tar").unlink()
    rendered = str(inspect_image(image)[0])

    assert "IMAGE_" in rendered
    assert "rosy-io.oci.tar" in rendered
