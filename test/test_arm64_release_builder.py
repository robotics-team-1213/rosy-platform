from __future__ import annotations

from pathlib import Path

import pytest

from arm64_release_builder import (
    BuiltImage,
    BuildError,
    BuildRequest,
    assemble_payload,
    build_images,
    main,
    validate_build_daemon,
    validate_request,
)


REVISION = "b" * 40
ROS_IMAGE = "ros:jazzy-ros-base@sha256:" + "a" * 64


def request(tmp_path: Path, **changes) -> BuildRequest:
    values = {
        "repo_root": tmp_path / "repo",
        "output": tmp_path / "payload",
        "release_id": "2026.09.21-001",
        "signing_key_id": "rosy-release-2026-01",
        "ros_image": ROS_IMAGE,
    }
    values.update(changes)
    values["repo_root"].mkdir(exist_ok=True)
    return BuildRequest(**values)


def test_valid_request_requires_native_clean_pinned_inputs(tmp_path):
    selected = validate_request(
        request(tmp_path), machine="aarch64", system="Linux", revision=REVISION, status=""
    )

    assert selected.revision == REVISION
    assert selected.request.ros_image == ROS_IMAGE


@pytest.mark.parametrize("machine", ["x86_64", "AMD64", "armv7l"])
def test_request_rejects_non_native_arm64_host(tmp_path, machine):
    with pytest.raises(BuildError, match="BUILD_HOST_ARCH"):
        validate_request(
            request(tmp_path), machine=machine, system="Linux", revision=REVISION, status=""
        )


def test_request_rejects_non_linux_host_even_if_cpu_reports_aarch64(tmp_path):
    with pytest.raises(BuildError, match="BUILD_HOST_OS"):
        validate_request(
            request(tmp_path),
            machine="aarch64",
            system="Windows",
            revision=REVISION,
            status="",
        )


@pytest.mark.parametrize("architecture", ["amd64", "x86_64", "armv7l", ""])
def test_request_rejects_non_native_arm64_docker_daemon(architecture):
    with pytest.raises(BuildError, match="BUILD_DAEMON_ARCH"):
        validate_build_daemon(architecture)


def test_request_rejects_dirty_or_ambiguous_source(tmp_path):
    with pytest.raises(BuildError, match="SOURCE_DIRTY"):
        validate_request(
            request(tmp_path),
            machine="aarch64",
            system="Linux",
            revision=REVISION,
            status=" M file.py",
        )
    with pytest.raises(BuildError, match="SOURCE_REVISION"):
        validate_request(
            request(tmp_path), machine="aarch64", system="Linux", revision="baffbec", status=""
        )


def test_request_rejects_mutable_ros_base_and_unsafe_output(tmp_path):
    with pytest.raises(BuildError, match="ROS_IMAGE_PIN"):
        validate_request(
            request(tmp_path, ros_image="ros:jazzy-ros-base"),
            machine="aarch64",
            system="Linux",
            revision=REVISION,
            status="",
        )

    existing = tmp_path / "already-there"
    existing.mkdir()
    with pytest.raises(BuildError, match="OUTPUT_EXISTS"):
        validate_request(
            request(tmp_path, output=existing),
            machine="aarch64",
            system="Linux",
            revision=REVISION,
            status="",
        )

    inside = request(tmp_path)
    inside = BuildRequest(**{**inside.__dict__, "output": inside.repo_root / "payload"})
    with pytest.raises(BuildError, match="OUTPUT_LOCATION"):
        validate_request(
            inside, machine="aarch64", system="Linux", revision=REVISION, status=""
        )


