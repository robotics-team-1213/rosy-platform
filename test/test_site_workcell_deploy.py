"""Opt-in workcell wiring preserves role isolation and existing credential bootstrapping."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from deploy.site import secret_exec

SITE = Path(__file__).resolve().parents[1] / "deploy/site"


@pytest.mark.parametrize("configured", [None, "", "three-arms"])
def test_compose_renders_default_or_complete_administrator_arm_mapping(tmp_path, configured):
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose CLI is required for interpolation acceptance")
    base = tmp_path / "base.yaml"
    base.write_text("services:\n  fleet:\n    image: example.invalid/fixture:unused\n"
                    "  vision:\n    image: example.invalid/fixture:unused\n", encoding="utf-8")
    env_file = tmp_path / "empty.env"
    env_file.write_text("", encoding="utf-8")
    env = dict(os.environ)
    variable = "ROSY_SITE_WORKCELL_ARM_CREDENTIAL_PATHS"
    env.pop(variable, None)
    env.update(ROSY_SITE_WORKCELL_MANIFEST=str(tmp_path / "observations.yaml"),
               ROSY_SITE_WORKCELL_ARM_SECRETS_DIR=str(tmp_path / "arms"),
               ROSY_SITE_WORKCELL_CAMERA_SECRETS_DIR=str(tmp_path / "cameras"))
    expected = {f"ROSY_ARM_{arm}_TOKEN": f"/run/rosy-workcell-arm-secrets/arm_{arm.lower()}_token"
                for arm in ("A", "B", "S") if configured == "three-arms" or arm != "S"}
    if configured is not None:
        env[variable] = json.dumps(expected) if configured == "three-arms" else configured
    result = subprocess.run([docker, "compose", "--env-file", str(env_file), "-f", str(base),
                             "-f", str(SITE / "compose.workcell.yaml"), "config", "--format", "json"],
                            env=env, capture_output=True, text=True, timeout=30, check=True)
    services = json.loads(result.stdout)["services"]
    assert json.loads(services["fleet"]["environment"]["ROSY_ADDITIONAL_CREDENTIAL_PATHS"]) == expected
    vision = json.loads(services["vision"]["environment"]["ROSY_ADDITIONAL_CREDENTIAL_PATHS"])
    assert set(vision) == {"ROSY_CAMERA_OVERHEAD_TOKEN", "ROSY_CAMERA_WRIST_A_TOKEN", "ROSY_CAMERA_WRIST_B_TOKEN"}


def test_workcell_overlay_adds_manifest_and_separate_role_secrets_without_replacing_commands():
    overlay = yaml.safe_load((SITE / "compose.workcell.yaml").read_text(encoding="utf-8"))
    assert set(overlay["services"]) == {"fleet", "vision"}
    roles = {
        "fleet": ("arm", {"ROSY_ARM_A_TOKEN", "ROSY_ARM_B_TOKEN"}),
        "vision": ("camera", {"ROSY_CAMERA_OVERHEAD_TOKEN", "ROSY_CAMERA_WRIST_A_TOKEN",
                               "ROSY_CAMERA_WRIST_B_TOKEN"}),
    }
    for service, (role, names) in roles.items():
        config = overlay["services"][service]
        assert "command" not in config and "entrypoint" not in config
        assert "ROSY_CREDENTIAL_PATHS" not in config["environment"]
        assert config["environment"]["ROSY_WORKCELL_OBSERVATIONS"] == "/run/rosy-workcell/observations.yaml"
        mapping = config["environment"]["ROSY_ADDITIONAL_CREDENTIAL_PATHS"]
        if service == "fleet":
            prefix = "${ROSY_SITE_WORKCELL_ARM_CREDENTIAL_PATHS:-"
            assert mapping.startswith(prefix) and mapping.endswith("}")
            mapping = mapping[len(prefix):-1]
        paths = json.loads(mapping)
        assert set(paths) == names
        volumes = config["volumes"]
        assert len(volumes) == 2
        assert all(v["type"] == "bind" and v["read_only"] and not v["bind"]["create_host_path"]
                   for v in volumes)
        assert volumes[0]["target"] == "/run/rosy-workcell/observations.yaml"
        assert "ROSY_SITE_WORKCELL_MANIFEST:?" in volumes[0]["source"]
        assert volumes[1]["target"] == f"/run/rosy-workcell-{role}-secrets"
        assert all(Path(path).parent.as_posix() == volumes[1]["target"] for path in paths.values())


class ExecIntercepted(Exception):
    pass


def _bootstrap(monkeypatch, tmp_path, *, additional):
    base = tmp_path / "base"
    base.write_text("base-token\n", encoding="utf-8")
    extra = tmp_path / "extra"
    extra.write_text("role-token\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_CREDENTIAL_PATHS", json.dumps({"ROSY_BASE_TOKEN": str(base)}))
    monkeypatch.setenv("ROSY_ADDITIONAL_CREDENTIAL_PATHS", additional.replace("EXTRA_PATH", extra.as_posix()))
    monkeypatch.setenv("ROSY_RUN_UID", "10001")
    monkeypatch.setenv("ROSY_RUN_GID", "10001")
    monkeypatch.setattr(secret_exec.os, "geteuid", lambda: 10001, raising=False)
    captured = {}

    def execvpe(program, command, environ):
        captured.update(program=program, command=command, environ=dict(environ))
        raise ExecIntercepted

    monkeypatch.setattr(secret_exec.os, "execvpe", execvpe)
    return captured


def test_bootstrap_adds_role_secrets_without_losing_base_or_pairing_credentials(monkeypatch, tmp_path):
    captured = _bootstrap(monkeypatch, tmp_path, additional='{"ROSY_ARM_A_TOKEN":"EXTRA_PATH"}')
    with pytest.raises(ExecIntercepted):
        secret_exec.main(["--", "fleet", "console"])
    assert captured["command"] == ["fleet", "console"]
    assert captured["environ"]["ROSY_BASE_TOKEN"] == "base-token"
    assert captured["environ"]["ROSY_ARM_A_TOKEN"] == "role-token"
    assert "ROSY_CREDENTIAL_PATHS" not in captured["environ"]
    assert "ROSY_ADDITIONAL_CREDENTIAL_PATHS" not in captured["environ"]


@pytest.mark.parametrize("missing_s", [False, True])
def test_three_arm_bootstrap_preserves_all_credentials_or_refuses_missing_s(monkeypatch, tmp_path, missing_s):
    captured = _bootstrap(monkeypatch, tmp_path, additional="{}")
    paths, values = {}, {}
    for arm in ("A", "B", "S"):
        name = f"ROSY_ARM_{arm}_TOKEN"
        path = tmp_path / f"arm_{arm.lower()}_token"
        values[name] = f"role-{arm}"
        if not (missing_s and arm == "S"):
            path.write_text(values[name] + "\n", encoding="utf-8")
        paths[name] = str(path)
    monkeypatch.setenv("ROSY_ADDITIONAL_CREDENTIAL_PATHS", json.dumps(paths))
    if missing_s:
        with pytest.raises(SystemExit, match="cannot read configured secret file for ROSY_ARM_S_TOKEN"):
            secret_exec.main(["--", "fleet", "console"])
        assert not captured
    else:
        with pytest.raises(ExecIntercepted):
            secret_exec.main(["--", "fleet", "console"])
        assert captured["environ"]["ROSY_BASE_TOKEN"] == "base-token"
        assert {name: captured["environ"][name] for name in values} == values
        assert "ROSY_ADDITIONAL_CREDENTIAL_PATHS" not in captured["environ"]


@pytest.mark.parametrize("additional", [
    "not-json", "[]", '{"ROSY_BASE_TOKEN":"EXTRA_PATH"}', '{"bad-name":"EXTRA_PATH"}',
    '{"ROSY_ARM_A_TOKEN":42}', '{"ROSY_ARM_A_TOKEN":"missing-file"}',
])
def test_bootstrap_rejects_invalid_or_overwriting_role_credentials(monkeypatch, tmp_path, additional):
    captured = _bootstrap(monkeypatch, tmp_path, additional=additional)
    with pytest.raises(SystemExit):
        secret_exec.main(["--", "fleet", "console"])
    assert not captured
