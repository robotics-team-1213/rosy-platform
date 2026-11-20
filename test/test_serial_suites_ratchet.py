"""A new serial_suites.txt line or HOST_ALONE entry must say when it was measured serial vs -n, who owns it, and when it expires."""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "remote"))
import xdist_plan as xp  # noqa: E402

MEASURED = re.compile(r"measured \d{4}-\d\d-\d\d serial vs -n, owner \S+, expires \d{4}-\d\d-\d\d")
GRANDFATHERED = {"integrations/simulation/gazebo/test", "learning/envs/isaac/test"}  # 2026-11-20 baseline; shrink only


def unmeasured(text: str) -> list[str]:
    rows = [line.split("#", 1) + [""] for line in text.splitlines() if line.split("#", 1)[0].strip()]
    return [r[0].strip() for r in rows if r[0].strip() not in GRANDFATHERED and not MEASURED.search(r[1])]


def test_serial_lines_carry_measurement_owner_and_expiry():
    assert unmeasured(xp.SERIAL_FILE.read_text(encoding="utf-8")) == []


def test_the_ratchet_rejects_a_bare_new_line_and_accepts_a_measured_one():
    assert unmeasured("new/suite  # because\n") == ["new/suite"]
    assert unmeasured("new/suite  # measured 2026-11-20 serial vs -n, owner me, expires 2026-12-20\n") == []


def test_host_alone_entries_carry_the_same_comment():
    src = Path(xp.__file__).read_text(encoding="utf-8")
    block = re.search(r"HOST_ALONE: tuple\[str, \.\.\.\] = \((.*)", src).group(1)
    assert block.strip() == ")" or MEASURED.search(block), "a HOST_ALONE entry needs the measured/owner/expires comment"


def test_each_xdist_worker_gets_its_own_home_xdg_and_tmp(tmp_path):
    spec = importlib.util.spec_from_file_location("rosy_root_conftest", ROOT / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a, b, serial = {"PYTEST_XDIST_WORKER": "gw0"}, {"PYTEST_XDIST_WORKER": "gw1"}, {}
    for env in (a, b, serial):
        mod.isolate_worker(env, str(tmp_path))
    assert serial == {}, "a serial run keeps the host's HOME"
    keys = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR")
    assert all(Path(a[k]).is_dir() and a[k] != b[k] for k in keys)
