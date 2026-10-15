import hashlib,json,math,os,signal,socket,subprocess,time,urllib.request,secrets
from pathlib import Path
import yaml
import sys
root=Path('/home/ai/rosy-test/d763-sim');source=root/'source'
out=root/'artifacts'/sys.argv[1];out.mkdir(exist_ok=False)
receipt=dict(source_revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip())
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip(),'dirty source'
(out/'source-receipt.json').write_text(json.dumps(receipt))
for port in (31351,31352,31353):
 with socket.socket() as check: check.bind(('127.0.0.1',port))
pointer=out/'model-pointer.txt';pointer.write_text('/home/ai/rosy-test/gazebo-core-126256-a6/model-v1\n')
manifest=[]
fleet_rest_tokens={};resolver_tokens={}
profile_source=source/'middleware/devices/pinky/profile/config/profile.yaml'
profile_doc=yaml.safe_load(profile_source.read_text());assert profile_doc['profile']['max_linear_velocity']==.2
profile_doc['profile']['max_linear_velocity']=.1
commission_profile=out/'commissioned-profile.yaml';commission_profile.write_text(yaml.safe_dump(profile_doc))
(out/'commission-profile-binding.json').write_text(json.dumps(dict(original_profile=str(profile_source),original_sha256=hashlib.sha256(profile_source.read_bytes()).hexdigest(),copied_profile=str(commission_profile),copied_sha256=hashlib.sha256(commission_profile.read_bytes()).hexdigest(),changed_fields={'profile.max_linear_velocity':.1,'CORE safety.manual_linear':.1,'CORE safety.fleet_linear':.1},scope='Owned virtual runtime commission; original geometry/angular/source/model unchanged; absolute robot.profile is the actual CORE loader path; ROSY_PROFILE env is not used'),indent=2))
for i,ns in enumerate(('rosy_01','rosy_02')):
 config=yaml.safe_load((source/'integrations/simulation/gazebo/config/map_v2_fleet_core.yaml').read_text())
 handover=out/f'handover_{ns}';handover.mkdir()
 config['hardware_probe']=dict(face_inputs_path=str(handover/'face-inputs.json'),status_inputs_path=str(handover/'status-inputs.json'))
 config['network']=dict(api_host='127.0.0.1',api_port=31351+i)
 config['robot']=dict(id=ns,name='Virtual lane lap '+ns,profile=str(commission_profile),capabilities=str(source/'middleware/devices/pinky/profile/config/capabilities.yaml'))
 config['traffic_policy']['scene_revision']='road-scene-v1'
 config.setdefault('safety',{}).update(manual_linear=.1,fleet_linear=.1)
 config['line_follow']=dict(bend_map_entry_enabled=True,turn_map_entry_enabled=True,authority_required=True,route_context_enabled=True,obstacle_mode='path',ir_guard_enabled=True,site_floor_map_id='map_v2_fleet',junction_signal_enabled=True)
 config['control']=dict(sensor_adapter=dict(mode='enforce',simulation_sensors=True))
 fleet_rest_tokens[ns]=secrets.token_urlsafe(32);resolver_tokens[ns]=secrets.token_urlsafe(32)
 config['auth']=dict(tokens=[dict(token=fleet_rest_tokens[ns],role='operator',label='owned simulation Fleet r5'),dict(token=resolver_tokens[ns],role='stuck_resolver',label='owned simulation Fleet stuck resolver'),dict(token='rosy-dev-operator',role='operator',label='existing localhost simulation operator'),dict(token='rosy-dev-viewer',role='viewer',label='existing localhost simulation viewer')])
 (out/f'core_{ns}.yaml').write_text(yaml.safe_dump(config))
 manifest.append(dict(robot_id=ns,base_url=f'http://127.0.0.1:{31351+i}',token=fleet_rest_tokens[ns],resolver_token=resolver_tokens[ns]))
