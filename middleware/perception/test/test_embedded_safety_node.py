"""Embedded sensor worker identity is independent of CORE's process name remap."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT/'middleware/control/drive/safety/adapter/node.py'


@pytest.mark.parametrize('sensor_only,namespace,embedded', [
    (True, '/owned', True), (True, None, False), (False, '/owned', False), (False, None, False)])
def test_constructor_retains_only_the_embedded_explicit_context(sensor_only, namespace, embedded):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='SafetyNode')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='__init__')
    end = next(i for i,n in enumerate(method.body) if isinstance(n,ast.Expr)
               and ast.unparse(n.value).startswith('super().__init__'))
    method.body = method.body[:end+1]
    cls.bases = [ast.Name(id='Base',ctx=ast.Load())]
    cls.body = [method]
    captured = []
    class Base:
        def __init__(self, *args, **kwargs):
            captured.append((args,kwargs))
    env = dict(Base=Base)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(SOURCE),'exec'),env)
    overrides = [object()]
    env['SafetyNode'](sensor_only=sensor_only,namespace=namespace,parameter_overrides=overrides)
    args,kwargs = captured[0]
    assert args == ('safety_node',)
    assert kwargs.get('use_global_arguments',True) is True
    assert kwargs.get('cli_args') == (['--ros-args','-r','__node:=safety_node'] if embedded else None)
    assert kwargs['parameter_overrides'] is overrides
    assert kwargs.get('namespace') == namespace


@pytest.mark.parametrize('clock',[False,True])
def test_real_ros_embedded_worker_ignores_core_name_but_keeps_namespace_params_and_clock(tmp_path, clock):
    setup = Path('/opt/ros/jazzy/setup.bash')
    if not setup.exists():
        pytest.skip('Requires installed ROS Jazzy')
    params = tmp_path/'global.yaml'
    params.write_text('/**:\n  ros__parameters:\n    filt_median: 7\n    safety_max_linear: 0.333\n/camera_law_46e142_test/core:\n  ros__parameters:\n    use_sim_time: true\n')
    script = tmp_path/'native.py'
    script.write_text('''import sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'middleware/perception'),str(root/'contracts/foundation')]
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from control.sensor_provider import make_node
rclpy.init(args=['--ros-args','-r','__node:=core','-r','__ns:=/camera_law_46e142_test','-r','scan:=scan_remapped','-r','imu_raw:=imu_remapped','-r','ir_sensor/range:=adc_remapped','--params-file',sys.argv[2]],domain_id=99)
core=Node('core',parameter_overrides=[Parameter('use_sim_time',value=sys.argv[3]=='True')]);worker=None
try:
 worker=make_node(sensor_only=True,namespace=core.get_namespace(),parameter_overrides=dict(use_sim_time=core.get_parameter('use_sim_time').value,safety_max_linear=.2,safety_max_angular=.8))
 assert core.get_fully_qualified_name()=='/camera_law_46e142_test/core'
 assert worker.get_fully_qualified_name()=='/camera_law_46e142_test/safety_node'
 assert worker.get_namespace()==core.get_namespace()
 assert worker.get_parameter('use_sim_time').value is (sys.argv[3]=='True')
 assert worker.get_parameter('safety_max_linear').value==.2
 assert worker.get_parameter('filt_median').value==7
 for source,target in [('scan','scan_remapped'),('imu_raw','imu_remapped'),('ir_sensor/range','adc_remapped')]:
  assert worker.resolve_topic_name(source)=='/camera_law_46e142_test/'+target
 assert worker.pub is None and worker.raw_zero_pub is None
 assert worker.count_publishers('/camera_law_46e142_test/cmd_vel')==0
 print('distinct node identity, explicit namespace/parameters/clock, no worker command publisher')
finally:
 if worker is not None:worker.destroy_node()
 core.destroy_node();rclpy.shutdown()
''')
    import os
    env = dict(os.environ, ROS_LOCALHOST_ONLY='1')
    result = subprocess.run(['bash','-c','source /opt/ros/jazzy/setup.bash && exec /usr/bin/python3 "$@"',
        'native-check',str(script),str(ROOT),str(params),str(clock)],env=env,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
    assert result.returncode==0,result.stdout
    assert 'distinct node identity' in result.stdout
