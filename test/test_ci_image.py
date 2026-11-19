"""The CI image carries the installs ci.yml jobs used to repeat; ci.yml pins it by digest."""

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = ROOT / ".github" / "ci-image" / "Dockerfile"
IMAGE = re.compile(r"^ghcr\.io/[a-z0-9-]+/rosy-ci@sha256:[0-9a-f]{64}$")


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def test_ci_jobs_run_in_the_prebuilt_image_pinned_by_digest():
    jobs = _jobs()
    for name in ("scope", "test"):
        image = jobs[name]["container"]["image"].split()[0]
        assert IMAGE.match(image), f"{name}: pin the CI image by digest, not a tag: {image}"
    assert jobs["scope"]["container"]["image"] == jobs["test"]["container"]["image"]


def test_test_jobs_install_no_apt_packages_and_never_apt_get_update():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "apt-get" not in text, "apt belongs in the image; the runner mirror outage must not reach jobs"
    for job in _jobs().values():
        for step in job["steps"]:
            run = step.get("run", "")
            assert "apt-get update" not in run and "apt-get install" not in run, step["name"]
            assert not (
                "pip3 install" in run and "--no-index" not in run and "--target /tmp/" not in run
                and "download.pytorch.org" not in run
            ), f"{step['name']}: common pip sets are baked into the image"


def test_readiness_asserts_survive_the_removed_install_steps():
    steps = {s["name"]: s["run"] for s in _jobs()["test"]["steps"] if "run" in s}
    run = steps["CI image readiness"]
    for needle in ("colcon", "openssl", "rauc", 'httpx.__version__ == "0.28.1"', '"1.64.1"', "joserfc",
                   'cryptography.__version__ == "50.0.0"', "PolicyBuilder, Store", "slam_toolbox", "ROSY_TEST_RAUC_DEB"):
        assert needle in run, needle
    scope = _jobs()["scope"]["steps"]
    assert any("import yaml" in s.get("run", "") for s in scope), "selector tools readiness"
    assert "dpkg -x /opt/rosy-ci/debs/" in steps["Guard (SaveMap request type and result codes)"]


def test_image_dockerfile_holds_the_pins_ci_used_to_install():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert text.startswith("# Prebuilt CI image") and "FROM ros:jazzy-ros-base" in text
    for needle in ("device-python-requirements.txt", "--require-hashes", "receiver-crypto-requirements.txt",
                   "requirements-cell.lock", "playwright==1.64.1", "httpx==0.28.1", "oauthlib==4.0.0",
                   "joserfc==1.7.5", "rauc=1.11.3-2", "fonts-noto-cjk", "playwright install --with-deps chromium",
                   "manylinux_2_28_x86_64", "PYTHONPATH=/opt/rosy-ci/receiver-crypto"):
        assert needle in text, needle


def test_image_workflow_pushes_with_the_job_token_and_prints_the_digest():
    doc = yaml.safe_load((ROOT / ".github/workflows/build-ci-image.yml").read_text(encoding="utf-8"))
    assert doc["permissions"] == {"contents": "read", "packages": "write"}
    text = (ROOT / ".github/workflows/build-ci-image.yml").read_text(encoding="utf-8")
    assert "github.token" in text and "RepoDigests" in text and "docker push" in text
