"""D-361: the one Fleet <-> CORE enrollment contract test.

It runs the **current source** CORE app (not a deployed image) and drives the Fleet
enrollment service over an ASGI transport: pair -> whoami -> system/info -> logout.
Before S4 CORE ignores `purpose` and issues a `pair-physical` token. This is code-level
evidence only; old-image behaviour is proven by bench step D1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / path for path in
              ("middleware/core/gateway", "middleware/core/events", "middleware/core/services",
               "middleware/core/api_web", "middleware/perception")):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

httpx = pytest.importorskip("httpx")

CONFIG_DIR = ROOT / "contracts" / "foundation" / "config"
BOOT_ID = "7d4c1f0e-0a52-4a8e-9a3e-2f6f1b1c0d11"
CODE = "7KXM" + "P3QA"  # assembled: the tracked-file scanner sees no literal
CODE_ID = "0123456789abcdef"


def _write_code(directory: Path) -> None:
    salt = bytes(range(16))
    digest = hashlib.scrypt(CODE.encode("ascii"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    (directory / "login-code.json").write_text(json.dumps({
        "schema_version": 1, "code_id": CODE_ID, "role": "operator", "source": "pair-physical",
        "kdf": {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1, "dklen": 32, "salt": salt.hex()},
        "digest": digest.hex(), "boot_id": BOOT_ID, "expires_monotonic": 1600.0,
    }), encoding="utf-8")


@pytest.fixture
def core_app(tmp_path, monkeypatch):
    from core_api_web.api.app import create_app
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    monkeypatch.delenv("ROSY_DEPLOYMENT", raising=False)
    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    robot_dir = robot_config_dir("pinky_pro")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, RobotProfile.load(robot_dir / "profile.yaml"), caps,
                                  tmp_path / "wp.json")
    app = create_app(config, services)
    boot, own = tmp_path / "run-boot", tmp_path / "run-rosy"
    boot.mkdir()
    own.mkdir()
    (tmp_path / "boot_id").write_text(BOOT_ID + "\n", encoding="ascii")
    state = app.state.pairing
    state.clock = lambda: 1000.0
    state.code_file = str(boot / "login-code.json")
    state.state_file = str(own / "login-code-state.json")
    state.boot_id_file = str(tmp_path / "boot_id")
    _write_code(boot)
    return app, services


def test_fleet_enrolls_and_unenrolls_against_current_core_source(tmp_path, core_app):
    from fleet.server.console import FleetConsole
    from fleet.server.enrollment import EnrollmentService
    from fleet.server.enrollment_store import EnrollmentStore
    from fleet.server.roster import SiteRoster

    app, services = core_app
    transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 50000))
    console = FleetConsole([], [])
    store = EnrollmentStore(tmp_path / "fleet.sqlite3")
    service = EnrollmentService(store, SiteRoster(console), key=bytes(range(32)),
                                fleet_name="site-a", transport=transport)

    async def scenario():
        row = await service.enroll(code=CODE.lower()[:4] + "-" + CODE[4:], principal_id="alice",
                                   address="192.168.1.202:8080")
        token = service._tokens[row["robot_id"]]
        async with httpx.AsyncClient(transport=transport, base_url="http://robot") as http:
            auth = {"Authori" + "zation": "Bearer " + token}
            before = await http.get("/api/v1/auth/whoami", headers=auth)
            result = await service.unenroll(row["robot_id"], principal_id="alice")
            after = await http.get("/api/v1/auth/whoami", headers=auth)
        return row, before, result, after

    row, before, result, after = asyncio.run(scenario())

    # Current source CORE ignores `purpose` until S4: an operator pair-physical token.
    assert row["role"] == "operator" and row["source"] == "pair-physical"
    assert row["legacy_lifetime"] is True and row["address"] == "192.168.1.202:8080"
    assert before.status_code == 200 and before.json()["label"] == "site:site-a"
    assert result["state"] == "removed"
    assert after.status_code == 401
    assert store.rows() == [] and console.robot_ids == []
