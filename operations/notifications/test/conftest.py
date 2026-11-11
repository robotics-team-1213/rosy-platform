import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'operations/notifications/src'))
sys.path.insert(0, str(ROOT / 'contracts/foundation'))
sys.path.insert(0, str(ROOT / 'operations/fleet'))