fleet_manifest=out/'robots.yaml';fleet_manifest.write_text(yaml.safe_dump(dict(robots=manifest)));fleet_manifest.chmod(0o600)
spec=dict(run_id='d763-sim',core_config_dir=str(out),fleet_manifest=str(fleet_manifest),hub_url='http://127.0.0.1:31353',gz_partition='d763-sim',ros_domain_id=87,robots=[dict(namespace=ns,api_port=31351+i) for i,ns in enumerate(('rosy_01','rosy_02'))])
specfile=out/'run_spec.yaml';specfile.write_text(yaml.safe_dump(spec))
# Immutable native simulator/world/map binding; the bootstrap independently checks it.
def digest(rel): return hashlib.sha256((source/rel).read_bytes()).hexdigest()
binding=dict(run_id=spec['run_id'],epoch=1,world='map_v2_fleet',map_id='map_v2_fleet',map_revision=1,source_revision=receipt['source_revision'],world_sha256=digest('middleware/perception/map/map_v2_fleet/worlds/map_v2_fleet_real.world'),graph_sha256=digest('middleware/perception/map/map_v2_fleet/lane_graph.yaml'),urdf_sha256=digest('middleware/devices/pinky/description/urdf/rosy_gz.urdf.xacro'),domain_id=spec['ros_domain_id'],partition=spec['gz_partition'],map_from_world=[0.,0.,0.],robots=[dict(robot_id=ns,model=ns,frame_id=ns+'/odom') for ns in ('rosy_01','rosy_02')])
(out/'native-pose-binding.json').write_text(json.dumps(binding,indent=2))
(out/'map-selection.json').write_text(json.dumps(dict(map_variant='.',world_rel='middleware/perception/map/map_v2_fleet/worlds/map_v2_fleet_real.world',graph_rel='middleware/perception/map/map_v2_fleet/lane_graph.yaml',scorer_profile='original_real',source_revision=receipt['source_revision']),indent=2))

env=os.environ.copy();env.update(ROS_DOMAIN_ID='87',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',GZ_PARTITION=spec['gz_partition'],GZ_IP='127.0.0.1',ROSY_DEV_AUTH='1',RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',CYCLONEDDS_URI='file://'+str(source/'middleware/devices/pinky/bringup/config/cyclonedds_localhost.xml'),ROS_LOG_DIR=str(out/'roslogs'),LIBGL_ALWAYS_SOFTWARE='1',MESA_LOADER_DRIVER_OVERRIDE='llvmpipe')
graph=yaml.safe_load((source/'middleware/perception/map/map_v2_fleet/lane_graph.yaml').read_text())
last=graph['segments']['west']['points'][-13];previous=graph['segments']['west']['points'][-16]  # 12 cm into the lane, off the NW junction
heading=math.atan2(previous[1]-last[1],previous[0]-last[0])
spawn_poses=f'0.9,0.0,0.0;{last[0]},{last[1]},{heading}'
map_root=out/'map_v2_fleet';map_root.mkdir()
(map_root/'lane_graph.yaml').write_bytes((source/'middleware/perception/map/map_v2_fleet/lane_graph.yaml').read_bytes())
paths=['operations/fleet','contracts/foundation','contracts/learning/src','contracts/motion/src','contracts/skill/src','operations/world/src','operations/execution/src','operations/decision/src']
boot='import sys;'+''.join(f'sys.path.insert(0,{str(source/p)!r});' for p in reversed(paths))+'from fleet.cli import main;main(sys.argv[1:])'
fleet_env=env.copy();fleet_env['FLEET_SMOKE_TOKEN']='rosy-dev-operator'
named_token=secrets.token_urlsafe(32)
users=out/'site-users.yaml';users.write_text(yaml.safe_dump(dict(users=[dict(principal_id='d763-sim-operator',role='operator',token_sha256=hashlib.sha256(named_token.encode()).hexdigest())])));users.chmod(0o600)

