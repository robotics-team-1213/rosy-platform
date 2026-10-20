"""Model inputs join native immutable dependency checks, never writable evidence."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/robot/omx'))
from native_sim_inputs import load_config, dependency_inventory, verify_bindings, inventory
from native_sim_prepare import environment
from test_native_sim_job import prepared


def host_config(tmp_path):
    for name in ('ros','overlay','base','act','science','policy'):
        (tmp_path/name).mkdir()
    (tmp_path/'ros/setup.bash').touch()
    (tmp_path/'overlay/setup.bash').touch()
    (tmp_path/'policy/policy-artifact.json').write_text('{}')
    (tmp_path/'policy/campaign.json').write_text('{}')
    config=dict(schema='rosy.omx-native-sim-host/1',role='ai',
        ros_setup=str(tmp_path/'ros/setup.bash'),overlay=str(tmp_path/'overlay'),
        python_site=str(tmp_path/'base'),policy_input=str(tmp_path/'policy'),
        inference_python_sites=[str(tmp_path/'science'),str(tmp_path/'act')])
    return config


def test_explicit_model_input_is_readonly_dependency_and_science_precedes_act(tmp_path):
    config=host_config(tmp_path)
    path=tmp_path/'host.json';path.write_text(json.dumps(config))
    checked=load_config(path)
    shell=environment(checked)
    assert 'export OMX_SIM_POLICY_INPUT='+str((tmp_path/'policy').resolve()) in shell
    assert str((tmp_path/'science').resolve())+':'+str((tmp_path/'act').resolve())+':' in shell


@pytest.mark.parametrize('fault',['missing_sites','missing_policy','empty_sites','missing_manifest',
                                 'unhashable_sites','duplicate_sites'])
def test_incomplete_inference_inputs_are_refused(tmp_path,fault):
    config=host_config(tmp_path)
    if fault=='missing_sites':config.pop('inference_python_sites')
    elif fault=='missing_policy':config.pop('policy_input')
    elif fault=='empty_sites':config['inference_python_sites']=[]
    elif fault=='unhashable_sites':config['inference_python_sites']=[{},[]]
    elif fault=='duplicate_sites':config['inference_python_sites']=[config['python_site']]*2
    else:(tmp_path/'policy/policy-artifact.json').unlink()
    path=tmp_path/'host.json';path.write_text(json.dumps(config))
    with pytest.raises(ValueError):load_config(path)


def test_changed_checkpoint_in_dependency_root_cannot_start(tmp_path):
    staged=prepared(tmp_path)
    policy=tmp_path/'policy';policy.mkdir()
    weights=policy/'model.safetensors';weights.write_bytes(b'original')
    document=json.loads((staged/'prepared.json').read_text())
    document['dependency_roots'].append(str(policy))
    document['dependency_hashes']=dependency_inventory(document['dependency_roots'])
    verify_bindings(document,staged/'source',staged/'state')
    weights.write_bytes(b'changed')
    with pytest.raises(ValueError,match='dependency input drift'):
        verify_bindings(document,staged/'source',staged/'state')
