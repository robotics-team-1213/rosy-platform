"""Put this test directory on sys.path so `import lane_sim` resolves under
pytest's rootdir rules even when a test file is collected from elsewhere."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