site=yaml.safe_load((source/'integrations/simulation/gazebo/config/fleet_sim_camera_site.yaml').read_text())
site['fleet']['traffic']['authority']=True
site['fleet']['traffic']['signals']={'sig_ring':dict(zone='roundabout',phases=[dict(approach='west:fwd',green_s=4.),dict(approach='east:rev',green_s=4.)],yellow_s=1.,all_red_s=1.)}
site['fleet']['trip_lease_required']=True
site['fleet']['trip_lease_ttl_s']=8.0  # D-760 1: must exceed the 5 s line authority ttl
site_path=out/'fleet-site.yaml';site_path.write_text(yaml.safe_dump(site))
(out/'authority-pair.json').write_text(json.dumps(dict(source_revision=receipt['source_revision'],scope='Owned virtual D676 multi-runner overlay; shared defaults unchanged',core_authority_required=True,fleet_traffic_authority=True,trip_lease_required=True,site_config_sha256=hashlib.sha256(site_path.read_bytes()).hexdigest()),indent=2))
probe_env=env.copy();probe_env['MAP_DRIVE_FLEET_TOKEN']=named_token;probe_env['MAP_DRIVE_SOURCE']=str(source);probe_env['D763_OUT']=str(out)
fleet_env_extra=dict(D763_OUT=str(out),D763_HARNESS_TOKEN=named_token)
(out/'named-token.txt').write_text(named_token);(out/'named-token.txt').chmod(0o600)
fleet_env.update(fleet_env_extra)
fleet_cmd=[str(root/'fleet-venv/bin/python'),str(root/'bootstrap-s7.py'),'console','--mission-api','--robots',str(fleet_manifest),'--host','127.0.0.1','--port','31353','--token-env','FLEET_SMOKE_TOKEN','--tasks-db',str(out/'tasks.sqlite'),'--site-map-import',str(map_root/'lane_graph.yaml'),'--site-config',str(site_path),'--users-file',str(users)]
cmd=['ros2','launch','gz_sim','map_v2_fleet_multi_real.launch.py','run_spec:='+str(specfile),'learned_lane_pointer:='+str(pointer), 'spawn_poses:='+spawn_poses,'map_variant:=.']
(out/'launch-receipt.json').write_text(json.dumps(dict(source_revision=receipt['source_revision'],command=cmd,acceptance='Two native COREs enforce floor; existing local Fleet bounded trip on CORE02; CORE01 OFF; current committed IR helper and typed RouteContext opt-in'),indent=2))
asset_root=source/'middleware/perception/map/map_v2_fleet'
assets={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest() for f in asset_root.rglob('*') if f.is_file()}
model_root=Path('/home/ai/rosy-test/gazebo-core-126256-a6/model-v1')
models={str(f.relative_to(model_root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in model_root.rglob('*') if f.is_file()}
(out/'map-model-lineage.json').write_text(json.dumps(dict(source_revision=receipt['source_revision'],map_id='map_v2_fleet',source_map_lineage='260919 MAP FILE.STL',map_asset_hashes=assets,learned_model_pointer=str(model_root),learned_model_hashes=models),indent=2))
with (out/'launch.log').open('w') as log:
 process=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 fleet_process=None
 extra_processes=[]
 try:
  helper=source/'integrations/simulation/gazebo/scripts/sim_ir_floor.py'
  (out/'instrumentation-manifest.json').write_text(json.dumps(dict(source_revision=receipt['source_revision'],ir_helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),scope='Whole committed C66 source snapshot; reused Leg12 fresh17 install, not a new build',route_context_enabled=True,selected_core='rosy_02'),indent=2))
  for ns in ('rosy_01','rosy_02'):
   rows=[dict(ros_topic_name=f'/{ns}/ir_sim/{channel}',gz_topic_name=f'/{ns}/ir/{channel}',ros_type_name='sensor_msgs/msg/LaserScan',gz_type_name='gz.msgs.LaserScan',direction='GZ_TO_ROS') for channel in ('left','mid','right')]
   bridge=out/f'floor-rays-{ns}.yaml';bridge.write_text(yaml.safe_dump(rows))
   commands=[['ros2','run','ros_gz_bridge','parameter_bridge','--ros-args','-r',f'__ns:=/{ns}','-r','__node:=floor_ray_bridge','-p','config_file:='+str(bridge)],[str(root/'venv/bin/python'),str(helper),'--ros-args','-r',f'__ns:=/{ns}','-p','use_sim_time:=true']]
   if ns=='rosy_02':commands.append([str(root/'venv/bin/python'),str(root/'sim-lane-guide.py'),str(source/'middleware/perception/map/map_v2_fleet/lane_graph.yaml'),'west:rev,ring_s:fwd,ring_e:fwd,ring_n:fwd,west:rev','--ros-args','-r',f'__ns:=/{ns}','-p','use_sim_time:=true'])
   for command in commands:extra_processes.append(subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
  (out/'floor-launch.json').write_text(json.dumps(dict(scope='Actual Gazebo three IR rays converted by existing helper; no reflectance or IR lane calibration claim',source_revision=receipt['source_revision'],core_sensor_adapter=dict(mode='enforce',simulation_sensors=True),namespaces=['rosy_01','rosy_02']),indent=2))
  # Read-only startup readiness before constructing a fail-closed bound pose port.
  # No port is replaced or revived after initialization.
  deadline=time.monotonic()+30.;startup={}
  while time.monotonic()<deadline:
   for i,ns in enumerate(('rosy_01','rosy_02')):
    try:
     req=urllib.request.Request(f'http://127.0.0.1:{31351+i}/api/v1/robot/state',headers={'Authorization':'Bearer '+fleet_rest_tokens[ns]})
     with urllib.request.urlopen(req,timeout=.5) as response: state=json.load(response)
     pose=state.get('odom_pose') or {}
     if state.get('robot_id')==ns and all(isinstance(pose.get(k),(int,float)) and math.isfinite(pose[k]) for k in ('x','y','yaw','stamp')) and 0<=time.time()-pose['stamp']<=.5:startup[ns]=state
    except Exception:pass
   if len(startup)==2:break
   time.sleep(.05)
  (out/'core-startup-readiness.json').write_text(json.dumps(startup,indent=2))
  assert len(startup)==2,'Actual CORE snapshots not ready; no Fleet pose provider created'
  fleet_process=subprocess.Popen(fleet_cmd,env=fleet_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  (out/'fleet-up.flag').write_text('1')
  result=subprocess.run([str(root/'venv/bin/python'),str(root/'probe-s7.py')],env=probe_env,timeout=int(os.environ.get('D763_PROBE_S','1500')))
  replies={}
  for name,path in [('state','state'),('map','site-map/active'),('traffic','traffic')]:
   req=urllib.request.Request('http://127.0.0.1:31353/api/fleet/'+path,headers={'Authorization':'Bearer '+named_token})
   with urllib.request.urlopen(req,timeout=5) as response:replies[name]=json.load(response)
  (out/'fleet-readback.json').write_text(json.dumps(replies,indent=2))
  assert fleet_process.poll() is None,'Fleet exited before readback'
  assert process.poll() is None,'launch exited before probe'
  (out/'probe-exit.json').write_text(json.dumps(dict(returncode=result.returncode)))
 finally:
  for child in extra_processes:
   if child.poll() is None:
    os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=3)
  if fleet_process is not None and fleet_process.poll() is None:
   os.killpg(fleet_process.pid,signal.SIGTERM)
   try:fleet_process.wait(timeout=8)
   except subprocess.TimeoutExpired:os.killpg(fleet_process.pid,signal.SIGKILL);fleet_process.wait(timeout=5)
  if process.poll() is None:
   os.killpg(process.pid,signal.SIGTERM)
   try: process.wait(timeout=10)
   except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
  (out/'launcher-exit.json').write_text(json.dumps(dict(pid=process.pid,returncode=process.returncode)))
  def owned():
   result=[]
   for folder in Path('/proc').iterdir():
    if not folder.name.isdigit(): continue
    try: variables=(folder/'environ').read_bytes().split(b'\0')
    except (PermissionError,FileNotFoundError,ProcessLookupError): continue
    if ('GZ_PARTITION='+spec['gz_partition']).encode() in variables: result.append(int(folder.name))
   return result
  remaining=owned()
  for pid in remaining:
   try: os.kill(pid,signal.SIGTERM)
   except ProcessLookupError: pass
  until=time.monotonic()+5
  while owned() and time.monotonic()<until: time.sleep(.2)
  for pid in owned():
   try: os.kill(pid,signal.SIGKILL)
   except ProcessLookupError: pass
  time.sleep(.2)
  left=owned()
  (out/'cleanup.json').write_text(json.dumps(dict(partition=spec['gz_partition'],residual_before=remaining,residual_after=left)))
  assert not left,'owned simulation processes remain'
