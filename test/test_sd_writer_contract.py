from __future__ import annotations

import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

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


def _run(case, *extra, plan_only=True, omit=(), switches=()):
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
    command.extend(switches)
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
    # D-180: Imager only writes; the full readback below is the single verify.
    assert writer_arguments.split()[:2] == ["--cli", "--disable-verify"]
    assert "--sha256" not in writer_arguments
    assert compressed_sha256 not in writer_arguments
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
    assert receipt["media_readback"]["image_raw_sha256"] == raw_sha256
    assert receipt["media_readback"]["device_sha256"] == raw_sha256
    assert registry["robot_numbers"] == [1]
    assert registry["device_names"] == ["rosy-pinky-k7m4"]
    assert registry["device_uids"] == ["9d40feaa-871f-4fd3-975a-a704e82d3af9"]


def _flip_one_byte(data: bytes) -> bytes:
    middle = len(data) // 2
    return data[:middle] + bytes([data[middle] ^ 0x01]) + data[middle + 1:]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    "corrupt",
    [lambda data: b"wrong media contents", _flip_one_byte],
    ids=["short-media", "one-flipped-byte"],
)
def test_readback_mismatch_stops_before_personalization_and_receipt(writer_case, tmp_path, corrupt):
    # D-180: Imager runs with --disable-verify, so this readback is the only
    # media check; a single wrong byte must still stop bundle, receipt and registry.
    writer_case["readback"].write_bytes(corrupt(writer_case["readback"].read_bytes()))
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
    assert "--disable-verify" in writer_case["writer_args"].read_text(encoding="utf-8")
    # D-181: a card that ends early is an I/O problem (resume); a flipped byte is bad data.
    rendered = " ".join((completed.stderr + completed.stdout).split())
    assert ("could not be read during readback" in rendered
            or "full media readback verification failed" in rendered)
    assert not (boot / "rosy-provision" / "provision.json").exists()
    assert not writer_case["receipt"].exists()
    registry = json.loads(writer_case["registry"].read_text(encoding="utf-8"))
    assert registry == {"robot_numbers": [], "device_names": [], "device_uids": []}


def test_script_has_no_plain_password_or_shell_string_escape_hatch():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "WifiPassword" not in text
    assert "Export-Clixml" in text and "Import-Clixml" in text
    assert "Read-Host -AsSecureString" in text
    # D-180: one authoritative verify (the full readback), no Imager verify,
    # no --sha256 and no separate raw-hash pre-pass over the image.
    assert '"--cli",' in text and '"--disable-verify",' in text
    assert "--sha256" not in text
    assert "--image-only" not in text
    assert text.count("verify-media-readback.py") == 1
    # One readback pass, run as a watched process (D-182); the only other call is
    # the pre-flight probe (raw size from the xz index, a timed read of the card start).
    assert text.count("& $PythonExe $readbackVerifier") == 1
    assert "& $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget --probe" in text
    assert text.count('@($readbackVerifier, "--image", $ImagePath, "--device", $readbackTarget)') == 1
    assert "Start-Process -FilePath $PythonExe -ArgumentList $verifierArguments" in text
    assert "--raw-size" not in text
    assert "cmd /c" not in text.lower()
    assert '"ERASE SERIAL $($firstDisk.SerialNumber) $DeviceName"' in text
    assert "Start-Process" in text
    # D-181: the writer is polled by a stall watchdog, never waited on blindly.
    assert "-Wait -PassThru" not in text
    assert "WaitForExit($pollMilliseconds)" in text
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
    assert '@($readbackVerifier, "--image", $ImagePath, "--device", $readbackTarget)' in text


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


# --- D-181: progress file, stall watchdog, actionable failures, resume ------
# Release 005: a write vanished without a receipt, Imager stalled for 23 minutes
# after its last byte while Start-Process -Wait waited, and the transcript never
# showed which stage was running.

WRITE_CONFIRMATION = ("-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4")
SUCCESS_STAGES = [
    ("verify-signature", "untouched"), ("select-disk", "untouched"), ("preflight", "untouched"),
    ("confirm", "untouched"), ("write", "writing"), ("readback", "written-unverified"),
    ("bundle", "verified-no-bundle"), ("bundle-writing", "bundle-partial"), ("receipt", "complete"),
    ("done", "complete"),
]
# The tree-wide stall watchdog (D-181 review) sees ping.exe's packets, so an
# idle writer child must really be idle.
IDLE_CHILD = f'"{sys.executable}" -c "import time; time.sleep(120)"'


