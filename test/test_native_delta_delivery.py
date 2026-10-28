"""Signed full targets remain authoritative when GitHub offers a smaller transport."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import shutil
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def trees(tmp_path):
    tool = load("transport_delta_builder", "tools/release/make_delta_release.py")
    private, public = tmp_path / "key", tmp_path / "key.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, capture_output=True)
    roots = []
    for number, data in [(1, b"old\n"), (2, b"new\n")]:
        release = f"2026.10.28-{number:03d}"
        root = tmp_path / release
        (root / "install/pkg").mkdir(parents=True)
        (root / "install/pkg/a.py").write_bytes(data)
        (root / "install/pkg/b.py").write_bytes(b"# unchanged\n" + b"".join(
            hashlib.sha256(str(i).encode()).digest() for i in range(2048)))
        (root / "install/.rosy-release").write_text(release + "\n")
        (root / "source-revision.txt").write_text(str(number) * 40 + "\n")
        (root / "source-ref.txt").write_text("main\n")
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in root.rglob("*") if p.is_file()}
        (root / "manifest.json").write_text(json.dumps({"release_id": release, "git_revision": str(number) * 40,
            "files": [{"path": p, "sha256": h} for p, h in sorted(files.items())]}) + "\n")
        files["manifest.json"] = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
        sums = "".join(f"{h}  {p}\n" for p, h in sorted(files.items())).encode()
        (root / "SHA256SUMS").write_bytes(sums)
        (root / "SHA256SUMS.sig").write_text(tool.sign_checksums(sums, private))
        archive = tmp_path / f"{release}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    tar.add(p, arcname=p.relative_to(root).as_posix())
        roots.append((root, archive))
    return tool, public, roots


def test_transport_delta_reuses_exact_signed_full_target(trees, tmp_path):
    tool, key, ((base, base_tar), (target, target_tar)) = trees
    out = tmp_path / "delta"
    result = tool.transport_delta(base_tar, target_tar, key, out,
        [("M", "src/pkg/a.py")], lambda side, path: b"old\n" if side == "old" else b"new\n")
    path, binding = result
    assert binding["base_release_id"] == base.name
    assert binding["full_tarball_sha256"] == hashlib.sha256(target_tar.read_bytes()).hexdigest()
    assert binding["target_sums_sha256"] == hashlib.sha256((target / "SHA256SUMS").read_bytes()).hexdigest()
    assert binding["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with tarfile.open(path) as tar:
        assert "install/pkg/a.py" in tar.getnames()
        assert "install/pkg/b.py" not in tar.getnames()
        for name in ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig"):
            assert tar.extractfile(name).read() == (target / name).read_bytes()
    assert (base / "install/pkg/a.py").read_bytes() == b"old\n"


@pytest.mark.parametrize("change", [("A", "src/pkg/a.py"), ("D", "src/pkg/a.py"), ("M", "src/pkg/package.xml")])
def test_unsupported_plan_uses_full_payload(trees, tmp_path, change):
    tool, key, ((_, base), (_, target)) = trees
    assert tool.transport_delta(base, target, key, tmp_path / "delta", [change], lambda *_: b"old\n") is None


def test_corrupt_signed_base_is_a_hold_not_a_full_fallback(trees, tmp_path):
    tool, key, ((root, _), (_, target)) = trees
    (root / "install/pkg/b.py").write_bytes(b"tampered")
    archive = tmp_path / "corrupt.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for p in root.rglob("*"):
            if p.is_file():
                tar.add(p, arcname=p.relative_to(root).as_posix())
    with pytest.raises(tool.DeltaError, match="verify"):
        tool.transport_delta(archive, target, key, tmp_path / "delta", [("M", "src/pkg/a.py")], lambda *_: b"old\n")


def test_publisher_rejects_transport_changed_after_preparation(trees, tmp_path):
    tool, key, ((_, base), (_, full)) = trees
    delta, binding = tool.transport_delta(base, full, key, tmp_path / "delta",
        [("M", "src/pkg/a.py")], lambda side, _: b"old\n" if side == "old" else b"new\n")
    producer = load("delta_publisher_check", "tools/release/publish_payload_release.py")
    delta.write_bytes(delta.read_bytes() + b"mutation")
    with pytest.raises(producer.PublishError, match="bytes differ"):
        producer.inspection.verify_transport_delta(full, delta, binding, key, tmp_path)


@pytest.mark.parametrize("paths,wanted", [(["docs/a.md"], "none"),
    (["deploy/robot/pinky_pro/image/customize-rootfs.sh"], "os-image"),
    (["unowned/a.py"], "review"), (["operations/setup.py"], "full-payload")])
def test_delivery_policy_has_executable_vocabulary(paths, wanted):
    impact = load("delivery_impact", "deploy/robot/pinky_pro/release/artifact_impact.py")
    assert impact.delivery_policy(paths) == wanted


@pytest.mark.parametrize("paths,wanted", [(["docs/a.md"], "none"),
    (["deploy/robot/pinky_pro/image/customize-rootfs.sh"], "os-image"), (["unowned/file"], "review")])
def test_coordinator_policy_reaches_dispatch_gate(tmp_path, paths, wanted):
    cd = load("delivery_cd", "tools/release/robot_cd.py")
    calls = []
    old, head = "1" * 40, "2" * 40
    config = {"repo": "team/robots", "repo_id": 7, "state_dir": tmp_path,
              "robots": [], "canary": "unused", "key_name": "test"}
    cd.write_json(tmp_path / "state.json", {"sha": old, "phase": "done"})

    def github(*args):
        calls.append(args)
        if args[0] != "api":
            raise AssertionError("policy must run before any build or publication")
        path = args[1]
        if path.endswith("git/ref/heads/main"):
            return json.dumps({"object": {"sha": head}})
        if "/compare/" in path:
            return json.dumps({"status": "ahead", "files": [{"filename": p, "status": "modified"} for p in paths]})
        raise AssertionError(path)

    coordinator = cd.Coordinator(config, gh=github)
    coordinator.ci = lambda _: "success"
    result = coordinator.tick()
    assert result in ("no_robot_changes", "delivery_held")
    assert coordinator.state["delivery_policy"] == wanted
    assert all(call[0] != "workflow" for call in calls)


def test_installed_snapshot_contains_executable_delivery_policy(tmp_path):
    """Use exactly the installer's inventory outside the repository tree."""
    import re
    import sys
    installer = (ROOT / "tools/release/install_robot_cd.ps1").read_text()
    names = re.findall(r'^\s*"([^"\n]+)"[,\r]?$', installer.split("$files = @(", 1)[1].split(")", 1)[0], re.M)
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    script = ("import importlib.util,sys;from pathlib import Path;"
              "r=Path(sys.argv[1]);sys.path.insert(0,str(r/'deploy/robot/pinky_pro/release'));"
              "import artifact_impact;assert artifact_impact.delivery_policy(['docs/a.md'])=='none';"
              "sys.path.insert(0,str(r/'tools/release'));import publish_payload_release,make_delta_release")
    checked = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tmp_path)],
                             cwd=tmp_path, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_coordinator_prepared_full_selects_delta_for_actual_publisher(trees, tmp_path, monkeypatch):
    _, public, ((_, base), (target, full)) = trees
    monkeypatch.syspath_prepend(str(ROOT / "tools/release"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "operator"))
    cd = load("delivery_connected_cd", "tools/release/robot_cd.py")
    state_dir = tmp_path / "cd-state"
    state_dir.mkdir()
    work = state_dir / target.name / "attempt-1"
    work.mkdir(parents=True)
    shutil.copyfile(full, work / full.name)
    config = {"repo": "team/robots", "repo_id": 7, "state_dir": state_dir,
              "robots": ["unused"], "canary": "unused", "key_name": "ephemeral-test"}
    cd.write_json(state_dir / "state.json", {"sha": "2" * 40, "phase": "preparing",
        "release_id": target.name, "work_dir": str(work), "base_tarball": str(base),
        "canary_name": "rosy-test"})
    coordinator = cd.Coordinator(config)
    coordinator.ci = lambda _: "success"
    coordinator.delta_sources = lambda *_: ([("M", "src/pkg/a.py")],
        lambda side, _: b"old\n" if side == "old" else b"new\n")

    def api(path):
        if path == "git/ref/heads/main":
            return {"object": {"sha": "2" * 40}}
        if path.startswith("compare/"):
            return {"status": "identical"}
        if path.startswith("git/matching-refs/"):
            return []
        raise AssertionError(path)

    coordinator.api = api
    import make_delta_release
    original = make_delta_release.transport_delta
    monkeypatch.setattr(make_delta_release, "transport_delta", lambda base, full, _, out, **kwargs:
                        original(base, full, public, out, **kwargs))
    import publish_payload_release
    calls = []
    monkeypatch.setattr(publish_payload_release, "main", lambda args, **kwargs: calls.append((args, kwargs)) or 0)
    assert coordinator.tick() == "done"
    assert coordinator.state["delivery_policy"] == "delta"
    assert len(calls) == 1
    delta_path, binding = calls[0][1]["transport_delta"]
    assert delta_path.is_file() and binding["full_tarball_sha256"] == hashlib.sha256(full.read_bytes()).hexdigest()
    assert coordinator.state["payload_tarball"] == str(work / full.name)


