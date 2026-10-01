"""D-373 decision 5: the site units for model/watch.py read config and token from files."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "deploy" / "site"
if str(ROOT / "tools" / "perception" / "model") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "perception" / "model"))

import watch  # noqa: E402

CONFIG = "/etc/rosy/model-watch.yaml"
TOKEN = "/etc/rosy/site/secrets/hf_token"


def _unit(name: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in (SITE / name).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            key, _, value = line.partition("=")
            keys.setdefault(key, []).append(value)
    return keys


def test_service_reads_config_and_token_file_only():
    unit = _unit("rosy-model-watch.service")
    (exec_start,) = unit["ExecStart"]
    assert exec_start.endswith(f"--config {CONFIG}")
    assert exec_start.split()[1].endswith("/tools/perception/model/watch.py")
    assert f"HF_TOKEN_FILE={TOKEN}" in unit["Environment"]
    # the token never appears on a command line or as a literal value
    for value in exec_start.split():
        assert "token" not in value.lower() and not value.startswith("hf_")
    assert not any(v.startswith("HF_TOKEN=") for v in unit["Environment"])
    assert "EnvironmentFile" not in unit


def test_service_is_an_unprivileged_hardened_oneshot():
    unit = _unit("rosy-model-watch.service")
    assert unit["Type"] == ["oneshot"]
    assert unit["User"] == ["rosy-model-watch"] and unit["Group"] == ["rosy-model-watch"]
    assert unit["StateDirectory"] == ["rosy-model-watch"]
    for key, value in (("NoNewPrivileges", "yes"), ("ProtectSystem", "strict"),
                       ("ProtectHome", "yes"), ("PrivateTmp", "yes"), ("UMask", "0077"),
                       ("PrivateDevices", "yes"), ("ProtectKernelTunables", "yes"),
                       ("ProtectKernelModules", "yes"), ("ProtectKernelLogs", "yes"),
                       ("RestrictNamespaces", "yes"), ("SystemCallFilter", "@system-service")):
        assert unit[key] == [value], key
    # StateDirectory is the only writable path in the unit; the store folder is added
    # by install-model-watch.sh as a drop-in, because its path is site config
    assert "ReadWritePaths" not in unit
    # one run may push to many robots: see the README's worst-case formula
    assert unit["TimeoutStartSec"] == ["6h"]


def test_timer_runs_the_service_every_10_minutes():
    timer = _unit("rosy-model-watch.timer")
    assert timer["Unit"] == ["rosy-model-watch.service"]
    assert timer["OnUnitInactiveSec"] == ["10min"]
    assert timer["WantedBy"] == ["timers.target"]


def test_example_config_matches_the_watcher_and_the_unit_state_dir(tmp_path):
    text = (SITE / "model-watch.yaml.example").read_text(encoding="utf-8")
    filled = text.replace("<robot-name>", "pinky-005").replace("<robot-ip>", "192.0.2.10")
    (tmp_path / "c.yaml").write_text(filled, encoding="utf-8")
    cfg = watch.load_config(tmp_path / "c.yaml")
    assert cfg["backend"] == "inbox" and cfg["store"] == "/srv/rosy/store"  # no HF by default
    assert "repo" not in cfg
    for key in ("intake_out", "state_file"):
        assert cfg[key].startswith("/var/lib/rosy-model-watch/")
    assert not [k for k in cfg if "token" in k.lower()]  # the token is never a config value


def test_readme_documents_the_install_paths():
    readme = (SITE / "README.md").read_text(encoding="utf-8")
    for needle in ("rosy-model-watch.timer", CONFIG, TOKEN, "rosy-model-watch",
                   "authorized_keys", "ssh-keygen", "since:", "max_attempts",
                   "not part of the signed site candidate", "install-model-watch.sh",
                   "release-hold", "TimeoutStartSec=6h", "An empty or missing file means no token",
                   "models/inbox", "READY", "models/accepted", "models/rejected", "backend: hf",
                   "ReadWritePaths", "Google Drive", "NAS"):
        assert needle in " ".join(readme.split()), needle  # prose is line-wrapped
    section = readme.split("## Automatic shadow delivery")[1].split("\n## ")[0]
    assert "operator key" not in section  # the site host has its own key


def test_readme_says_hf_is_optional():
    readme = " ".join((SITE / "README.md").read_text(encoding="utf-8").split())
    section = readme.split("## Automatic shadow delivery")[1].split(" ## ")[0]
    assert "HF is optional" in section
    assert "huggingface_hub" not in section.split("backend: hf")[0]  # not in the default setup
