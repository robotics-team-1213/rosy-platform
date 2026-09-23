from __future__ import annotations

import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "sd" / "prepare-rosy-sd.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
sys.path.insert(0, str(ROOT / "deploy" / "release"))
from signing import build_sha256sums, sign_checksums  # noqa: E402


def _disk(**overrides):
    disk = {
        "Number": 7,
        "FriendlyName": "Fixture USB SD Reader",
        "SerialNumber": "FIXTURE-SD-0007",
        "Size": 32 * 1024**3,
        "BusType": "USB",
        "IsBoot": False,
        "IsSystem": False,
        "IsOffline": False,
        "IsReadOnly": False,
    }
    disk.update(overrides)
    return disk


@pytest.fixture
def writer_case(tmp_path: Path):
    release = tmp_path / "release"
    release.mkdir()
    image = release / "rosy-os-pinky-pro-2026.09.21-001-arm64.img.xz"
    raw_image = tmp_path / "raw-image.bin"
    raw_image.write_bytes(b"fixture rosy image\n" * 4096)
    image.write_bytes(lzma.compress(raw_image.read_bytes()))
    manifest = release / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "release_id": "2026.09.21-001",
        "product": "rosy-os",
        "board": "pinky_pro",
        "architecture": "arm64",
        "image": {
            "filename": image.name,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        },
    }, sort_keys=True), encoding="utf-8")
    private_key = tmp_path / "release-private.pem"
    public_key = tmp_path / "release-public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
        check=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        check=True,
    )
    sums = build_sha256sums(release, ["manifest.json", image.name])
    (release / "SHA256SUMS").write_bytes(sums)
    signature = release / "SHA256SUMS.sig"
    signature.write_text(sign_checksums(sums, private_key), encoding="utf-8")
    inventory = tmp_path / "disks.json"
    inventory.write_text(json.dumps([_disk()]), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps({"robot_numbers": [], "device_names": [], "device_uids": []}),
        encoding="utf-8",
    )
    marker = tmp_path / "writer-called.txt"
    writer_args = tmp_path / "writer-args.txt"
    fake_writer = tmp_path / "fake-writer.cmd"
    fake_writer.write_text(
        f'@echo off\n> "{marker}" echo called\n> "{writer_args}" echo %*\nexit /b 0\n',
        encoding="utf-8",
    )
    local_app_data = tmp_path / "local-app-data"
    credential_dir = local_app_data / "Rosy" / "credentials"
    credential_dir.mkdir(parents=True)
    credential = credential_dir / "fixture-profile.credential.xml"
    command = (
        "$s=ConvertTo-SecureString ('fixture-'+'writer-pass') -AsPlainText -Force;"
        "$c=[pscredential]::new('fixture-ssid',$s);"
        f"$c|Export-Clixml -LiteralPath '{credential}'"
    )
    subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], check=True)
    return {
        "image": image,
        "signature": signature,
        "public_key": public_key,
        "private_key": private_key,
        "inventory": inventory,
        "registry": registry,
        "marker": marker,
        "writer_args": writer_args,
        "writer": fake_writer,
        "receipt": tmp_path / "receipt.json",
        "readback": raw_image,
        "env": {**os.environ, "LOCALAPPDATA": str(local_app_data)},
    }