@pytest.mark.parametrize("mode", ["same", "different", "missing", "tamper", "dirty-base", "raced-base", "healthfail"])
def test_signed_producer_local_http_consumer_transport(trees, tmp_path, mode):
    """Run real HTTP, signature checks and GNU tar; staging never changes current."""
    from auto_update_fakes import FakeGitHub
    tool, public, ((base, base_tar), (target, full)) = trees
    delta, binding = tool.transport_delta(base_tar, full, public, tmp_path / "transport",
        [("M", "src/pkg/a.py")], lambda side, _: b"old\n" if side == "old" else b"new\n")
    native = ROOT / "deploy/robot/pinky_pro/native"
    stage = load("delivery_stage", "deploy/robot/pinky_pro/native/auto_update_stage.py")
    root = tmp_path / "device"
    releases = root / "opt/rosy/releases"
    releases.mkdir(parents=True)
    current = base.name if mode != "different" else "2026.10.28-099"
    if mode != "missing":
        shutil.copytree(base, releases / current)
    (releases.parent / "current").symlink_to(releases / current, target_is_directory=True)
    key_path = root / stage.TRUSTED_KEY
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(public.read_bytes())
    if mode == "dirty-base":
        (releases / current / "install/pkg/b.py").write_bytes(b"contaminated")
    identity = root / "var/lib/rosy/device-identity.json"
    identity.parent.mkdir(parents=True)
    identity.write_bytes(b"preserve identity WiFi calibration")
    calls = []

    class HTTP:
        def get(self, url, headers, maximum):
            with urllib.request.urlopen(url) as response:
                data = response.read(maximum + 1)
                assert len(data) <= maximum
                return response.status, dict(response.headers), data

        def download(self, url, path, maximum):
            _, _, data = self.get(url, {}, maximum)
            path.write_bytes(data)
            if mode == "raced-base":
                (releases / current / "install/pkg/a.py").write_bytes(b"changed after base verification")
            return hashlib.sha256(data).hexdigest()

    class Host:
        def free_bytes(self, _):
            return 100 * 1024 ** 3

        def current_release(self):
            return current

        def run(self, argv, timeout):
            calls.append(argv)
            if "verify" in argv:
                release_id = argv[argv.index("--release-id") + 1]
                import signing
                errors = signing.verify_release_files(releases / release_id, public)
                return subprocess.CompletedProcess(argv, int(bool(errors)), json.dumps({"ok": not errors}), "")
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    class Stager(stage.UpdaterStage):
        def _native(self, name):
            return str(native / name)

        def _dev(self, path):
            return str(root / path)

        def release_path(self, release_id):
            return str(releases / release_id)

        def _mark_failed(self, *_):
            pass

    stager = Stager()
    stager.root, stager.updates = root, root / "var/lib/rosy/updates"
    stager.host, stager.http = Host(), HTTP()
    hub = FakeGitHub()
    try:
        producer = load("delta_http_publisher", "tools/release/publish_payload_release.py")
        from auto_update_fakes import HOST, T0

        def publish_to_http(arguments):
            assert arguments[:3] == ["gh", "release", "create"]
            paths = [Path(arg) for arg in arguments[4:] if arg in
                     {str(full), str(delta), str(tmp_path / "publish/rollout.json"),
                      str(tmp_path / "publish/rollout.json.sig")}]
            assert len(paths) == 4
            assets = []
            for path in paths:
                name = f"{target.name}/{path.name}"
                hub.assets[name] = path.read_bytes()
                assets.append({"name": path.name, "size": path.stat().st_size,
                    "browser_download_url": f"{hub.base}/dl/{name}"})
            hub.releases = [{"tag_name": f"payload-{target.name}", "draft": False,
                             "prerelease": False, "assets": assets}]
            return 0, "", ""

        publisher = producer.Publisher(release_id=target.name, repo="team/robots", work_dir=tmp_path / "publish",
            key_name="ephemeral-test", private_key=public.with_name("key"), public_key=public,
            local_appdata=tmp_path, evidence_dir=tmp_path / "evidence", gh=publish_to_http,
            ssh=lambda _: (_ for _ in ()).throw(AssertionError("no device access")),
            now=lambda: T0, monotonic=lambda: 0, sleep=lambda _: None)
        rollout = producer.build_rollout(target.name, hashlib.sha256(full.read_bytes()).hexdigest(), "2" * 40,
                                         T0.isoformat(), HOST, 600)
        rollout["delta"] = binding
        publisher.create(rollout, full, HOST, delta_asset=delta)
        name = binding["tarball"]
        hub.assets[f"{target.name}/{name}"] = b"tampered" if mode == "tamper" else delta.read_bytes()
        stager.api_base = hub.base
        # The fixture repository is the same API used by the production discovery parser.
        from auto_update_fakes import REPO
        release = stager._releases({}, REPO)[0]
        rollout = stager._rollout(release)
        if mode in ("tamper", "dirty-base", "raced-base"):
            with pytest.raises(stage.UpdateError):
                stager._stage_once({}, release, rollout)
            assert not (releases / target.name).exists()
        else:
            stager._stage_once({}, release, rollout)
            import signing
            assert signing.verify_release_files(releases / target.name, public) == []
            assert (releases / target.name / "SHA256SUMS").read_bytes() == (target / "SHA256SUMS").read_bytes()
            assert (releases / target.name / "manifest.json").read_bytes() == (target / "manifest.json").read_bytes()
        downloads = [path for path, _ in hub.requests if path.endswith(".tar.gz")]
        if mode in ("same", "healthfail"):
            assert downloads == [f"/dl/{target.name}/{name}"]
            assert (releases / current / "install/pkg/a.py").read_bytes() == b"old\n"
            assert (releases / current / "install/pkg/b.py").stat().st_ino == (releases / target.name / "install/pkg/b.py").stat().st_ino
        elif mode in ("different", "missing"):
            assert downloads == [f"/dl/{target.name}/{target.name}.tar.gz"]
        elif mode == "dirty-base":
            assert downloads == []
        assert not any("activate" in arg for argv in calls for arg in argv)
        assert (releases.parent / "current").resolve().name == current
        assert identity.read_bytes() == b"preserve identity WiFi calibration"
        if mode == "healthfail":
            # Exercise the unchanged application activation/health/rollback
            # coordinator on the tree reconstructed by the real delta unpacker.
            from auto_update_fakes import BOOT, FakeHost, updater, write_json, kinds
            boot = root / "proc/sys/kernel/random/boot_id"
            boot.parent.mkdir(parents=True)
            boot.write_text(BOOT + "\n")
            (root / "opt/rosy/native-runtime").mkdir(parents=True)
            write_json(root / "var/lib/rosy/updates/config.json", {"enabled": True, "repo": REPO})
            fake = FakeHost(root, current=current)
            fake.overrides["ready"] = lambda h, argv: subprocess.CompletedProcess(
                argv, 1, "", "health failed") if h.links["current"] == target.name else None
            result = updater(fake, hub).run()
            assert result["phase"] == "rolled_back", result
            assert fake.links["current"] == current
            assert "activate" in kinds(fake) and "rollback" in kinds(fake)
            assert (releases / current / "install/pkg/a.py").read_bytes() == b"old\n"
            assert identity.read_bytes() == b"preserve identity WiFi calibration"
    finally:
        hub.close()
