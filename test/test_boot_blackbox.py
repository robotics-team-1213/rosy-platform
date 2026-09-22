"""L1 black box on the FAT32 boot partition (D-175 Task 3).

Acceptance shape: with the first card's failure, a person who inserts the card
into any PC reads the failed unit and the ModuleNotFoundError from
rosy-diag/latest.txt without elevation or an ext4 reader.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
sys.path.insert(0, str(ROOT / "deploy" / "release"))
from secret_scan import scan_text  # noqa: E402

JOURNAL_TAIL = (
    "[    7.964206] ubuntu recover-release.sh[504]: Traceback (most recent call last):\n"
    "[    7.964660] ubuntu recover-release.sh[504]: ModuleNotFoundError: No module named 'signing'\n"
    "[    7.970000] ubuntu recover-release.sh[504]: ROSY_API_" + "TOKEN=" + "Zk3q9LmT2vXw8Ab7Cd1Ef4Gh6Ij0Kl5Mn8Op3Qr\n"
    "[    8.017223] ubuntu systemd[1]: rosy-release-recover.service: Main process exited, status=1/FAILURE\n"
)
FAILED_CARD_UNITS = {
    "rosy-release-recover.service": "failed\n",
    "rosy-first-boot.service": "active\n",
    "rosy-sd-provision.service": "active\n",
    "rosy-core.service": "inactive\n",
    "rosy-runtime.target": "inactive\n",
}


def _load(name: str, filename: str):
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location(name, NATIVE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _device(tmp_path: Path, boot_id: str = "23fe37a5e32a4462bd07ec95dc392a06") -> Path:
    root = tmp_path / "device"
    (root / "boot/firmware").mkdir(parents=True)
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/device-identity.json").write_text('{"device_name": "rosy-pinky-e4us"}', encoding="utf-8")
    (root / "var/lib/rosy/provisioning").mkdir(parents=True)
    (root / "var/lib/rosy/provisioning/state.json").write_text('{"state":"PROVISIONED"}', encoding="utf-8")
    (root / "proc/sys/kernel/random").mkdir(parents=True)
    (root / "proc/sys/kernel/random/boot_id").write_text(boot_id + "\n", encoding="utf-8")
    return root


def _runner(units, calls):
    def run(command):
        calls.append(command)
        if command[:2] == ["systemctl", "show"]:
            return units.get(command[-1], "")
        if command[:1] == ["journalctl"]:
            return JOURNAL_TAIL
        if command[:2] == ["hostname", "-I"]:
            return "192.168.1.201\n"
        return ""
    return run


def _boot(root, units, when=datetime(2026, 9, 22, 13, 5, tzinfo=timezone.utc)):
    status = _load("rosy_boot_status", "rosy-boot-status.py")
    calls: list[list[str]] = []
    run = _runner(units, calls)
    facts = status.gather(root, run)
    stage = status.classify(facts["units"], facts["provisioning"])
    record = status.status_record(facts, stage, when)
    errors = status.apply(root, record, stage, run)
    return errors, calls


def test_the_first_card_failure_is_readable_from_the_boot_partition(tmp_path):
    root = _device(tmp_path)

    errors, calls = _boot(root, FAILED_CARD_UNITS)

    assert errors == []
    diag = root / "boot/firmware/rosy-diag"
    latest = (diag / "latest.txt").read_text(encoding="utf-8")
    assert "FAILED:rosy-release-recover" in latest
    assert "No module named 'signing'" in latest
    assert "rosy-pinky-e4us" in latest
    reports = sorted(diag.glob("boot-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["stage"] == "FAILED:rosy-release-recover"
    assert report["boot_id"] == "23fe37a5e32a4462bd07ec95dc392a06"
    assert ["journalctl", "-b", "-u", "rosy-release-recover.service", "-n", "60",
            "--no-pager", "-o", "short-monotonic"] in calls


def test_black_box_output_is_redacted_and_scanner_clean(tmp_path):
    root = _device(tmp_path)

    _boot(root, FAILED_CARD_UNITS)

    for path in (root / "boot/firmware/rosy-diag").iterdir():
        text = path.read_text(encoding="utf-8")
        assert "Zk3q9LmT2vXw8" not in text, path.name
        assert scan_text(f"diag/{path.name}", text) == [], path.name


def test_the_same_stage_is_written_once_per_boot(tmp_path):
    root = _device(tmp_path)
    _boot(root, FAILED_CARD_UNITS)
    report = next((root / "boot/firmware/rosy-diag").glob("boot-*.json"))
    first = report.stat().st_mtime_ns

    _errors, calls = _boot(root, FAILED_CARD_UNITS, when=datetime(2026, 9, 22, 13, 6, tzinfo=timezone.utc))

    assert report.stat().st_mtime_ns == first
    assert not [c for c in calls if c[:1] == ["journalctl"]]


def test_a_stage_change_updates_the_same_boot_report(tmp_path):
    root = _device(tmp_path)
    booting = {unit: "activating\n" for unit in FAILED_CARD_UNITS}
    _boot(root, booting)

    _boot(root, FAILED_CARD_UNITS)

    reports = sorted((root / "boot/firmware/rosy-diag").glob("boot-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["stage"] == "FAILED:rosy-release-recover"


def test_only_the_last_five_boots_are_kept(tmp_path):
    root = _device(tmp_path)
    for index in range(7):
        (root / "proc/sys/kernel/random/boot_id").write_text(f"{index:08x}{0:024x}\n", encoding="utf-8")
        _boot(root, FAILED_CARD_UNITS)

    reports = sorted((root / "boot/firmware/rosy-diag").glob("boot-*.json"))

    assert len(reports) == 5
    assert json.loads(reports[-1].read_text(encoding="utf-8"))["boot_id"] == f"{6:08x}{0:024x}"


def test_black_box_stays_under_its_size_cap(tmp_path, monkeypatch):
    blackbox = _load("rosy_blackbox", "rosy_blackbox.py")
    record = {"stage": "FAILED:rosy-core", "boot_id": "b" * 32, "device_name": "rosy-pinky-e4us",
              "release_id": "2026.09.22-003", "ipv4": [], "failed_unit": "rosy-core.service",
              "detail": None, "updated_at": "2026-09-23T00:00:00Z", "units": {}}
    huge = {"rosy-core.service": ["x" * 4000] * 60}
    boot = tmp_path / "boot/firmware"
    boot.mkdir(parents=True)

    blackbox.write(boot, record, huge)

    total = sum(path.stat().st_size for path in (boot / "rosy-diag").iterdir())
    assert total <= blackbox.TOTAL_CAP_BYTES


def test_no_boot_partition_means_no_black_box_and_no_error(tmp_path):
    root = _device(tmp_path)
    (root / "boot/firmware").rmdir()

    errors, _calls = _boot(root, FAILED_CARD_UNITS)

    assert errors == []
    assert not (root / "boot/firmware/rosy-diag").exists()


def test_a_crash_loop_does_not_keep_rewriting_the_boot_partition(tmp_path):
    # Review M6: FAILED and PROVISIONED alternated during a CORE restart loop.
    root = _device(tmp_path)
    starting = dict(FAILED_CARD_UNITS, **{"rosy-release-recover.service": "active\n",
                                          "rosy-core.service": "activating\n"})
    crashed = dict(starting, **{"rosy-core.service": "failed\n"})
    _boot(root, crashed)
    report = next((root / "boot/firmware/rosy-diag").glob("boot-*.json"))
    first = report.stat().st_mtime_ns

    for units in (starting, crashed, starting, crashed):
        _boot(root, units)

    assert report.stat().st_mtime_ns == first
    assert json.loads(report.read_text(encoding="utf-8"))["stage"] == "FAILED:rosy-core"


def test_recovery_to_ready_is_always_recorded(tmp_path):
    root = _device(tmp_path)
    _boot(root, FAILED_CARD_UNITS)
    ready = {unit: "active\n" for unit in FAILED_CARD_UNITS}

    _boot(root, ready)

    report = next((root / "boot/firmware/rosy-diag").glob("boot-*.json"))
    assert json.loads(report.read_text(encoding="utf-8"))["stage"] == "CORE_READY"


def test_report_numbers_sort_numerically_past_four_digits(tmp_path):
    blackbox = _load("rosy_blackbox", "rosy_blackbox.py")
    boot = tmp_path / "boot/firmware"
    (boot / "rosy-diag").mkdir(parents=True)
    (boot / "rosy-diag/boot-9999-aaaaaaaa.json").write_text('{"stage": "X"}', encoding="utf-8")
    record = {"stage": "FAILED:rosy-core", "boot_id": "b" * 32, "units": {}}

    written = blackbox.write(boot, record, {})

    assert written.name == "boot-010000-bbbbbbbb.json"
    assert {p.name for p in (boot / "rosy-diag").glob("boot-*.json")} >= {written.name, "boot-9999-aaaaaaaa.json"}
