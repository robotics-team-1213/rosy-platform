"""tools/release/prepare_payload_release.py with fake tarballs, fake ssh and fake sign/pack (no network)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "prepare_payload_release", ROOT / "tools" / "release" / "prepare_payload_release.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

RELEASE_ID = "2026.10.01-021"
# Low-entropy stand-in: a real commit sha trips the secret scan's high-entropy rule.
SHA = "ab" * 20
ROS_PACKAGES = (
    "ros-jazzy-rclcpp=28.1.9-1noble.20250725.204120\n"
    "ros-jazzy-rmw-fastrtps-cpp=8.4.2-1noble.20250725.201015\n"
    "ros-jazzy-rviz2=14.1.11-1noble.20250725.214002\n"
)
# `dpkg-query -W -f='${db:Status-Abbrev}\t${binary:Package}\t${Version}\n'`: status, name, version.
# rviz2 is "rc" (removed, config files left) and still reports its old version; it must be ignored.
DPKG_OK = (
    "ii \tros-jazzy-rclcpp\t28.1.9-1noble.20250725.204120\n"
    "un \tros-jazzy-rmw-fastrtps-cpp\t\n"
    "ii \tros-jazzy-ros-base\t0.11.0-1noble.20250725.220510\n"
    "rc \tros-jazzy-rviz2\t14.1.10-1noble.20250601.000000\n"
)


def _unsigned_tarball(path: Path, files: dict[str, str]) -> Path:
    """A tarball shaped like the CI handoff: no top-level directory."""
    with tarfile.open(path, "w:gz") as tar:
        dirs = sorted({str(Path(name).parent).replace("\\", "/") for name in files} - {"."})
        for name in dirs:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(info)
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    return path


def _release_files(**overrides: str) -> dict[str, str]:
    files = {
        "manifest.json": '{"release_id": "%s"}\n' % RELEASE_ID,
        "SHA256SUMS": "",
        "install/.colcon_install_layout": "isolated\n",
        "install/.rosy-release": RELEASE_ID + "\n",
        "install/setup.sh": "#!/bin/sh\n",
        "ros-packages.txt": ROS_PACKAGES,
        "rosy-packages.txt": "core\ninterfaces\npinky_pro\n",
        "required-ros-packages.txt": "core\npinky_pro\n",
    }
    files.update(overrides)
    return files


class FakeSsh:
    def __init__(self, outputs: dict[str, tuple[int, str]]):
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        host = next(arg for arg in argv if arg.startswith("rosy@")).split("@", 1)[1]
        code, out = self.outputs[host]
        return code, out, "" if code == 0 else "ssh: connect failed"


# --- extraction ------------------------------------------------------------

def test_dotfile_survives_extraction(tmp_path):
    tarball = _unsigned_tarball(tmp_path / f"{RELEASE_ID}.unsigned.tar.gz", _release_files())
    target = tmp_path / "x" / RELEASE_ID
    tool.extract_release(tarball, target)
    assert (target / "install" / ".colcon_install_layout").read_text(encoding="utf-8") == "isolated\n"
    assert (target / "install" / ".rosy-release").is_file()
    assert (target / "manifest.json").is_file()
    assert [p.name for p in target.parent.iterdir()] == [RELEASE_ID]


def test_existing_release_dir_is_refused(tmp_path):
    tarball = _unsigned_tarball(tmp_path / f"{RELEASE_ID}.unsigned.tar.gz", _release_files())
    target = tmp_path / "x" / RELEASE_ID
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(tool.PrepareError, match="already exists"):
        tool.extract_release(tarball, target)
    assert sorted(p.name for p in target.iterdir()) == ["manifest.json"]


def test_failed_extraction_leaves_no_release_dir(tmp_path):
    broken = tmp_path / f"{RELEASE_ID}.unsigned.tar.gz"
    good = _unsigned_tarball(tmp_path / "good.tar.gz", _release_files()).read_bytes()
    broken.write_bytes(good[: len(good) // 2])
    target = tmp_path / "x" / RELEASE_ID
    with pytest.raises(Exception):
        tool.extract_release(broken, target)
    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_tarball_with_top_level_dir_is_refused(tmp_path):
    files = {f"{RELEASE_ID}/{name}": text for name, text in _release_files().items()}
    tarball = _unsigned_tarball(tmp_path / "nested.tar.gz", files)
    with pytest.raises(tool.PrepareError, match="manifest.json"):
        tool.extract_release(tarball, tmp_path / "x" / RELEASE_ID)
    assert not (tmp_path / "x" / RELEASE_ID).exists()


# --- ABI parse and compare -------------------------------------------------

def test_release_list_parses_name_equals_version():
    parsed = tool.parse_release_ros_packages(ROS_PACKAGES)
    assert parsed == {
        "ros-jazzy-rclcpp": "28.1.9-1noble.20250725.204120",
        "ros-jazzy-rmw-fastrtps-cpp": "8.4.2-1noble.20250725.201015",
        "ros-jazzy-rviz2": "14.1.11-1noble.20250725.214002",
    }


def test_release_list_line_without_equals_is_an_error():
    with pytest.raises(tool.PrepareError, match="name=version"):
        tool.parse_release_ros_packages("ros-jazzy-rclcpp 28.1.9\n")


def test_dpkg_query_parses_tab_and_drops_empty_version():
    parsed = tool.parse_dpkg_query(DPKG_OK + "ii \tros-jazzy-foo:arm64\t1.0\n")
    assert parsed == {
        "ros-jazzy-rclcpp": "28.1.9-1noble.20250725.204120",
        "ros-jazzy-ros-base": "0.11.0-1noble.20250725.220510",
        "ros-jazzy-foo": "1.0",
    }


def test_dpkg_query_ignores_removed_rc_packages():
    assert "ros-jazzy-rviz2" not in tool.parse_dpkg_query(DPKG_OK)
    assert tool.parse_dpkg_query("rc \tros-jazzy-x\t1.0\nhi \tros-jazzy-y\t2.0\n") == {}


def test_dpkg_query_malformed_line_is_an_error():
    with pytest.raises(tool.PrepareError, match="dpkg-query"):
        tool.parse_dpkg_query("ros-jazzy-rclcpp\t28.1.9\n")


def test_abi_matches_when_shared_packages_agree():
    result = tool.compare_abi(tool.parse_release_ros_packages(ROS_PACKAGES), tool.parse_dpkg_query(DPKG_OK))
    # rclcpp is the only package installed on both sides; fastrtps has an empty robot version.
    assert result.compared == 1
    assert result.mismatches == []
    assert result.ok


def test_abi_mismatch_fails():
    robot = DPKG_OK.replace("28.1.9-1noble.20250725.204120", "28.1.10-1noble.20250901.000000")
    result = tool.compare_abi(tool.parse_release_ros_packages(ROS_PACKAGES), tool.parse_dpkg_query(robot))
    assert not result.ok
    assert result.mismatches == [
        ("ros-jazzy-rclcpp", "28.1.9-1noble.20250725.204120", "28.1.10-1noble.20250901.000000")]


def test_abi_comparing_nothing_fails():
    """The 2026-10-01 trap: a parse that compares zero packages must not pass."""
    result = tool.compare_abi(tool.parse_release_ros_packages(ROS_PACKAGES), {"ros-jazzy-other": "1"})
    assert result.compared == 0
    assert not result.ok


def test_robot_abi_check_runs_read_only_dpkg_query_over_ssh(tmp_path):
    ssh = FakeSsh({"192.168.1.202": (0, DPKG_OK)})
    ok, line = tool.check_robot_abi("192.168.1.202", tool.parse_release_ros_packages(ROS_PACKAGES),
                                    ssh, local_appdata=tmp_path)
    assert ok, line
    assert "192.168.1.202" in line and "OK" in line
    argv = ssh.calls[0]
    assert argv[0] == "ssh"
    assert "rosy@192.168.1.202" in argv
    # The remote shell sees single quotes only, so ${...}, \t and \n reach dpkg-query untouched.
    assert argv[-1] == ("dpkg-query -W -f='${db:Status-Abbrev}\\t${binary:Package}\\t${Version}\\n' "
                        "'ros-jazzy-*'")
    assert '"' not in argv[-1]
    joined = " ".join(argv)
    for option in ("IdentitiesOnly=yes", "BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=5"):
        assert option in joined
    assert str(tmp_path / "Rosy" / "ssh" / "rosy-operator-ed25519") in argv
    # Unquoted: ssh.exe receives a quoted value literally and fails with "invalid quotes"
    # (first live run, 2026-10-02). Paths with spaces are refused instead.
    assert f'UserKnownHostsFile={tmp_path / "Rosy" / "known_hosts"}' in argv
    assert not any('"' in arg for arg in argv[:-1])


def test_a_known_hosts_path_with_a_space_or_quote_is_refused(tmp_path):
    for bad in (tmp_path / "has space", tmp_path / 'has"quote'):
        with pytest.raises(tool.PrepareError):
            tool.ssh_argv("192.168.1.202", bad)


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client required")
def test_the_real_ssh_client_accepts_the_built_options(tmp_path):
    # ssh -G resolves the options without connecting; the 2026-10-02 quoted value
    # failed here with "invalid quotes" before any network traffic.
    argv = tool.ssh_argv("192.168.1.202", tmp_path)
    empty = tmp_path / "empty_ssh_config"  # isolate from the operator's own ~/.ssh/config
    empty.write_text("", encoding="ascii")
    probe = [argv[0], "-G", "-F", str(empty), *argv[1:-1]]
    done = subprocess.run(probe, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert "userknownhostsfile " in done.stdout.lower()


def test_robot_abi_check_fails_on_mismatch_and_on_ssh_error(tmp_path):
    release = tool.parse_release_ros_packages(ROS_PACKAGES)
    bad = FakeSsh({"10.0.0.1": (0, DPKG_OK.replace("28.1.9-1", "28.1.8-1")), "10.0.0.2": (255, "")})
    ok, line = tool.check_robot_abi("10.0.0.1", release, bad, local_appdata=tmp_path)
    assert not ok and "ros-jazzy-rclcpp" in line and "MISMATCH" in line
    ok, line = tool.check_robot_abi("10.0.0.2", release, bad, local_appdata=tmp_path)
    assert not ok and "ssh" in line


# --- required packages -----------------------------------------------------

def test_required_packages_must_be_in_rosy_inventory():
    assert tool.missing_required("core\n# comment\n\npinky_pro\n", "core\ninterfaces\npinky_pro\n") == []
    assert tool.missing_required("core\npinky_pro\n", "core\ninterfaces\n") == ["pinky_pro"]


# --- whole command ---------------------------------------------------------

class FakeTools:
    """Stands in for sign_image_release.py and build_payload_release.py pack."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        if "pack" in argv:
            Path(argv[argv.index("--out") + 1]).write_bytes(b"signed")
        return 0