def _run(case, *extra, plan_only=True, omit=()):
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT),
        "-DiskNumber", "7",
        "-RobotNumber", "1",
        "-Model", "pinky_pro",
        "-Preset", "hardware",
        "-WifiProfile", "fixture-profile",
        "-ImagePath", str(case["image"]),
        "-ImageSha256", hashlib.sha256(case["image"].read_bytes()).hexdigest(),
        "-ImageSignaturePath", str(case["signature"]),
        "-ReleasePublicKey", str(case["public_key"]),
        "-ReleaseId", "2026.09.21-001",
        "-FleetEndpoint", "https://fleet.fixture.invalid:8443",
        "-FleetTrustProfile", "site-ca-2026",
        "-DiskInventoryJson", str(case["inventory"]),
        "-RegistryJson", str(case["registry"]),
        "-ReceiptPath", str(case["receipt"]),
        "-RpiImager", str(case["writer"]),
        "-ReadbackDevice", str(case["readback"]),
        "-DeviceName", "rosy-pinky-k7m4",
        "-DeviceUid", "9d40feaa-871f-4fd3-975a-a704e82d3af9",
    ]
    for name in omit:
        index = command.index(name)
        del command[index:index + 2]
    if plan_only:
        command.append("-PlanOnly")
    extra_values = list(map(str, extra))
    index = 0
    while index < len(extra_values):
        name = extra_values[index]
        value = extra_values[index + 1]
        if name in command:
            command[command.index(name) + 1] = value
        else:
            command.extend((name, value))
        index += 2
    return subprocess.run(command, capture_output=True, text=True, env=case["env"])


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_plan_only_prints_a_redacted_physical_disk_plan(writer_case):
    completed = _run(writer_case)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["physical_drive"] == r"\\.\PhysicalDrive7"
    assert plan["device_name"] == "rosy-pinky-k7m4"
    assert plan["mode"] == "PLAN_ONLY"
    assert "writer-pass" not in completed.stdout + completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    "change",
    [
        {"IsBoot": True},
        {"IsSystem": True},
        {"BusType": "SATA"},
        {"IsOffline": True},
        {"IsReadOnly": True},
        {"Size": 4 * 1024**3},
        {"SerialNumber": ""},
    ],
)
def test_unsafe_disk_is_rejected_without_invoking_writer(writer_case, change):
    writer_case["inventory"].write_text(json.dumps([_disk(**change)]), encoding="utf-8")

    completed = _run(writer_case)

    assert completed.returncode != 0
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_disk_drift_between_probes_is_rejected(writer_case, tmp_path):
    second = tmp_path / "second.json"
    second.write_text(json.dumps([_disk(SerialNumber="CHANGED-SERIAL")]), encoding="utf-8")

    completed = _run(writer_case, "-SecondDiskInventoryJson", second)

    assert completed.returncode != 0
    assert "changed between safety probes" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("field", "value"),
    [("robot_numbers", [1]), ("device_names", ["rosy-pinky-k7m4"]),
     ("device_uids", ["9d40feaa-871f-4fd3-975a-a704e82d3af9"])],
)
def test_registry_reuse_is_rejected(writer_case, field, value):
    registry = {"robot_numbers": [], "device_names": [], "device_uids": []}
    registry[field] = value
    writer_case["registry"].write_text(json.dumps(registry), encoding="utf-8")

    completed = _run(writer_case)

    assert completed.returncode != 0
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("missing", ["hash", "signature"])
def test_image_integrity_companions_are_required(writer_case, missing):
    if missing == "signature":
        writer_case["signature"].unlink()
        completed = _run(writer_case)
    else:
        completed = _run(writer_case, "-ImageSha256", "invalid")

    assert completed.returncode != 0
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_existing_receipt_is_never_overwritten(writer_case):
    writer_case["receipt"].write_text("existing evidence\n", encoding="utf-8")

    completed = _run(writer_case)

    assert completed.returncode != 0
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_wrong_confirmation_never_invokes_writer(writer_case):
    completed = _run(
        writer_case,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-wrong",
        plan_only=False,
    )

    assert completed.returncode != 0
    assert "confirmation did not match" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_invalid_release_signature_is_rejected_before_disk_discovery(writer_case):
    writer_case["signature"].write_text("invalid-signature\n", encoding="utf-8")

    completed = _run(writer_case)

    assert completed.returncode != 0
    assert "signed image release verification failed" in completed.stderr.lower()
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_manifest_identity_mismatch_is_rejected_before_writer(writer_case):
    manifest = writer_case["image"].parent / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["board"] = "not-pinky"
    manifest.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    sums = build_sha256sums(manifest.parent, ["manifest.json", writer_case["image"].name])
    (manifest.parent / "SHA256SUMS").write_bytes(sums)
    writer_case["signature"].write_text(
        sign_checksums(sums, writer_case["private_key"]), encoding="utf-8"
    )

    completed = _run(writer_case)

    assert completed.returncode != 0
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_successful_write_stages_one_time_bundle_and_updates_registry(writer_case, tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()
    completed = _run(
        writer_case,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        "-BootMountPath", boot,
        plan_only=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert writer_case["marker"].exists()
    writer_arguments = writer_case["writer_args"].read_text(encoding="utf-8")
    raw_sha256 = hashlib.sha256(writer_case["readback"].read_bytes()).hexdigest()
    compressed_sha256 = hashlib.sha256(writer_case["image"].read_bytes()).hexdigest()
    assert f"--sha256 {raw_sha256}" in writer_arguments
    assert f"--sha256 {compressed_sha256}" not in writer_arguments
    bundle_path = boot / "rosy-provision" / "provision.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
    assert bundle["device_identity"]["device_name"] == "rosy-pinky-k7m4"
    assert bundle["network"]["ssid"] == "fixture-ssid"
    assert len(bundle["network"]["wpa_psk"]) == 64
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    registry = json.loads(writer_case["registry"].read_text(encoding="utf-8-sig"))
    rendered = completed.stdout + completed.stderr + json.dumps(receipt)
    assert "fixture-writer-pass" not in rendered
    assert "wpa_psk" not in json.dumps(receipt)
    assert receipt["media_readback"]["verified"] is True
    assert receipt["media_readback"]["bytes_verified"] == writer_case["readback"].stat().st_size
    assert registry["robot_numbers"] == [1]
    assert registry["device_names"] == ["rosy-pinky-k7m4"]
    assert registry["device_uids"] == ["9d40feaa-871f-4fd3-975a-a704e82d3af9"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_readback_mismatch_stops_before_personalization_and_receipt(writer_case, tmp_path):
    writer_case["readback"].write_bytes(b"wrong media contents")
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(
        writer_case,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        "-BootMountPath", boot,
        plan_only=False,
    )

    assert completed.returncode != 0
    assert writer_case["marker"].exists()
    assert not (boot / "rosy-provision" / "provision.json").exists()
    assert not writer_case["receipt"].exists()
    registry = json.loads(writer_case["registry"].read_text(encoding="utf-8"))
    assert registry == {"robot_numbers": [], "device_names": [], "device_uids": []}


def test_script_has_no_plain_password_or_shell_string_escape_hatch():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "WifiPassword" not in text
    assert "Export-Clixml" in text and "Import-Clixml" in text
    assert "Read-Host -AsSecureString" in text
    assert "--cli" in text and "--sha256" in text
    assert "--disable-verify" not in text
    assert "cmd /c" not in text.lower()
    assert '"ERASE SERIAL $($firstDisk.SerialNumber) $DeviceName"' in text
    assert "Start-Process" in text
    assert "-Wait" in text
    assert "-PassThru" in text
    assert "& $RpiImager" not in text
    assert "create-provision-bundle.py" in text
    assert "BootMountPath" in text
    assert "GetNetworkCredential().Password" in text
    verify_call = text.index("verify-image-release.py")
    disk_probe = text.index("$firstDisk = Select-SafeDisk")
    assert verify_call < disk_probe
    assert "ReleasePublicKey" in text
    assert "verify-media-readback.py" in text
    assert text.index("verify-media-readback.py") < text.index("create-provision-bundle.py")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_omitted_robot_number_is_drawn_from_free_registry_slots(writer_case):
    taken = [number for number in range(1, 62) if number not in (17, 42)]
    writer_case["registry"].write_text(
        json.dumps({"robot_numbers": taken, "device_names": [], "device_uids": []}),
        encoding="utf-8",
    )

    drawn = set()
    for _ in range(6):
        completed = _run(writer_case, omit=("-RobotNumber",))
        assert completed.returncode == 0, completed.stderr
        plan = json.loads(completed.stdout)
        assert plan["robot_number_source"] == "auto"
        assert plan["ros_domain_id"] == 40 + plan["robot_number"]
        assert plan["namespace"] == "rosy_{:02d}".format(plan["robot_number"])
        drawn.add(plan["robot_number"])

    assert drawn <= {17, 42}
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_full_registry_refuses_automatic_robot_number(writer_case):
    writer_case["registry"].write_text(
        json.dumps({"robot_numbers": list(range(1, 62)), "device_names": [], "device_uids": []}),
        encoding="utf-8",
    )

    completed = _run(writer_case, omit=("-RobotNumber",))

    assert completed.returncode != 0
    assert "no free robot number" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_explicit_robot_number_is_reported_as_operator_choice(writer_case):
    completed = _run(writer_case)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["robot_number"] == 1
    assert plan["robot_number_source"] == "operator"
    assert plan["fleet_source"] == "operator"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_omitted_fleet_values_default_to_this_console_host(writer_case):
    completed = _run(writer_case, omit=("-FleetEndpoint", "-FleetTrustProfile"))

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    host = os.environ["COMPUTERNAME"].lower()
    assert plan["fleet_endpoint"] == f"https://{host}.local"
    assert plan["fleet_trust_profile"] == "rosy-pilot-lan"
    assert plan["fleet_source"] == "default"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_plan_file_is_written_once_and_matches_stdout(writer_case, tmp_path):
    plan_path = tmp_path / "plan.json"

    completed = _run(writer_case, "-PlanPath", plan_path, omit=("-RobotNumber", "-DeviceName", "-DeviceUid"))

    assert completed.returncode == 0, completed.stderr
    saved = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    assert saved == json.loads(completed.stdout)
    assert "writer-pass" not in plan_path.read_text(encoding="utf-8-sig")

    again = _run(writer_case, "-PlanPath", plan_path)
    assert again.returncode != 0
    assert "plan already exists" in again.stderr
    assert json.loads(plan_path.read_text(encoding="utf-8-sig")) == saved


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_write_reuses_the_reviewed_plan_identity(writer_case, tmp_path):
    plan_path = tmp_path / "plan.json"
    planned = _run(writer_case, "-PlanPath", plan_path, omit=("-RobotNumber", "-DeviceName", "-DeviceUid"))
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(
        writer_case,
        "-PlanPath", plan_path,
        "-Confirmation", f"ERASE SERIAL FIXTURE-SD-0007 {plan['device_name']}",
        "-BootMountPath", boot,
        plan_only=False,
        omit=("-RobotNumber", "-DeviceName", "-DeviceUid"),
    )

    assert completed.returncode == 0, completed.stderr
    registry = json.loads(writer_case["registry"].read_text(encoding="utf-8-sig"))
    assert registry["robot_numbers"] == [plan["robot_number"]]
    assert registry["device_names"] == [plan["device_name"]]
    assert registry["device_uids"] == [plan["device_uid"]]
    bundle = json.loads((boot / "rosy-provision" / "provision.json").read_text(encoding="utf-8-sig"))
    assert bundle["dds"]["robot_number"] == plan["robot_number"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("disk_serial", "OTHER-CARD-0001"),
        ("image_sha256", "0" * 64),
        ("release_id", "2026.09.21-002"),
        ("mode", "WRITE"),
        ("wifi_ssid", "FIXTURE-SSID"),
        ("namespace", "rosy_02"),
        ("ros_domain_id", 42),
        ("registry_path", r"C:\other\registry.json"),
    ],
)
def test_write_refuses_a_plan_that_no_longer_matches(writer_case, tmp_path, field, value):
    plan_path = tmp_path / "plan.json"
    planned = _run(writer_case, "-PlanPath", plan_path)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    plan[field] = value
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    completed = _run(
        writer_case,
        "-PlanPath", plan_path,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        plan_only=False,
    )

    assert completed.returncode != 0
    assert "reviewed plan" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_write_refuses_explicit_identity_that_contradicts_the_plan(writer_case, tmp_path):
    plan_path = tmp_path / "plan.json"
    planned = _run(writer_case, "-PlanPath", plan_path)
    assert planned.returncode == 0, planned.stderr

    completed = _run(
        writer_case,
        "-PlanPath", plan_path,
        "-RobotNumber", "9",
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        plan_only=False,
    )

    assert completed.returncode != 0
    assert "reviewed plan" in completed.stderr
    assert not writer_case["marker"].exists()


def _plan_then_write(case, tmp_path, mutate=None, *extra, omit=()):
    plan_path = tmp_path / "plan.json"
    planned = _run(case, "-PlanPath", plan_path)
    assert planned.returncode == 0, planned.stderr
    if mutate is not None:
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        mutate(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return _run(
        case,
        "-PlanPath", plan_path,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        *extra,
        plan_only=False,
        omit=omit,
    )


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("-DeviceName", "ROSY-PINKY-K7M4"),
        ("-FleetEndpoint", "https://FLEET.fixture.invalid:8443"),
        ("-Preset", "core"),
        ("-CountryCode", "US"),
    ],
)
def test_write_refuses_arguments_that_differ_from_the_plan_even_by_case(writer_case, tmp_path, name, value):
    completed = _plan_then_write(writer_case, tmp_path, None, name, value)

    assert completed.returncode != 0
    assert "contradicts the reviewed plan" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_automatic_robot_number_is_never_drawn_inside_a_write(writer_case, tmp_path):
    completed = _run(
        writer_case,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
        "-BootMountPath", tmp_path,
        plan_only=False,
        omit=("-RobotNumber",),
    )

    assert completed.returncode != 0
    assert "needs a reviewed plan" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_tampered_plan_robot_number_is_rejected_before_writer(writer_case, tmp_path):
    def tamper(plan):
        plan.update(robot_number=75, robot_number_source="auto", ros_domain_id=115, namespace="rosy_75")

    completed = _plan_then_write(writer_case, tmp_path, tamper, omit=("-RobotNumber",))

    assert completed.returncode != 0
    assert "between 1 and 61" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("key", ["robot_number_source", "requested_preset", "registry_path"])
def test_plan_missing_a_field_fails_with_its_name(writer_case, tmp_path, key):
    completed = _plan_then_write(writer_case, tmp_path, lambda plan: plan.pop(key))

    assert completed.returncode != 0
    assert f"reviewed plan has no {key}" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_plan_records_preset_model_country_and_registry(writer_case):
    completed = _run(writer_case)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["model"] == "pinky_pro"
    assert plan["requested_preset"] == "hardware"
    assert plan["country_code"] == "KR"
    assert Path(plan["registry_path"]) == writer_case["registry"].resolve()


def _operator_key_file(tmp_path, seed=7):
    import base64
    import struct

    def string(value):
        return struct.pack(">I", len(value)) + value

    blob = string(b"ssh-ed25519") + string(bytes([seed]) * 32)
    key = f"ssh-ed25519 {base64.b64encode(blob).decode()} operator@bench"
    path = tmp_path / f"operator-{seed}.pub"
    path.write_text(key + "\n", encoding="utf-8")
    return path, key


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_operator_key_is_fingerprinted_in_the_plan_and_installed_on_write(writer_case, tmp_path):
    # D-174 F3: the card carries a key-only operator login; the plan pins its fingerprint.
    key_file, key = _operator_key_file(tmp_path)
    plan_path = tmp_path / "plan.json"
    planned = _run(writer_case, "-PlanPath", plan_path, "-OperatorPublicKey", key_file)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    assert plan["operator_key_fingerprint"].startswith("SHA256:")
    assert key.split()[1] not in plan_path.read_text(encoding="utf-8-sig")
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(
        writer_case, "-PlanPath", plan_path, "-OperatorPublicKey", key_file,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4", "-BootMountPath", boot,
        plan_only=False,
    )

    assert completed.returncode == 0, completed.stderr
    bundle = json.loads((boot / "rosy-provision/provision.json").read_text(encoding="utf-8-sig"))
    assert bundle["operator"] == {"ssh_authorized_keys": [key]}
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["personalization"]["operator"]["ssh_key_fingerprints"] == [plan["operator_key_fingerprint"]]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_different_operator_key_than_reviewed_stops_before_the_writer(writer_case, tmp_path):
    reviewed, _ = _operator_key_file(tmp_path, seed=7)
    other, _ = _operator_key_file(tmp_path, seed=9)
    plan_path = tmp_path / "plan.json"
    assert _run(writer_case, "-PlanPath", plan_path, "-OperatorPublicKey", reviewed).returncode == 0

    completed = _run(
        writer_case, "-PlanPath", plan_path, "-OperatorPublicKey", other,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4", plan_only=False,
    )

    assert completed.returncode != 0
    assert "operator_key_fingerprint" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_private_key_file_is_refused_as_an_operator_key(writer_case, tmp_path):
    bad = tmp_path / "id_ed25519"
    bad.write_text("-----BEGIN OPENSSH " + "PRIVATE KEY-----\n", encoding="utf-8")

    completed = _run(writer_case, "-OperatorPublicKey", bad)

    assert completed.returncode != 0
    assert "operator public key" in completed.stderr


def _prior_receipt(tmp_path, **overrides):
    receipt = {
        "device_uid": "9d40feaa-871f-4fd3-975a-a704e82d3af9",
        "device_name": "rosy-pinky-k7m4",
        "robot_number": 1,
        "release_id": "2026.09.20-001",
        "disk_serial": "FIXTURE-SD-0007",
        "image_sha256": "a" * 64,
        "writer_exit_code": 0,
        "media_readback": {"verified": True},
        "created_at": "2026-09-22T13:04:48+00:00",
    }
    receipt.update(overrides)
    path = tmp_path / "prior-receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def _registered(case):
    case["registry"].write_text(json.dumps({
        "robot_numbers": [1], "device_names": ["rosy-pinky-k7m4"],
        "device_uids": ["9d40feaa-871f-4fd3-975a-a704e82d3af9"],
    }), encoding="utf-8")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_registered_identity_can_be_rewritten_only_with_its_prior_receipt(writer_case, tmp_path):
    # D-174 F7: the same robot gets a fixed release on the same identity.
    _registered(writer_case)
    prior = _prior_receipt(tmp_path)
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(
        writer_case, "-ReprovisionReceipt", prior,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4", "-BootMountPath", boot,
        plan_only=False,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["supersedes"] == {
        "release_id": "2026.09.20-001", "image_sha256": "a" * 64,
        "created_at": "2026-09-22T13:04:48+00:00",
    }
    registry = json.loads(writer_case["registry"].read_text(encoding="utf-8-sig"))
    assert registry["robot_numbers"] == [1]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_reprovision_plan_takes_the_identity_from_the_receipt(writer_case, tmp_path):
    _registered(writer_case)
    prior = _prior_receipt(tmp_path)

    completed = _run(writer_case, "-ReprovisionReceipt", prior,
                     omit=("-RobotNumber", "-DeviceName", "-DeviceUid"))

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert (plan["device_name"], plan["robot_number"]) == ("rosy-pinky-k7m4", 1)
    assert plan["robot_number_source"] == "reprovision"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    "overrides",
    [
        {"robot_number": 2},
        {"device_name": "rosy-pinky-zzzz"},
        {"writer_exit_code": 1},
        {"media_readback": {"verified": False}},
    ],
)
def test_reprovision_refuses_a_receipt_that_does_not_prove_this_identity(writer_case, tmp_path, overrides):
    _registered(writer_case)
    prior = _prior_receipt(tmp_path, **overrides)

    completed = _run(writer_case, "-ReprovisionReceipt", prior)

    assert completed.returncode != 0
    assert "reprovision receipt" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_reprovision_receipt_cannot_launder_another_plans_identity(writer_case, tmp_path):
    # Review M1: the plan replaced the receipt's identity and every registry check was skipped.
    _registered(writer_case)
    prior = _prior_receipt(tmp_path)
    plan_path = tmp_path / "plan-robot-20.json"
    planned = _run(writer_case, "-PlanPath", plan_path, "-RobotNumber", "20",
                   "-DeviceName", "rosy-pinky-abcd", "-DeviceUid", "11111111-2222-4333-8444-555555555555")
    assert planned.returncode == 0, planned.stderr

    completed = _run(
        writer_case, "-PlanPath", plan_path, "-ReprovisionReceipt", prior,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-abcd", plan_only=False,
        omit=("-RobotNumber", "-DeviceName", "-DeviceUid"),
    )

    assert completed.returncode != 0
    assert "reprovision receipt" in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_reprovision_requires_the_identity_to_be_registered(writer_case, tmp_path):
    prior = _prior_receipt(tmp_path)  # registry is empty in the fixture

    completed = _run(writer_case, "-ReprovisionReceipt", prior)

    assert completed.returncode != 0
    assert "reprovision receipt" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    "overrides",
    [{"writer_exit_code": None}, {"writer_exit_code": "0"}, {"media_readback": {"verified": "false"}},
     {"media_readback": {"verified": 1}}],
    ids=["exit-null", "exit-string", "verified-string", "verified-int"],
)
def test_reprovision_proof_fields_are_strictly_typed(writer_case, tmp_path, overrides):
    # Review M2: [bool]"false" is True and [int]$null is 0 in PowerShell 5.1.
    _registered(writer_case)
    prior = _prior_receipt(tmp_path, **overrides)

    completed = _run(writer_case, "-ReprovisionReceipt", prior)

    assert completed.returncode != 0
    assert "reprovision receipt" in completed.stderr