def _err(completed):
    # PowerShell wraps long error lines at the console width.
    return " ".join(completed.stderr.split())


def _progress(case):
    path = Path(str(case["receipt"]) + ".progress.jsonl")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in lines:
        assert line["ts"].endswith("Z") and "T" in line["ts"]
    return lines


def _stages(lines):
    return [(line["stage"], line["card_state"]) for line in lines if line.get("detail") not in ("heartbeat", "measured")]


def _stage_line(lines, stage):
    return next(line for line in lines if line["stage"] == stage and line.get("detail") not in ("heartbeat", "measured"))


def _failed(lines):
    assert lines[-1]["stage"] == "failed"
    return lines[-1]["card_state"]


def _fake_writer(case, body):
    case["writer"].write_text(
        f'@echo off\n> "{case["marker"]}" echo called\n> "{case["writer_args"]}" echo %*\n{body}\n',
        encoding="utf-8",
    )


def _write(case, tmp_path, *extra, switches=()):
    boot = tmp_path / "boot"
    boot.mkdir(exist_ok=True)
    return _run(case, *WRITE_CONFIRMATION, "-BootMountPath", boot, *extra,
                plan_only=False, switches=switches), boot


def _nothing_recorded(case, boot):
    assert not (boot / "rosy-provision" / "provision.json").exists()
    assert not case["receipt"].exists()
    registry = json.loads(case["registry"].read_text(encoding="utf-8"))
    assert registry == {"robot_numbers": [], "device_names": [], "device_uids": []}


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_progress_file_records_every_stage_of_a_successful_write(writer_case, tmp_path):
    completed, _boot = _write(writer_case, tmp_path)

    assert completed.returncode == 0, completed.stderr
    lines = _progress(writer_case)
    assert _stages(lines) == SUCCESS_STAGES
    raw_size = writer_case["readback"].stat().st_size
    assert _stage_line(lines, "write")["detail"] == f"raw image {raw_size} bytes"
    assert _stage_line(lines, "readback")["total"] == raw_size
    beats = [line for line in lines if line["stage"] == "readback" and line.get("detail") == "heartbeat"]
    assert beats and beats[-1]["bytes"] == raw_size
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["resumed_after_write"] is False
    assert receipt["writer_exit_code"] == 0
    # Review MEDIUM-1: the readback's compressed-stream hash is the signed one.
    assert receipt["media_readback"]["image_sha256"] == hashlib.sha256(writer_case["image"].read_bytes()).hexdigest()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_bad_signature_leaves_the_card_untouched_and_says_to_download_again(writer_case, tmp_path):
    writer_case["signature"].write_text("invalid-signature\n", encoding="utf-8")

    completed, _boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "stage=verify-signature card_state=untouched" in _err(completed)
    assert "next: download the release again" in _err(completed)
    assert _failed(_progress(writer_case)) == "untouched"
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_wrong_confirmation_leaves_the_card_untouched_and_says_to_re_run(writer_case, tmp_path):
    completed, _boot = _write(writer_case, tmp_path, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4:")

    assert completed.returncode != 0
    assert "typed: 'ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4:'" in _err(completed)
    assert "stage=confirm card_state=untouched" in _err(completed)
    assert "next: re-run and type exactly: ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4" in _err(completed)
    assert _stages(_progress(writer_case))[-2:] == [("confirm", "untouched"), ("failed", "untouched")]
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_missing_card_says_to_reseat_the_reader_and_re_plan(writer_case, tmp_path):
    _inventory(writer_case, _disk(SerialNumber="OTHER-CARD"))

    completed, _boot = _write(writer_case, tmp_path, "-DiskSerial", "FIXTURE-SD-0007", "-DiskNumber", "7")

    assert completed.returncode != 0
    assert "no USB disk has serial" in _err(completed)
    assert "stage=select-disk card_state=untouched" in _err(completed)
    assert "next: reseat the card reader, re-run -PlanOnly" in _err(completed)
    assert _failed(_progress(writer_case)) == "untouched"
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_failed_imager_means_a_full_rewrite(writer_case, tmp_path):
    _fake_writer(writer_case, "exit /b 5")

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "image writer failed with exit code 5" in _err(completed)
    assert "stage=write card_state=writing" in _err(completed)
    assert "next: the card is partially written: re-run the full write" in _err(completed)
    lines = _progress(writer_case)
    assert _failed(lines) == "writing"
    assert "readback" not in [line["stage"] for line in lines]
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_writer_that_stalls_mid_write_is_killed_and_needs_a_full_rewrite(writer_case, tmp_path):
    # cmd.exe waits on ping with no CPU or I/O of its own, like Imager in release 005.
    _fake_writer(writer_case, f"{IDLE_CHILD}\nexit /b 0")

    started = time.monotonic()
    completed, boot = _write(writer_case, tmp_path, "-WriterStallMinutes", "0.05", "-HeartbeatSeconds", "0")

    assert completed.returncode != 0
    assert "image writer stalled" in _err(completed)
    assert time.monotonic() - started < 100, "the stalled writer was waited on instead of killed"
    assert "stage=write card_state=writing" in _err(completed)
    assert "re-run the full write" in _err(completed)
    lines = _progress(writer_case)
    assert any(line["stage"] == "write" and line.get("detail") == "heartbeat" and "bytes" in line for line in lines)
    assert _failed(lines) == "writing"
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_writer_that_stalls_after_the_last_byte_points_to_resume(writer_case, tmp_path):
    copy = tmp_path / "written.bin"
    _fake_writer(writer_case, f'copy /b "{writer_case["readback"]}" "{copy}" >nul\n{IDLE_CHILD}')

    completed, boot = _write(writer_case, tmp_path, "-WriterStallMinutes", "0.05")

    assert completed.returncode != 0
    assert "image writer stalled" in _err(completed)
    assert "stage=write card_state=written-unverified" in _err(completed)
    assert "-ResumeAfterWrite" in _err(completed)
    assert _failed(_progress(writer_case)) == "written-unverified"
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_readback_mismatch_says_rewrite_then_replace_the_card(writer_case, tmp_path):
    writer_case["readback"].write_bytes(_flip_one_byte(writer_case["readback"].read_bytes()))

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "stage=readback card_state=written-unverified" in _err(completed)
    assert "re-run the full write" in _err(completed) and "replace the card" in _err(completed)
    assert _failed(_progress(writer_case)) == "written-unverified"
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_unreadable_card_during_readback_says_reinsert_and_resume(writer_case, tmp_path):
    completed, boot = _write(writer_case, tmp_path, "-ReadbackDevice", tmp_path / "card-was-removed.bin")

    assert completed.returncode != 0
    assert "could not be read during readback" in _err(completed)
    assert "next: reinsert the card (or use another reader), then re-run the same command with -ResumeAfterWrite" in _err(completed)
    assert "device cannot be opened" in _err(completed)  # the verifier's own reason
    assert _failed(_progress(writer_case)) == "written-unverified"
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_image_changed_after_the_signature_check_fails_on_its_readback_hash(writer_case, tmp_path):
    # Bytes after the xz stream do not change what lzma decompresses, so only
    # the compressed-stream hash can tell this file from the signed one.
    _fake_writer(writer_case, f'>> "{writer_case["image"]}" echo appended-after-signing\nexit /b 0')

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "the image read back is not the signed image" in _err(completed)
    assert "stage=readback card_state=unknown" in _err(completed)
    assert "next: download the release again" in _err(completed)
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_card_is_selected_again_before_the_bundle(writer_case, tmp_path):
    swapped = tmp_path / "swapped.json"
    swapped.write_text(json.dumps([_disk(SerialNumber="SWAPPED-READER")]), encoding="utf-8")
    # The inventory changes after both pre-write probes, as if the reader were swapped.
    _fake_writer(writer_case, f'copy /y "{swapped}" "{writer_case["inventory"]}" >nul\nexit /b 0')

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "target disk changed between the readback and the bundle" in _err(completed)
    assert "stage=bundle card_state=verified-no-bundle" in _err(completed)
    assert "-ResumeAfterWrite" in _err(completed)
    assert _failed(_progress(writer_case)) == "verified-no-bundle"
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_after_write_skips_the_writer_and_still_reads_back_everything(writer_case, tmp_path):
    completed, boot = _write(writer_case, tmp_path, switches=("-ResumeAfterWrite",))

    assert completed.returncode == 0, completed.stderr
    assert not writer_case["marker"].exists()
    lines = _progress(writer_case)
    assert _stages(lines) == [
        ("verify-signature", "untouched"), ("select-disk", "untouched"), ("preflight", "untouched"),
        ("confirm", "untouched"), ("write", "written-unverified"), ("readback", "written-unverified"),
        ("bundle", "verified-no-bundle"), ("bundle-writing", "bundle-partial"), ("receipt", "complete"),
        ("done", "complete"),
    ]
    assert lines[0]["detail"] == "resume-after-write"
    assert _stage_line(lines, "write")["detail"] == "skipped: -ResumeAfterWrite"
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["resumed_after_write"] is True
    assert receipt["writer_exit_code"] is None
    assert receipt["media_readback"]["verified"] is True
    assert (boot / "rosy-provision" / "provision.json").exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_after_write_still_blocks_on_a_readback_mismatch(writer_case, tmp_path):
    writer_case["readback"].write_bytes(_flip_one_byte(writer_case["readback"].read_bytes()))

    completed, boot = _write(writer_case, tmp_path, switches=("-ResumeAfterWrite",))

    assert completed.returncode != 0
    assert "full media readback verification failed" in _err(completed)
    assert not writer_case["marker"].exists()
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("case_name", ["existing-receipt", "wrong-confirmation"])
def test_resume_after_write_keeps_every_pre_write_check(writer_case, tmp_path, case_name):
    extra = ()
    if case_name == "existing-receipt":
        writer_case["receipt"].write_text("existing evidence\n", encoding="utf-8")
        message = "receipt already exists"
    else:
        extra = ("-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-zzzz")
        message = "confirmation did not match"

    completed, _boot = _write(writer_case, tmp_path, *extra, switches=("-ResumeAfterWrite",))

    assert completed.returncode != 0
    assert message in _err(completed)
    assert "readback" not in [line["stage"] for line in _progress(writer_case)]
    if case_name == "existing-receipt":
        assert writer_case["receipt"].read_text(encoding="utf-8") == "existing evidence\n"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_resumed_receipt_proves_a_verified_write_for_reprovisioning(writer_case, tmp_path):
    _registered(writer_case)
    prior = _prior_receipt(tmp_path, writer_exit_code=None, resumed_after_write=True)

    completed = _run(writer_case, "-ReprovisionReceipt", prior)

    assert completed.returncode == 0, completed.stderr


# Release 005 rewrite: the transcript said only "full media readback verification
# failed"; the verifier's stderr never reached it, so a mid-read disconnect could
# not be told from bad data. The reason now travels through --error-json.


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_readback_mismatch_reason_reaches_the_failure_and_the_progress_file(writer_case, tmp_path):
    raw = writer_case["readback"].read_bytes()
    writer_case["readback"].write_bytes(_flip_one_byte(raw))
    offset = len(raw) // 2

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    reason = f"media readback mismatch at byte offset {offset}"
    assert f"full media readback verification failed: {reason} (verified 0 bytes before it stopped)" in _err(completed)
    assert "if it fails again, replace the card" in _err(completed)
    failed = _progress(writer_case)[-1]
    assert failed["stage"] == "failed" and failed["card_state"] == "written-unverified"
    assert reason in failed["detail"] and "verified 0 bytes" in failed["detail"]
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_card_that_ends_mid_readback_is_an_io_problem_with_its_reason_logged(writer_case, tmp_path):
    raw = writer_case["readback"].read_bytes()
    writer_case["readback"].write_bytes(raw[:1000])  # the reader dropped out partway

    completed, boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    reason = "media is shorter than the image at byte offset 0"
    assert f"could not be read during readback (removed, disconnected or I/O error): {reason}" in _err(completed)
    assert "next: reinsert the card (or use another reader), then re-run the same command with -ResumeAfterWrite" in _err(completed)
    failed = _progress(writer_case)[-1]
    assert failed["card_state"] == "written-unverified"
    assert reason in failed["detail"]
    _nothing_recorded(writer_case, boot)


# --- D-182: readback watchdog, pre-flight, card identity --------------------
# Release 005: the readback ran at about 3.4 MB/s for about 60 minutes, then the
# reader dropped out of Get-Disk and nothing noticed; the operating agent kept
# giving wrong completion times; a cheap reader's dummy serial (000000000207)
# named the reader, not the card.

import struct  # noqa: E402

from sd_pipe_card import PipeCard  # noqa: E402

MIB = 1024 * 1024


def _rerelease(case, raw: bytes):
    """Sign a release around ``raw`` and make the file stand-in card hold it."""
    case["readback"].write_bytes(raw)
    image = case["image"]
    image.write_bytes(lzma.compress(raw))
    release = image.parent
    manifest = release / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["image"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    sums = build_sha256sums(release, ["manifest.json", image.name])
    (release / "SHA256SUMS").write_bytes(sums)
    case["signature"].write_text(sign_checksums(sums, case["private_key"]), encoding="utf-8")


def _multi_chunk_raw(chunks: int = 6) -> bytes:
    return bytes(range(256)) * (chunks * MIB * 4 // 256)  # chunks x 4 MiB, compresses to little


def _mbr_raw(signature: int) -> bytes:
    raw = bytearray(bytes(range(256)) * (MIB // 256))
    struct.pack_into("<I", raw, 440, signature)
    raw[510:512] = b"\x55\xaa"
    return bytes(raw)


def _measured(lines):
    return next(line for line in lines if line["stage"] == "preflight" and line.get("detail") == "measured")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_hung_readback_is_stopped_and_points_to_resume(writer_case, tmp_path):
    raw = _multi_chunk_raw()
    _rerelease(writer_case, raw)
    # The pre-flight probe and the pre-erase re-check read it; the readback hangs.
    card = PipeCard(raw, ["full", "full", "hang"])
    try:
        started = time.monotonic()
        completed, boot = _write(writer_case, tmp_path, "-ReadbackDevice", card.path,
                                 "-ReadbackStallMinutes", "0.05", "-HeartbeatSeconds", "0")
        elapsed = time.monotonic() - started
    finally:
        card.close()

    assert completed.returncode != 0
    assert elapsed < 120, "the hung verifier was waited on instead of stopped"
    assert "could not be read during readback (stalled, kind io)" in _err(completed)
    assert "the verifier was stopped" in _err(completed)
    assert "stage=readback card_state=written-unverified" in _err(completed)
    assert "next: reinsert the card (or use another reader), then re-run the same command with -ResumeAfterWrite" in _err(completed)
    failed = _progress(writer_case)[-1]
    assert (failed["stage"], failed["card_state"], failed["kind"]) == ("failed", "written-unverified", "io")
    assert "-ResumeAfterWrite" in failed["next"]
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_slow_readback_that_keeps_moving_is_never_stopped(writer_case, tmp_path):
    raw = _multi_chunk_raw()
    _rerelease(writer_case, raw)
    # Six 4 MiB pieces 0.8 s apart: about 5 s in all, longer than the 3 s limit,
    # but the verified byte count rises well inside it every time.
    card = PipeCard(raw, ["full", "full", ("slow", 0.8)])
    try:
        completed, _boot = _write(writer_case, tmp_path, "-ReadbackDevice", card.path,
                                  "-ReadbackStallMinutes", "0.05", "-HeartbeatSeconds", "0")
    finally:
        card.close()

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["media_readback"]["bytes_verified"] == len(raw)
    assert receipt["readback_target"] == card.path  # D-181 review: the evidence names what was read
    beats = [line for line in _progress(writer_case) if line["stage"] == "readback" and line.get("detail") == "heartbeat"]
    assert len(beats) >= 4


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_writer_whose_child_does_the_io_is_not_stalled(writer_case, tmp_path):
    # D-181 review: only the launched PID was sampled, so a wrapper that waits
    # while its child writes looked idle and was killed mid-write.
    out = tmp_path / "child-writes.bin"
    child = (f'"{sys.executable}" -c "import time; f=open(r\'{out}\', \'ab\', buffering=0); '
             f'[(f.write(bytes(65536)), time.sleep(0.4)) for _ in range(15)]"')
    _fake_writer(writer_case, f"{child}\nexit /b 0")

    completed, _boot = _write(writer_case, tmp_path, "-WriterStallMinutes", "0.03")

    assert completed.returncode == 0, completed.stderr
    assert out.stat().st_size == 15 * 65536


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_preflight_measures_the_card_and_predicts_the_job(writer_case, tmp_path):
    _rerelease(writer_case, _multi_chunk_raw(1))  # at least 1 MiB is timed; less is reported unmeasured
    raw_size = writer_case["readback"].stat().st_size

    completed, _boot = _write(writer_case, tmp_path, "-AssumedWriteMBps", "9")

    assert completed.returncode == 0, completed.stderr
    measured = _measured(_progress(writer_case))
    assert measured["card_state"] == "untouched"
    assert measured["read_mbps"] > 0 and measured["read_bytes"] == raw_size
    assert measured["raw_bytes"] == raw_size
    assert measured["assumed_write_mbps"] == 9
    assert measured["predicted_write_seconds"] == -(-raw_size // 9_000_000)
    assert measured["predicted_total_seconds"] == measured["predicted_write_seconds"] + measured["predicted_readback_seconds"]
    assert "Pre-flight: card read" in completed.stdout
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["preflight"]["read_mbps"] == measured["read_mbps"]
    assert receipt["fixture"] is True  # D-182 review: fixture evidence says so


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_slow_media_stops_a_non_interactive_run_before_the_confirmation(writer_case, tmp_path):
    _rerelease(writer_case, _multi_chunk_raw(1))
    completed, _boot = _write(writer_case, tmp_path, "-MinReadMBps", "1e12")

    assert completed.returncode != 0
    assert "SLOW MEDIA" in completed.stdout
    assert "below -MinReadMBps" in _err(completed)
    assert "stage=preflight card_state=untouched" in _err(completed)
    assert "USB 3.0 reader, with an A1/A2 or U3 card" in _err(completed)
    assert "-AcceptSlowMedia" in _err(completed)
    assert "confirm" not in [line["stage"] for line in _progress(writer_case)]
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_accept_slow_media_writes_anyway(writer_case, tmp_path):
    _rerelease(writer_case, _multi_chunk_raw(1))
    completed, _boot = _write(writer_case, tmp_path, "-MinReadMBps", "1e12", switches=("-AcceptSlowMedia",))

    assert completed.returncode == 0, completed.stderr
    assert "SLOW MEDIA" in completed.stdout
    assert writer_case["marker"].exists()


def _plan_with_card(case, tmp_path, **identity):
    _inventory(case, _disk(**identity))
    plan_path = tmp_path / "plan.json"
    planned = _run(case, "-PlanPath", plan_path)
    assert planned.returncode == 0, planned.stderr
    return plan_path, json.loads(plan_path.read_text(encoding="utf-8-sig"))


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_plan_pins_the_inserted_cards_identity(writer_case, tmp_path):
    _plan_path, plan = _plan_with_card(writer_case, tmp_path, Signature=0x1A2B3C4D,
                                       Guid="{1B7A3F52-0000-4000-8000-00000000ABCD}")

    assert plan["disk_signature"] == "1a2b3c4d"
    assert plan["disk_guid"] == "1b7a3f52-0000-4000-8000-00000000abcd"
    assert plan["disk_size"] == 32 * 1024**3


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("card_signature", [0x55667788, 0], ids=["other-signature", "zero-signature"])
def test_another_card_in_the_same_reader_stops_before_the_erase(writer_case, tmp_path, card_signature):
    plan_path, _plan = _plan_with_card(writer_case, tmp_path, Signature=0x1A2B3C4D)
    # Same reader serial and size, and Get-Disk's cache still shows the planned
    # signature; the card's own first sector is what counts (D-182 review).
    writer_case["readback"].write_bytes(_mbr_raw(card_signature))
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(writer_case, "-PlanPath", plan_path, *WRITE_CONFIRMATION, "-BootMountPath", boot, plan_only=False)

    assert completed.returncode != 0
    assert "a different card is in the reader" in _err(completed)
    found = "disk signature 55667788" if card_signature else "disk signature none"
    assert "disk signature 1a2b3c4d" in _err(completed) and found in _err(completed)
    assert "card_state=untouched" in _err(completed)
    assert "next: put the planned card back (check its label)" in _err(completed)
    assert "confirm" not in [line["stage"] for line in _progress(writer_case)]
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_planned_card_is_written(writer_case, tmp_path):
    _rerelease(writer_case, _mbr_raw(0x1A2B3C4D))  # the card's first sector carries the planned signature
    plan_path, _plan = _plan_with_card(writer_case, tmp_path, Signature=0x1A2B3C4D)
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(writer_case, "-PlanPath", plan_path, *WRITE_CONFIRMATION, "-BootMountPath", boot, plan_only=False)

    assert completed.returncode == 0, completed.stderr
    assert writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_blank_card_falls_back_to_serial_and_size_with_a_warning(writer_case, tmp_path):
    plan_path, plan = _plan_with_card(writer_case, tmp_path)  # no Signature, no Guid
    boot = tmp_path / "boot"
    boot.mkdir()

    completed = _run(writer_case, "-PlanPath", plan_path, *WRITE_CONFIRMATION, "-BootMountPath", boot, plan_only=False)

    assert (plan["disk_signature"], plan["disk_guid"]) == (None, None)
    assert completed.returncode == 0, completed.stderr
    assert "factory blank" in " ".join(completed.stdout.split())


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_refuses_a_card_that_does_not_hold_the_images_mbr_signature(writer_case, tmp_path):
    _rerelease(writer_case, _mbr_raw(0xAABBCCDD))
    other = bytearray(writer_case["readback"].read_bytes())
    struct.pack_into("<I", other, 440, 0x11223344)  # a card from another release, or never written
    writer_case["readback"].write_bytes(bytes(other))

    started = time.monotonic()
    completed, boot = _write(writer_case, tmp_path, switches=("-ResumeAfterWrite",))

    assert completed.returncode != 0
    assert "does not hold this release's image" in _err(completed)
    assert "11223344" in _err(completed) and "aabbccdd" in _err(completed)
    assert "stage=preflight card_state=unknown" in _err(completed)
    assert "readback" not in [line["stage"] for line in _progress(writer_case)]
    assert time.monotonic() - started < 120
    _nothing_recorded(writer_case, boot)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_accepts_a_card_with_the_images_mbr_signature(writer_case, tmp_path):
    _rerelease(writer_case, _mbr_raw(0xAABBCCDD))

    completed, _boot = _write(writer_case, tmp_path, switches=("-ResumeAfterWrite",))

    assert completed.returncode == 0, completed.stderr
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_refuses_a_card_that_already_has_a_bundle(writer_case, tmp_path):
    # D-181 review: the readback would read the whole card, then fail on the extra file.
    boot = tmp_path / "boot"
    (boot / "rosy-provision").mkdir(parents=True)

    completed, _boot = _write(writer_case, tmp_path, switches=("-ResumeAfterWrite",))

    assert completed.returncode != 0
    assert "already has a provisioning bundle" in _err(completed)
    assert "card_state=bundle-partial" in _err(completed)
    assert "next: rewrite the card: re-run the full write" in _err(completed)
    assert "readback" not in [line["stage"] for line in _progress(writer_case)]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_failure_while_the_bundle_is_copied_says_rewrite_not_resume(writer_case, tmp_path):
    boot = tmp_path / "boot"
    (boot / "rosy-provision").mkdir(parents=True)
    (boot / "rosy-provision" / "provision.json").write_text("{}", encoding="utf-8")

    completed, _boot = _write(writer_case, tmp_path)

    assert completed.returncode != 0
    assert "stage=bundle-writing card_state=bundle-partial" in _err(completed)
    assert "cannot be resumed" in _err(completed)
    assert "-ResumeAfterWrite (skips" not in _err(completed)
    assert _failed(_progress(writer_case)) == "bundle-partial"
    assert not writer_case["receipt"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("resume", [False, True], ids=["write", "resume"])
def test_a_readback_device_is_refused_for_a_real_disk(writer_case, tmp_path, resume):
    # D-181 review MEDIUM: the readback read another device, and the bundle and
    # receipt went to the real card.
    completed = _run(writer_case, *WRITE_CONFIRMATION, plan_only=False, omit=("-DiskInventoryJson",),
                     switches=("-ResumeAfterWrite",) if resume else ())

    assert completed.returncode != 0
    assert "-ReadbackDevice is a test fixture option" in _err(completed)
    assert not writer_case["marker"].exists()
    assert not Path(str(writer_case["receipt"]) + ".progress.jsonl").exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_writer_that_is_not_an_exe_is_refused_for_a_real_disk(writer_case):
    completed = _run(writer_case, *WRITE_CONFIRMATION, plan_only=False, omit=("-DiskInventoryJson", "-ReadbackDevice"))

    assert completed.returncode != 0
    assert "-RpiImager must be the Raspberry Pi Imager .exe" in _err(completed)
    assert not writer_case["marker"].exists()


def test_the_watchdogs_kill_without_throwing_and_never_resume_an_unkillable_writer():
    text = SCRIPT.read_text(encoding="utf-8")

    # D-181 review: taskkill stderr under ErrorAction Stop threw in PowerShell 5.1.
    assert "2>&1 | Out-Null" not in text
    assert '$ErrorActionPreference = "Continue"' in text and "& taskkill.exe /PID $Process.Id /T /F *> $null" in text
    assert "return $Process.WaitForExit(10000)" in text
    assert "Imager could not be stopped: unplug the card reader and reboot the PC" in text
    assert "(do not resume)" in text
    # The whole process tree is sampled, not only the launched PID.
    assert "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue" in text
    assert "ParentProcessId" in text


# --- D-182 review -------------------------------------------------------------


def _card_holding_the_release(case, tmp_path):
    """A blank card was planned; the reader now holds a card with this release on it."""
    _rerelease(case, _mbr_raw(0xAABBCCDD))
    plan_path, plan = _plan_with_card(case, tmp_path)  # blank at plan time
    assert plan["disk_signature"] is None
    boot = tmp_path / "boot"
    boot.mkdir(exist_ok=True)
    return plan_path, boot


def _write_plan(case, plan_path, boot):
    return _run(case, "-PlanPath", plan_path, *WRITE_CONFIRMATION, "-BootMountPath", boot, plan_only=False)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_finished_card_for_another_robot_is_never_erased_under_this_plan(writer_case, tmp_path):
    # Card A was written and provisioned but not booted: it still carries the
    # image's MBR signature. Plan B was made on a blank card.
    plan_path, boot = _card_holding_the_release(writer_case, tmp_path)
    (boot / "rosy-provision").mkdir()

    completed = _write_plan(writer_case, plan_path, boot)

    assert completed.returncode != 0
    assert "a different card is in the reader" in _err(completed)
    assert "provisioning bundle" in _err(completed)
    assert "card_state=untouched" in _err(completed)
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_card_holding_the_release_needs_an_earlier_write_of_this_plan(writer_case, tmp_path):
    plan_path, boot = _card_holding_the_release(writer_case, tmp_path)

    completed = _write_plan(writer_case, plan_path, boot)

    assert completed.returncode != 0
    assert "no earlier write of this plan was recorded" in _err(completed)
    assert "card_state=untouched" in _err(completed)
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_earlier_write_of_this_plan_lets_the_partly_written_card_be_rewritten(writer_case, tmp_path):
    plan_path, boot = _card_holding_the_release(writer_case, tmp_path)
    earlier = tmp_path / "write-earlier.log.progress.jsonl"
    earlier.write_text(
        json.dumps({"ts": "2026-09-24T01:00:00Z", "stage": "verify-signature", "card_state": "untouched",
                    "plan": str(plan_path.resolve())}) + "\n"
        + json.dumps({"ts": "2026-09-24T01:05:00Z", "stage": "write", "card_state": "writing"}) + "\n",
        encoding="utf-8")

    completed = _write_plan(writer_case, plan_path, boot)

    assert completed.returncode == 0, completed.stderr
    assert "from an earlier write of this plan" in " ".join(completed.stdout.split())
    assert writer_case["marker"].exists()
    first = _progress(writer_case)[0]
    assert first["plan"] == str(plan_path.resolve())


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_fixture_inventory_cannot_drive_an_exe_writer(writer_case, tmp_path):
    completed, _boot = _write(writer_case, tmp_path, "-RpiImager", tmp_path / "rpi-imager.exe")

    assert completed.returncode != 0
    assert "cannot drive an .exe writer" in _err(completed)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("device", [r"\\.\PhysicalDrive9", r"\\?\PhysicalDrive9"])
def test_a_fixture_readback_device_cannot_be_a_real_device(writer_case, tmp_path, device):
    completed, _boot = _write(writer_case, tmp_path, "-ReadbackDevice", device)

    assert completed.returncode != 0
    assert "must be a file or pipe stand-in" in _err(completed)
    assert not writer_case["marker"].exists()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_readback_whose_heartbeat_lags_but_keeps_reading_is_not_stopped(writer_case, tmp_path):
    # 512 KiB every 0.45 s: a 4 MiB chunk (and so a heartbeat) only every 3.6 s,
    # longer than the 3 s limit; the verifier's own disk reads show it is moving.
    raw = _multi_chunk_raw(3)
    _rerelease(writer_case, raw)
    card = PipeCard(raw, ["full", "full", ("slow", 0.45, 512 * 1024)])
    try:
        completed, _boot = _write(writer_case, tmp_path, "-ReadbackDevice", card.path,
                                  "-ReadbackStallMinutes", "0.05", "-HeartbeatSeconds", "0")
    finally:
        card.close()

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(writer_case["receipt"].read_text(encoding="utf-8-sig"))
    assert receipt["media_readback"]["bytes_verified"] == len(raw)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_card_too_slow_for_the_probe_limit_is_slow_media(writer_case, tmp_path):
    # D-182 review: a probe that timed out gave no rate and skipped the gate.
    raw = _multi_chunk_raw(1)
    _rerelease(writer_case, raw)
    card = PipeCard(raw, ["hang"])
    try:
        completed, _boot = _write(writer_case, tmp_path, "-ReadbackDevice", card.path, "-ProbeSeconds", "1")
    finally:
        card.close()

    assert completed.returncode != 0
    assert "below -MinReadMBps" in _err(completed) and "-AcceptSlowMedia" in _err(completed)
    assert _measured(_progress(writer_case))["read_mbps"] == 0
    assert not writer_case["marker"].exists()
