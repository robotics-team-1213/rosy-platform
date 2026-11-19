"""Build Fleet and foundation wheels and exercise journal aliases without checkout imports."""
import subprocess
import sys
from pathlib import Path


def test_observation_owner_and_legacy_aliases_ship_in_fleet_wheel(tmp_path):
    package = Path(__file__).resolve().parents[1]
    foundation = package.parents[1] / 'contracts' / 'foundation'
    wheels, installed = tmp_path / 'wheels', tmp_path / 'installed'
    result = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
        '--wheel-dir', str(wheels), str(package), str(foundation)], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode()
    wheel, = wheels.glob('fleet-*.whl')
    foundation_wheel, = wheels.glob('core_common-*.whl')
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', str(installed),
                             str(wheel), str(foundation_wheel)], capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode()
    script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from fleet.observe.events import CoreEventStore
from fleet.observe.store import ObservationStore
from fleet.server.core_event_store import CoreEventStore as LegacyEvents
from fleet.server.observation_store import ObservationStore as LegacyStore
from rosy_situation.wait_graph import wait_cycle
from rosy_situation.fact_rules import COMMAND_WORDS
import fleet.observe.store as owner
import core_common.audit_fields as fields
assert wait_cycle({'a': 'b', 'b': 'a'})
assert COMMAND_WORDS
assert CoreEventStore is LegacyEvents and ObservationStore is LegacyStore
assert Path(owner.__file__).is_relative_to(Path(sys.argv[1]))
assert Path(fields.__file__).is_relative_to(Path(sys.argv[1]))
assert fields.is_credential_field('access_token')
store = ObservationStore(sys.argv[2])
store.append_snapshot([dict(robot_id='synthetic', online=True, state=None)], received_at=10, monotonic_now=10)
assert store.read_observations()[0]['observation']['capture']['robot_ids'] == ['synthetic']
print('PASS_INSTALLED_OBSERVATION_ALIAS_ONLY')
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(installed), str(tmp_path / 'fleet.db')],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.strip() == b'PASS_INSTALLED_OBSERVATION_ALIAS_ONLY'
