import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = new URL('../../../../applications/fleet/web/devices/device-profiles.js', import.meta.url);
const gate = new URL('../../../../applications/fleet/web/shared/poll-gate.js', import.meta.url);
const code = (await readFile(source, 'utf8')).replace('/console/assets/poll-gate.js', gate.href);
const {profilePayload, createDeviceProfiles} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('profiles preserve declared model and composition independently of USB identities', () => {
  const payload = profilePayload({device_id:'omx-s',display_name:'OMX S',manufacturer:'ROBOTIS',
    model:'OMX S',device_kind:'manipulator',arm_count:'1',hardware_ids:'bus-a\nbus-b\n'});
  assert.equal(payload.arm_count, 1);
  assert.deepEqual(payload.hardware_ids, ['bus-a','bus-b']);
  assert.equal(profilePayload({...payload,arm_count:'',hardware_ids:''}).arm_count, null);
  assert.throws(() => profilePayload({...payload,hardware_ids:'bus-a\nbus-a'}), /중복/);
  for (const arm_count of ['1.5','17','-1','abc']) {
    assert.throws(() => profilePayload({...payload,arm_count,hardware_ids:''}), /팔 수/);
  }
});

function fixture(role='operator') {
  const fields = ['device_id','display_name','manufacturer','model','device_kind','arm_count','hardware_ids'];
  const nodes = Object.fromEntries([...fields,'list','save','new','refresh','status','permission','saved'].map(key => [key,{
    value:'',textContent:'',disabled:false,hidden:false,handlers:{},
    addEventListener(type,fn){this.handlers[type]=fn;},setAttribute(){},removeAttribute(){},
    replaceChildren(...children){this.children=children;},focus(){},
  }]));
  nodes.device_kind.value='manipulator';
  const root={querySelector:selector=>nodes[selector.match(/data-profile="([^"]+)"/)[1]],
    ownerDocument:{createElement:()=>({value:'',textContent:''})}};
  let rows=[],pendingSave=null;
  const calls=[];
  const scope={listen(node,type,fn){node.addEventListener(type,fn);},onDispose(){}};
  const call=async(path,options={})=>{calls.push([path,options]);
    if(options.method==='PUT') return await pendingSave;
    return path==='/api/fleet/device-profiles'?{profiles:rows}:rows.find(row=>path.endsWith(row.device_id));};
  const panel=createDeviceProfiles({root,scope,call,identity:()=>({role,principal_id:'alice'})});
  return {nodes,panel,calls,setRows(value){rows=value;},setSave(value){pendingSave=value;}};
}

test('refresh preserves a dirty draft and viewers cannot submit', async () => {
  const f=fixture();
  f.nodes.display_name.value='OMX S draft';f.nodes.display_name.handlers.input();
  f.setRows([{device_id:'other',display_name:'OMX AI'}]);
  await f.panel.refresh();
  assert.equal(f.nodes.display_name.value,'OMX S draft');
  const viewer=fixture('viewer');viewer.panel.updateAuthorization();
  assert.equal(viewer.nodes.save.disabled,true);
  await viewer.nodes.save.handlers.click();
  assert.equal(viewer.calls.length,0);
});

test('save prevents duplicate submission and verifies saved metadata without connection claims', async () => {
  const f=fixture();let finish;
  f.setSave(new Promise(resolve=>{finish=resolve;}));
  Object.assign(f.nodes.device_id,{value:'omx-s'});f.nodes.display_name.value='OMX S';
  f.nodes.model.value='OMX S';f.nodes.manufacturer.value='ROBOTIS';f.nodes.arm_count.value='1';
  const saved={device_id:'omx-s',display_name:'OMX S',model:'OMX S',manufacturer:'ROBOTIS',
    device_kind:'manipulator',arm_count:1,hardware_ids:[],connection_status:'not_checked',control_enabled:false};
  f.setRows([saved]);
  const first=f.nodes.save.handlers.click();await f.nodes.save.handlers.click();
  assert.equal(f.calls.filter(([,opts])=>opts.method==='PUT').length,1);
  finish(saved);await first;
  assert.match(f.nodes.status.textContent,/저장/);
  assert.match(f.nodes.saved.textContent,/연결 미확인/);
  assert.equal(f.nodes.save.disabled,false);
});
