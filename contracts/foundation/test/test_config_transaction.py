import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import yaml
from core_common.config import patch_local_config
from core_common.config_transaction import transaction


class OverlayConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'rosy.yaml'
        self.path.write_text('robot:\n  id: preserved\nauth:\n  tokens: []\n', encoding='utf8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_writers_and_repository_nested_transaction_preserve_fields(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(lambda n: patch_local_config({'settings': {str(n): n}}, self.path), range(24)))
        with transaction(self.path):
            patch_local_config({'auth': {'peer_pairing': {'schema': 'rosy.peer-grants/1'}}}, self.path)
        result = yaml.safe_load(self.path.read_text())
        self.assertEqual({str(n): n for n in range(24)}, result['settings'])
        self.assertEqual('preserved', result['robot']['id'])
        self.assertEqual([], result['auth']['tokens'])

    def test_distinct_processes_serialize_same_overlay_without_lost_updates(self):
        program = ('import sys; from pathlib import Path; from core_common.config import patch_local_config; '
                   'patch_local_config({"process": {sys.argv[2]: sys.argv[2]}}, Path(sys.argv[1]))')
        # A bare `python -c` child has no pytest sys.path; point it at this source tree
        # so the test runs wherever the suite runs (host, CI container, installed robot).
        env = {**os.environ,
               'PYTHONPATH': str(Path(__file__).resolve().parents[1])
               + (os.pathsep + os.environ['PYTHONPATH'] if 'PYTHONPATH' in os.environ else '')}
        children = [subprocess.Popen([sys.executable, '-c', program, str(self.path), str(n)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                    for n in range(8)]
        for child in children:
            out, err = child.communicate(timeout=15)
            self.assertEqual(0, child.returncode, err.decode())
        self.assertEqual({str(n): str(n) for n in range(8)}, yaml.safe_load(self.path.read_text())['process'])

    def test_real_replace_failure_leaves_file_identical_and_no_temporary_left(self):
        before = self.path.read_bytes()
        with patch('core_common.config.os.replace', side_effect=OSError('fixture replace refused')):
            with self.assertRaises(OSError):
                patch_local_config({'auth': {'tokens': ['unexpected']}}, self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.path.parent.glob('rosy.yaml.*.tmp')))


if __name__ == '__main__':
    unittest.main()