class Result:
    def __init__(self, *, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class DockerRunner:
    def __init__(self, inspections):
        self.inspections = iter(inspections)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[:3] == ["docker", "image", "inspect"]:
            import json

            return Result(stdout=json.dumps([next(self.inspections)]))
        return Result()


def inspected(image_id="sha256:" + "c" * 64, **changes):
    value = {
        "Id": image_id,
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
    }
    value.update(changes)
    return value


def validated(tmp_path):
    return validate_request(
        request(tmp_path), machine="aarch64", system="Linux", revision=REVISION, status=""
    )


def test_builder_builds_and_inspects_both_arm64_targets(tmp_path):
    runner = DockerRunner([
        inspected("sha256:" + "c" * 64),
        inspected("sha256:" + "d" * 64),
    ])

    images = build_images(validated(tmp_path), runner=runner)

    assert images["rosy_core"].image_id == "sha256:" + "c" * 64
    assert images["rosy_io"].image_id == "sha256:" + "d" * 64
    builds = [call[0] for call in runner.calls if call[0][:3] == ["docker", "buildx", "build"]]
    assert len(builds) == 2
    assert {cmd[cmd.index("--target") + 1] for cmd in builds} == {"core", "io"}
    assert all(["--platform", "linux/arm64"] == cmd[cmd.index("--platform"):][:2]
               for cmd in builds)
    assert all(f"ROS_IMAGE={ROS_IMAGE}" in cmd for cmd in builds)
    assert all(f"org.opencontainers.image.revision={REVISION}" in cmd for cmd in builds)


@pytest.mark.parametrize(
    "bad, code",
    [
        (inspected(Architecture="amd64"), "IMAGE_ARCH"),
        (inspected(Os="windows"), "IMAGE_OS"),
        (inspected(image_id="not-a-digest"), "IMAGE_ID"),
        (inspected(Config={"Labels": {}}), "IMAGE_REVISION"),
    ],
)
def test_builder_rejects_image_identity_mismatch(tmp_path, bad, code):
    runner = DockerRunner([bad])

    with pytest.raises(BuildError, match=code):
        build_images(validated(tmp_path), runner=runner)


def test_builder_redacts_failed_command_output(tmp_path):
    class FailedRunner:
        def __call__(self, argv, **kwargs):
            return Result(returncode=9, stderr="secret build output")

    with pytest.raises(BuildError, match="BUILD_COMMAND") as raised:
        build_images(validated(tmp_path), runner=FailedRunner())

    assert "secret build output" not in str(raised.value)


def release_images():
    return {
        "rosy_core": BuiltImage(
            name="rosy_core",
            tag="local/rosy-core:test",
            image_id="sha256:" + "c" * 64,
            os="linux",
            architecture="arm64",
            revision=REVISION,
        ),
        "rosy_io": BuiltImage(
            name="rosy_io",
            tag="local/rosy-io:test",
            image_id="sha256:" + "d" * 64,
            os="linux",
            architecture="arm64",
            revision=REVISION,
        ),
    }


def runtime_source(req: BuildRequest):
    root = req.repo_root / "deploy" / "robot" / "pinky_pro"
    (root / "config").mkdir(parents=True)
    (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (root / "config" / "profile.core.yaml").write_text("mode: core\n", encoding="utf-8")
    (root / "config" / "line_follow.yaml").write_text("enabled: false\n", encoding="utf-8")


class SaveRunner:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:3] == ["docker", "image", "save"]:
            tag = argv[-1]
            if tag == self.fail_on:
                return Result(returncode=7, stderr="private daemon detail")
            path = Path(argv[argv.index("--output") + 1])
            path.write_bytes(("archive:" + tag).encode())
        return Result()


def test_payload_contains_exact_runtime_images_provenance_and_manifest(tmp_path):
    import hashlib
    import json

    req = request(tmp_path)
    runtime_source(req)
    selected = validate_request(
        req, machine="aarch64", system="Linux", revision=REVISION, status=""
    )
    runner = SaveRunner()

    output = assemble_payload(
        selected,
        release_images(),
        runner=runner,
        created_at="2026-09-21T12:34:56Z",
        docker_version="29.7.2",
    )

    assert output == req.output.resolve()
    assert not (output / "SHA256SUMS").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_revision"] == REVISION
    assert manifest["containers"] == {
        "rosy_core": "sha256:" + "c" * 64,
        "rosy_io": "sha256:" + "d" * 64,
    }
    declared = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert set(declared) == actual
    for name, digest in declared.items():
        assert digest == hashlib.sha256((output / name).read_bytes()).hexdigest()
    provenance = json.loads((output / "build-provenance.json").read_text(encoding="utf-8"))
    assert provenance["ros_base_image"] == ROS_IMAGE
    assert provenance["docker_version"] == "29.7.2"
    assert provenance["source_revision"] == REVISION
    saves = [call for call in runner.calls if call[:3] == ["docker", "image", "save"]]
    assert len(saves) == 2
    assert {call[-1] for call in saves} == {
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
    }


def test_payload_failure_leaves_no_output_or_staging_directory(tmp_path):
    req = request(tmp_path)
    runtime_source(req)
    selected = validate_request(
        req, machine="aarch64", system="Linux", revision=REVISION, status=""
    )
    before = set(tmp_path.iterdir())

    with pytest.raises(BuildError, match="BUILD_COMMAND"):
        assemble_payload(
            selected,
            release_images(),
            runner=SaveRunner(fail_on="sha256:" + "d" * 64),
            created_at="2026-09-21T12:34:56Z",
            docker_version="29.7.2",
        )

    assert not req.output.exists()
    assert set(tmp_path.iterdir()) == before


def test_payload_rechecks_verified_image_metadata(tmp_path):
    from dataclasses import replace

    req = request(tmp_path)
    runtime_source(req)
    selected = validate_request(
        req, machine="aarch64", system="Linux", revision=REVISION, status=""
    )
    images = release_images()
    images["rosy_io"] = replace(images["rosy_io"], architecture="amd64")

    with pytest.raises(BuildError, match="IMAGE_ARCH"):
        assemble_payload(
            selected,
            images,
            runner=SaveRunner(),
            created_at="2026-09-21T12:34:56Z",
            docker_version="29.7.2",
        )


def test_payload_rejects_one_image_reused_for_both_runtime_roles(tmp_path):
    from dataclasses import replace

    req = request(tmp_path)
    runtime_source(req)
    selected = validate_request(
        req, machine="aarch64", system="Linux", revision=REVISION, status=""
    )
    images = release_images()
    images["rosy_io"] = replace(
        images["rosy_io"], image_id=images["rosy_core"].image_id
    )

    with pytest.raises(BuildError, match="IMAGE_COLLISION"):
        assemble_payload(
            selected,
            images,
            runner=SaveRunner(),
            created_at="2026-09-21T12:34:56Z",
            docker_version="29.7.2",
        )


@pytest.mark.parametrize(
    "release_id,key_id,code",
    [
        ("latest", "rosy-release-2026-01", "RELEASE_ID"),
        ("2026.09.21-001", "INVALID KEY", "SIGNING_KEY_ID"),
    ],
)
def test_request_rejects_malformed_release_or_key_identity(tmp_path, release_id, key_id, code):
    with pytest.raises(BuildError, match=code):
        validate_request(
            request(tmp_path, release_id=release_id, signing_key_id=key_id),
            machine="aarch64",
            system="Linux",
            revision=REVISION,
            status="",
        )


def test_request_rejects_os_suite_the_device_updater_cannot_verify(tmp_path):
    with pytest.raises(BuildError, match="OS_SUITE"):
        validate_request(
            request(tmp_path, os_suite="jammy"),
            machine="aarch64",
            system="Linux",
            revision=REVISION,
            status="",
        )


class CliRunner:
    def __init__(self):
        self.calls = []
        self.inspections = iter([
            inspected("sha256:" + "c" * 64),
            inspected("sha256:" + "d" * 64),
        ])

    def __call__(self, argv, **kwargs):
        import json

        self.calls.append(argv)
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return Result(stdout=REVISION + "\n")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return Result(stdout="")
        if argv[:2] == ["docker", "version"]:
            return Result(stdout="29.7.2\n")
        if argv[:2] == ["docker", "info"]:
            return Result(stdout="aarch64\n")
        if argv[:3] == ["docker", "image", "inspect"]:
            return Result(stdout=json.dumps([next(self.inspections)]))
        if argv[:3] == ["docker", "image", "save"]:
            Path(argv[argv.index("--output") + 1]).write_bytes(b"oci archive")
        return Result()


def test_cli_prepares_unsigned_payload_without_accessing_a_private_key(tmp_path, capsys):
    from datetime import datetime, timezone

    req = request(tmp_path)
    runtime_source(req)
    runner = CliRunner()

    result = main(
        [
            "--repo-root", str(req.repo_root),
            "--output", str(req.output),
            "--release-id", req.release_id,
            "--signing-key-id", req.signing_key_id,
            "--ros-image", req.ros_image,
        ],
        machine="aarch64",
        system="Linux",
        runner=runner,
        clock=lambda: datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert result == 0
    rendered = __import__("json").loads(capsys.readouterr().out)
    assert rendered == {
        "ok": True,
        "output": str(req.output.resolve()),
        "release_id": req.release_id,
        "git_revision": REVISION,
        "signed": False,
    }
    assert req.output.is_dir()
    assert not any("private" in " ".join(call).lower() for call in runner.calls)


def test_first_device_runbook_connects_native_build_to_offline_signing():
    root = Path(__file__).resolve().parents[1]
    runbook = (root / "docs/deployment/pinky-pro-first-device-runbook.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "arm64_release_builder.py",
        "uname -m",
        "@sha256:",
        "package_release.py",
        "--private-key",
        "signed-bundle-verification.json",
    ):
        assert required in runbook
    assert runbook.index("arm64_release_builder.py") < runbook.index("package_release.py")