def test_operator_key_is_passed_as_an_argument_not_through_the_console():
    # Release 004 plan: piping the key through PowerShell 5.1 prepended a BOM and
    # the real key was refused; the fixture run had no console and passed.
    text = SCRIPT.read_text(encoding="utf-8")

    assert "operator_key_fingerprint(sys.argv[1])" in text
    assert "$operatorKey | &" not in text


def test_the_writer_never_tries_to_offline_removable_media():
    # Release 004 retry: "Removable media cannot be set to offline." Mount metadata
    # is tolerated by verify-media-readback.py instead (see test_media_readback.py).
    text = SCRIPT.read_text(encoding="utf-8")

    assert "-IsOffline $true" not in text
    assert "$mediaReadbackOutput = & $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget" in text


# --- Disk selected by serial, not by Windows disk number -------------------
# Release 004: another USB device disappeared, the card moved from disk 2 to
# disk 1, and a reviewed plan pinned to the number could no longer be written.


def _inventory(case, *disks):
    case["inventory"].write_text(json.dumps(list(disks)), encoding="utf-8")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_reviewed_plan_follows_its_card_to_a_new_disk_number(writer_case, tmp_path):
    plan_path = tmp_path / "plan.json"
    planned = _run(writer_case, "-PlanPath", plan_path)
    assert planned.returncode == 0, planned.stderr
    _inventory(writer_case, _disk(Number=3), _disk(Number=5, SerialNumber="OTHER-CARD", Size=16 * 1024**3))
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(
        writer_case, "-PlanPath", plan_path,
        "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4", "-BootMountPath", boot,
        plan_only=False, omit=("-DiskNumber",),
    )

    assert completed.returncode == 0, completed.stderr
    assert "PhysicalDrive3" in writer_case["writer_args"].read_text(encoding="utf-8")
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["disk_serial"] == "FIXTURE-SD-0007"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_disk_serial_selects_the_card_without_a_number(writer_case):
    _inventory(writer_case, _disk(Number=4))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert (plan["disk_number"], plan["disk_serial"]) == (4, "FIXTURE-SD-0007")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("disks", "message"),
    [
        ([], "no USB disk has serial"),
        ([{"Number": 3}, {"Number": 4}], "more than one USB disk has serial"),
    ],
    ids=["missing", "duplicated"],
)
def test_a_serial_must_resolve_to_exactly_one_usb_disk(writer_case, disks, message):
    _inventory(writer_case, *[_disk(**disk) for disk in disks])

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_number_and_serial_that_disagree_are_refused(writer_case):
    _inventory(writer_case, _disk(Number=3), _disk(Number=7, SerialNumber="OTHER-CARD"))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007")  # -DiskNumber 7 is the other card

    assert completed.returncode != 0
    assert "does not match -DiskSerial" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_old_number_based_confirmation_is_refused(writer_case, tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(writer_case, "-Confirmation", "ERASE DISK 7 rosy-pinky-k7m4",
                     "-BootMountPath", boot, plan_only=False)

    assert completed.returncode != 0
    assert "confirmation did not match" in completed.stderr
    assert not writer_case["marker"].exists()


# --- Fallback AP credentials and the editable settings file (D-176 Task 3) --


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_each_card_gets_a_stored_random_ap_password_and_a_settings_template(writer_case, tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(writer_case, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
                     "-BootMountPath", boot, plan_only=False)

    assert completed.returncode == 0, completed.stderr
    bundle = json.loads((boot / "rosy-provision/provision.json").read_text(encoding="utf-8-sig"))
    ap = bundle["network"]["ap"]
    assert ap["ssid"] == "rosy-pinky-k7m4" and len(ap["password"]) == 14
    store = Path(writer_case["env"]["LOCALAPPDATA"]) / "Rosy/ap/rosy-pinky-k7m4.credential.xml"
    assert store.is_file() and ap["password"] not in store.read_text(encoding="utf-16")  # DPAPI, not plaintext
    receipt_text = writer_case["receipt"].read_text(encoding="utf-8-sig")
    assert ap["password"] not in receipt_text and ap["password"] not in completed.stdout
    assert ap["password"] in completed.stderr  # shown once to the operator
    template = (boot / "rosy-config.yaml").read_text(encoding="utf-8")
    assert template.startswith("# ROSY robot settings (D-176)")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_rewriting_the_same_device_keeps_its_ap_password_and_an_edited_settings_file(writer_case, tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()
    assert _run(writer_case, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
                "-BootMountPath", boot, plan_only=False).returncode == 0
    first = json.loads((boot / "rosy-provision/provision.json").read_text(encoding="utf-8-sig"))["network"]["ap"]
    (boot / "rosy-provision/provision.json").unlink()
    (boot / "rosy-config.yaml").write_text("schema_version: 1\ncountry: US\n", encoding="utf-8")
    writer_case["receipt"].unlink()
    writer_case["registry"].write_text(json.dumps({"robot_numbers": [], "device_names": [], "device_uids": []}),
                                       encoding="utf-8")

    completed = _run(writer_case, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
                     "-BootMountPath", boot, plan_only=False)

    assert completed.returncode == 0, completed.stderr
    second = json.loads((boot / "rosy-provision/provision.json").read_text(encoding="utf-8-sig"))["network"]["ap"]
    assert second == first
    assert (boot / "rosy-config.yaml").read_text(encoding="utf-8") == "schema_version: 1\ncountry: US\n"


# Release 005: the same reader reported serial 000000000207, then an empty
# Get-Disk SerialNumber after a replug, while its USBSTOR instance ID kept it.
USBSTOR = "USBSTOR\DISK&VEN_GENERIC&PROD_STORAGE_DEVICE&REV_0207\{}&GL&23:PERPROS"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_empty_serial_falls_back_to_the_usb_instance_id(writer_case):
    _inventory(writer_case, _disk(Number=1, SerialNumber="", UniqueId=USBSTOR.format("FIXTURE-SD-0007")))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert (plan["disk_number"], plan["disk_serial"]) == (1, "FIXTURE-SD-0007")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("unique_id", [USBSTOR.format("7") + "&0", "SCSI\DISK&VEN_X\FIXTURE-SD-0007&0", ""],
                         ids=["windows-generated", "not-usbstor", "absent"])
def test_no_serial_is_invented_from_an_id_that_does_not_carry_one(writer_case, unique_id):
    _inventory(writer_case, _disk(Number=1, SerialNumber="", UniqueId=unique_id))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode != 0
    assert "no USB disk has serial" in completed.stderr


# Release 005: after a replug the same reader reported an empty Get-Disk
# SerialNumber; its USBSTOR instance ID still carried 000000000207.
READER_ID = "USBSTOR\DISK&VEN_GENERIC&PROD_STORAGE_DEVICE&REV_0207\FIXTURE-SD-0007&GL&23:PERPROS"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_empty_serial_falls_back_to_the_usb_instance_serial(writer_case):
    _inventory(writer_case, _disk(Number=4, SerialNumber="", UniqueId=READER_ID))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert (plan["disk_number"], plan["disk_serial"]) == (4, "FIXTURE-SD-0007")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    "unique_id",
    [
        "USBSTOR\DISK&VEN_GENERIC&PROD_STORAGE_DEVICE&REV_0207\7&2A3B4C5D&0:PERPROS",  # Windows-invented
        "SCSI\DISK&VEN_NVME\FIXTURE-SD-0007&0",  # not a USB mass-storage ID
        "",
    ],
    ids=["generated", "not-usbstor", "empty"],
)
def test_no_real_usb_serial_means_no_card(writer_case, unique_id):
    _inventory(writer_case, _disk(Number=4, SerialNumber="", UniqueId=unique_id))

    completed = _run(writer_case, "-DiskSerial", "FIXTURE-SD-0007", omit=("-DiskNumber",))

    assert completed.returncode != 0
    assert "no USB disk has serial" in completed.stderr
    assert not writer_case["marker"].exists()
