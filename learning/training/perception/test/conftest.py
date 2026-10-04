import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[4]
for p in (ROOT / "learning" / "training" / "perception" / "dataset", ROOT / "src" / "runtime" / "sensing",
          ROOT / "src" / "contracts" / "foundation"):  # core_common, needed by control (D-424)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def private_test_delivery_journal(monkeypatch, tmp_path):
    """Fake runners must never add simulated success to an operator journal."""
    monkeypatch.setenv('ROSY_MODEL_DELIVERY_JOURNAL_DIR', str(tmp_path / 'delivery-journal'))
