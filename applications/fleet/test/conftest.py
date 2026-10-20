"""App tests use shared browser helpers without importing a Fleet backend fixture."""
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[3] / 'test'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dev'))
