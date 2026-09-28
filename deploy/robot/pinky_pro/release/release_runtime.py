"""Host-only Docker adapter. A health result identifies the actual candidate image."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from bundle import BundleError
from layout import read_activation

PROJECT_LABEL = "label=com.docker.compose.project=rosy-runtime"


class DockerRuntime:
    def __init__(self, layout, *, runner=subprocess.run):
        self.layout, self.runner = layout, runner

    def run(self, argv, **kwargs):
        result = self.runner(argv, capture_output=True, text=True, check=False, timeout=300, **kwargs)
        if result.returncode:
            # Docker errors may print interpolation values from runtime.env. Keep those out of API/logs.
            raise BundleError("RUNTIME_COMMAND", f"{argv[0]} {argv[1]} failed (exit {result.returncode})")
        return result.stdout

    def running(self):
        return self.run(["docker", "ps", "-q", "--filter", PROJECT_LABEL]).split()

    def assert_stopped(self):
        if self.running():
            raise BundleError("RUNTIME_BUSY", "stop ROSY runtime for maintenance before install/rollback")

    def stop(self):
        ids = self.running()
        if ids:
            self.run(["docker", "stop", "--time", "10", *ids])
        self.assert_stopped()

    def load_images(self, root, manifest):
        for name, file in (("rosy_core", "rosy-core"), ("rosy_io", "rosy-io")):
            self.run(["docker", "image", "load", "--input", str(root / "images" / f"{file}.oci.tar")])
            digest = manifest["containers"][name]
            images = json.loads(self.run(["docker", "image", "inspect", digest]))
            if (len(images) != 1 or images[0].get("Id") != digest
                    or images[0].get("Architecture") != "arm64" or images[0].get("Os") != "linux"):
                raise BundleError("IMAGE_IDENTITY", "loaded image does not match signed ARM64 image identity")

    def environment(self):
        path = self.layout.etc / "runtime.env"
        if path.is_symlink():
            raise BundleError("RUNTIME_ENV", "runtime.env must be a regular host-owned file")
        env = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise BundleError("RUNTIME_ENV", "runtime.env must contain literal KEY=value lines")
            if key in env:
                raise BundleError("RUNTIME_ENV", "runtime.env contains duplicate keys")
            env[key] = value
        if not env.get("ROS_DOMAIN_ID") or not env.get("ROSY_NAMESPACE"):
            raise BundleError("ROBOT_IDENTITY_MISSING", "runtime.env must identify this robot")
        for name in ("ROSY_UID", "ROSY_GID"):
            if not env.get(name, "").isdigit() or int(env[name]) == 0:
                raise BundleError("RUNTIME_ACCOUNT", "configure a non-root dedicated ROSY_UID/ROSY_GID")
        # Do not inherit COMPOSE_FILE/PROFILES or arbitrary ROSY overrides from the caller.
        base = {k: v for k, v in os.environ.items() if not k.startswith(("ROSY_", "COMPOSE_"))}
        return {**base, **env}

    def prepare_data(self, path):
        env = self.environment()
        if os.name == "posix":
            for entry in [path, *path.rglob("*")]:
                os.chown(entry, int(env["ROSY_UID"]), int(env["ROSY_GID"]))
                entry.chmod(0o750 if entry.is_dir() else 0o640)

    def start(self, mode):
        if mode != "core":
            raise BundleError("COMMISSIONING_REQUIRED", "release runtime starts core only")
        if self.layout.recovery_hold.exists():
            raise BundleError("RECOVERY_HELD", "clear recovery hold deliberately before starting")
        record = read_activation(self.layout)
        root = Path(record.release_path)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        config = self.layout.config_generation(record.config_generation) / "rosy.yaml"
        working = self.layout.var / "data-working" / record.data_generation
        if not config.is_file() or not working.is_dir():
            raise BundleError("GENERATION_MISSING", "activation config or working data is unavailable")
        env = self.environment()
        if os.name == "posix":
            os.chown(config, 0, int(env["ROSY_GID"]))
            config.chmod(0o440)
        env.update(ROSY_RUNTIME_MODE="core", ROSY_CORE_IMAGE=manifest["containers"]["rosy_core"],
                   ROSY_IO_IMAGE=manifest["containers"]["rosy_io"], ROSY_CONFIG_PATH=str(config),
                   ROSY_DATA_PATH=str(working), ROSY_DATA_GENERATION=record.data_generation)
        self.run(["docker", "compose", "--project-name", "rosy-runtime", "--env-file",
                  str(self.layout.etc / "runtime.env"), "-f", str(root / "runtime/compose.yaml"),
                  "up", "-d", "--no-build", "--pull", "never", "--remove-orphans", "rosy-core"], env=env)

    def healthy(self):
        try:
            record = read_activation(self.layout)
            manifest = json.loads((Path(record.release_path) / "manifest.json").read_text(encoding="utf-8"))
            ids = self.running()
            if len(ids) != 1:
                return False
            container = json.loads(self.run(["docker", "inspect", ids[0]]))[0]
            return (container.get("Image") == manifest["containers"]["rosy_core"]
                    and container.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "rosy-core"
                    and container.get("State", {}).get("Running") is True
                    and container.get("State", {}).get("Health", {}).get("Status") == "healthy")
        except (BundleError, OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
            return False
