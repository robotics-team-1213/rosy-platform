"""The native product runtime addresses the motor bus as /dev/rosy-motor.

`rosy-io.service`/`rosy-navigation.service` hardcode
`DeviceAllow=/dev/rosy-motor` and `motor_device:=/dev/rosy-motor`, but no
udev rule ever created that name on the host — the compose device mapping
was the only thing that did, and compose is development-only (D-161).
Without this rule the native I/O service cannot open the motor bus at all.

Contract (communication-protocol report 2026-09-22 §8-F / remediation plan T3):
the rule ships in-tree, the native image bakes it into /etc/udev/rules.d,
and configure-uart-pi5.sh retrofits it on existing devices (the alias is
meaningless without the UART4 overlay that script owns).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULE = ROOT / "deploy" / "robot" / "udev" / "99-rosy-motor.rules"
UART_SCRIPT = ROOT / "deploy" / "robot" / "configure-uart-pi5.sh"
PAYLOAD = ROOT / "deploy" / "image" / "build-native-payload.sh"
IO_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-io.service"
NAV_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-navigation.service"
VERIFY_MOTORS = ROOT / "deploy" / "robot" / "verify" / "verify-motors.sh"


def test_rule_creates_stable_alias():
    text = RULE.read_text(encoding="utf-8")
    assert 'KERNEL=="ttyAMA4"' in text
    assert 'SYMLINK+="rosy-motor"' in text
    assert 'GROUP="dialout"' in text
    assert 'MODE="0660"' in text


def test_uart_script_installs_rule_before_idempotent_exit():
    """Both paths (already configured / adding overlay) must install the rule,
    so the call has to run before the early-exit PASS."""
    text = UART_SCRIPT.read_text(encoding="utf-8")
    assert "99-rosy-motor.rules" in text
    assert "/etc/udev/rules.d" in text
    # Find the top-level call on its own line, not the `() {` definition.
    call_site = text.find("\ninstall_motor_udev_rule\n")
    exit_pos = text.find("is already configured")
    assert 0 < call_site < exit_pos, (
        "install_motor_udev_rule must run before the already-configured "
        "early exit so re-runs on provisioned devices still get the rule")


def test_native_image_bakes_the_rule():
    text = PAYLOAD.read_text(encoding="utf-8")
    assert "udev/99-rosy-motor.rules" in text
    assert "etc/udev/rules.d" in text


def test_native_units_and_probe_agree_on_the_alias():
    for unit in (IO_UNIT, NAV_UNIT):
        text = unit.read_text(encoding="utf-8")
        assert "DeviceAllow=/dev/rosy-motor rw" in text, unit
        assert "motor_device:=/dev/rosy-motor" in text, unit
    assert "/dev/rosy-motor" in VERIFY_MOTORS.read_text(encoding="utf-8")
