"""Expose the source contract readers for standalone profile test invocations."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "contracts/foundation"))
