from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_omx_ai_vendor_sources_are_pinned_to_immutable_revisions():
    lock_path = ROOT / "deploy" / "omx" / "stack.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))

    assert lock["target"]["model"] == "omx_ai"
    assert lock["target"]["ros_distro"] == "jazzy"
    assert lock["target"]["workstation_arch"] == "amd64"
    assert lock["vendor"]["release"] == "5.1.2"
    assert lock["vendor"]["repository"] == "https://github.com/ROBOTIS-GIT/open_manipulator.git"
    assert lock["vendor"]["revision"] == "0a4af6a923b8b7d80b8c20506d1839c54d2e993e"
    assert lock["vendor"]["repositories"]
    for dependency in lock["vendor"]["repositories"]:
        assert len(dependency["revision"]) == 40
        assert set(dependency["revision"]) <= set("0123456789abcdef")