def _artifact_dir(tmp_path: Path, **overrides: str) -> Path:
    artifact = tmp_path / "artifact"
    (artifact / RELEASE_ID).mkdir(parents=True)  # the dotfile-less copy a zip download leaves
    _unsigned_tarball(artifact / f"{RELEASE_ID}.unsigned.tar.gz", _release_files(**overrides))
    return artifact


def _key(tmp_path: Path) -> Path:
    signing = tmp_path / "appdata" / "Rosy" / "signing"
    signing.mkdir(parents=True)
    (signing / "rosy-release-2026-01.private.pem").write_text("fake", encoding="utf-8")
    return tmp_path / "appdata"


def test_main_prints_push_commands_and_never_pushes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    out = tmp_path / "out"
    ssh = FakeSsh({"192.168.1.202": (0, DPKG_OK), "192.168.1.203": (0, DPKG_OK)})
    tools = FakeTools()
    code = tool.main(["--artifact-dir", str(_artifact_dir(tmp_path)), "--release-id", RELEASE_ID,
                      "--out-dir", str(out), "--robot", "192.168.1.202", "--robot", "192.168.1.203"],
                     ssh_runner=ssh, tool_runner=tools)
    printed = capsys.readouterr().out
    assert code == 0, printed
    release_dir = out / "x" / RELEASE_ID
    tarball = out / f"{RELEASE_ID}.tar.gz"
    assert (release_dir / "install" / ".colcon_install_layout").is_file()
    sign, pack = tools.calls
    assert sign[1].endswith("sign_image_release.py") and sign[2] == str(release_dir)
    assert pack[1].endswith("build_payload_release.py") and pack[2] == "pack"
    assert pack[pack.index("--release-dir") + 1] == str(release_dir)
    assert pack[pack.index("--modes-from") + 1] == str(tmp_path / "artifact" / f"{RELEASE_ID}.unsigned.tar.gz")
    quoted = "'" + str(tarball).replace("'", "''") + "'"
    for ip in ("192.168.1.202", "192.168.1.203"):
        assert (f"deploy\\robot\\pinky_pro\\rosy-release-push.ps1 -Robot {ip} -Tarball {quoted} -PrintCommands"
                in printed)
        assert f"deploy\\robot\\pinky_pro\\rosy-release-push.ps1 -Robot {ip} -Tarball {quoted}\n" in printed
    assert all("rosy-release-push" not in " ".join(call) for call in tools.calls + ssh.calls)


def test_main_stops_before_signing_on_abi_mismatch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    ssh = FakeSsh({"192.168.1.202": (0, DPKG_OK.replace("28.1.9-1", "28.1.8-1"))})
    tools = FakeTools()
    code = tool.main(["--artifact-dir", str(_artifact_dir(tmp_path)), "--release-id", RELEASE_ID,
                      "--out-dir", str(tmp_path / "out"), "--robot", "192.168.1.202"],
                     ssh_runner=ssh, tool_runner=tools)
    assert code == 1
    assert tools.calls == []
    assert "rosy-release-push.ps1" not in capsys.readouterr().out
    assert not (tmp_path / "out" / "x" / RELEASE_ID).exists()


def test_main_stops_when_required_package_is_not_in_inventory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    tools = FakeTools()
    code = tool.main(["--artifact-dir", str(_artifact_dir(tmp_path, **{"rosy-packages.txt": "core\n"})),
                      "--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "out"), "--skip-abi"],
                     ssh_runner=FakeSsh({}), tool_runner=tools)
    assert code == 1
    assert "pinky_pro" in capsys.readouterr().err
    assert tools.calls == []


def test_main_refuses_existing_release_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    out = tmp_path / "out"
    (out / "x" / RELEASE_ID / "install").mkdir(parents=True)
    tools = FakeTools()
    code = tool.main(["--artifact-dir", str(_artifact_dir(tmp_path)), "--release-id", RELEASE_ID,
                      "--out-dir", str(out), "--robot", "192.168.1.202"],
                     ssh_runner=FakeSsh({"192.168.1.202": (0, DPKG_OK)}), tool_runner=tools)
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert tools.calls == []


def test_main_needs_a_robot_or_skip_abi(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    with pytest.raises(SystemExit):
        tool.main(["--artifact-dir", str(_artifact_dir(tmp_path)), "--release-id", RELEASE_ID,
                   "--out-dir", str(tmp_path / "out")], ssh_runner=FakeSsh({}), tool_runner=FakeTools())


def test_artifact_name_resolves_release_id_and_sha():
    names = ["rosy-native-payload-build-log", f"rosy-native-payload-unsigned-{RELEASE_ID}-{SHA}"]
    assert tool.pick_artifact(names, None) == (f"rosy-native-payload-unsigned-{RELEASE_ID}-{SHA}", RELEASE_ID)
    assert tool.pick_artifact(names, RELEASE_ID)[1] == RELEASE_ID
    with pytest.raises(tool.PrepareError):
        tool.pick_artifact(names, "2026.10.01-022")
    with pytest.raises(tool.PrepareError):
        tool.pick_artifact(["rosy-native-payload-build-log"], None)


# --- review fixes ----------------------------------------------------------

def test_push_commands_escape_spaces_and_apostrophes():
    tarball = Path("X:/Dev Temp/it's/2026.10.01-021.tar.gz")
    lines = tool.push_commands(["192.168.1.202"], tarball)
    expected = "'" + str(tarball).replace("'", "''") + "'"
    assert "''" in expected and " " in expected
    assert lines[1] == f"deploy\\robot\\pinky_pro\\rosy-release-push.ps1 -Robot 192.168.1.202 -Tarball {expected}"
    assert lines[0].startswith(lines[1] + " -PrintCommands")


def test_main_reports_truncated_tarball_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    artifact = _artifact_dir(tmp_path)
    unsigned = artifact / f"{RELEASE_ID}.unsigned.tar.gz"
    data = unsigned.read_bytes()
    unsigned.write_bytes(data[: len(data) - 40])
    code = tool.main(["--artifact-dir", str(artifact), "--release-id", RELEASE_ID,
                      "--out-dir", str(tmp_path / "out"), "--skip-abi"],
                     ssh_runner=FakeSsh({}), tool_runner=FakeTools())
    captured = capsys.readouterr()
    assert code == 1
    assert "error:" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_main_reports_bad_manifest_json_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    artifact = _artifact_dir(tmp_path, **{"manifest.json": "{not json"})
    code = tool.main(["--artifact-dir", str(artifact), "--release-id", RELEASE_ID,
                      "--out-dir", str(tmp_path / "out"), "--skip-abi"],
                     ssh_runner=FakeSsh({}), tool_runner=FakeTools())
    assert code == 1
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "out" / "x" / RELEASE_ID).exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_link_members_are_refused(tmp_path, kind):
    tarball = _unsigned_tarball(tmp_path / "links.tar.gz", _release_files())
    linked = tmp_path / "linked.tar.gz"
    with tarfile.open(tarball, "r:gz") as source, tarfile.open(linked, "w:gz") as tar:
        for member in source:
            tar.addfile(member, source.extractfile(member) if member.isreg() else None)
        info = tarfile.TarInfo("install/link")
        info.type = kind
        info.linkname = "install/setup.sh"
        tar.addfile(info)
    target = tmp_path / "x" / RELEASE_ID
    with pytest.raises(tool.PrepareError, match="link"):
        tool.extract_release(linked, target)
    assert not target.exists()


class FailingTools(FakeTools):
    def __init__(self, fail: str):
        super().__init__()
        self.fail = fail

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return 1 if argv[1].endswith(self.fail) else 0


@pytest.mark.parametrize("fail", ["sign_image_release.py", "build_payload_release.py"])
def test_sign_or_pack_failure_names_the_dir_to_delete(tmp_path, monkeypatch, capsys, fail):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    out = tmp_path / "out"
    code = tool.main(["--artifact-dir", str(_artifact_dir(tmp_path)), "--release-id", RELEASE_ID,
                      "--out-dir", str(out), "--skip-abi"], ssh_runner=FakeSsh({}), tool_runner=FailingTools(fail))
    err = capsys.readouterr().err
    assert code == 1
    assert fail in err and str(out / "x" / RELEASE_ID) in err and "delete" in err


def test_run_with_release_id_refuses_existing_dir_before_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(_key(tmp_path)))
    out = tmp_path / "out"
    (out / "x" / RELEASE_ID).mkdir(parents=True)

    def no_download():
        raise AssertionError("must not download")
    monkeypatch.setattr(tool, "_download_tool", no_download)
    code = tool.main(["--run", "1", "--release-id", RELEASE_ID, "--out-dir", str(out), "--skip-abi"],
                     ssh_runner=FakeSsh({}), tool_runner=FakeTools())
    assert code == 1
    assert "already exists" in capsys.readouterr().err


def test_run_refuses_existing_dir_after_naming_but_before_download(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "x" / RELEASE_ID).mkdir(parents=True)

    class FakeGitHub:
        def __init__(self, *_args):
            pass

        def _json(self, _path):
            return {"artifacts": [{"name": f"rosy-native-payload-unsigned-{RELEASE_ID}-{SHA}"}]}

        def artifact(self, *_args):
            raise AssertionError("must not look up the artifact for download")

    class Downloader:
        def __init__(self, *_args):
            raise AssertionError("must not download")

    fake = type("FakeDownloadTool", (), {
        "GitHub": FakeGitHub, "Downloader": Downloader, "DownloadError": RuntimeError,
        "default_repo": staticmethod(lambda: "owner/rosy-os"), "github_token": staticmethod(lambda: "t"),
    })
    monkeypatch.setattr(tool, "_download_tool", lambda: fake)
    with pytest.raises(tool.PrepareError, match="already exists"):
        tool.download_unsigned(1, None, out, None, 8)
