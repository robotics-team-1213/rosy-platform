import test from 'node:test';
import assert from 'node:assert/strict';
import {pointerPose, drawStartPointMarks} from '../../fleet/server/web/start-point-layer.js';
import {fitTransform, siteBounds, project} from '../../fleet/server/web/site-layer.js';

test('site-map picks use the actual drawing transform and reject track padding', () => {
  const view = {siteMap: {maps: [{map_id:'track', polygon_m:[[-1,-.5],[1,-.5],[1,.5],[-1,.5]]}]}};
  const rect = {left:10, top:20, width:800, height:400};
  const t=fitTransform(siteBounds(view.siteMap),800,400,32);
  const p=project(t,.4,-.2);
  const pose=pointerPose(view,rect,{width:1600,height:800},p.px+10,p.py+20);
  assert.ok(Math.abs(pose.x-.4)<1e-9); assert.ok(Math.abs(pose.y+.2)<1e-9);
  assert.equal(pointerPose(view,rect,{width:1600,height:800},10,20),null);
});

test('occupancy map letterboxing never creates a pose in the margin', () => {
  const view={map:{width:100,height:50,resolution:.02,origin:{x:-1,y:-.5}}};
  const rect={left:0,top:0,width:400,height:400};
  assert.equal(pointerPose(view,rect,{width:100,height:50},200,50),null);
  assert.deepEqual(pointerPose(view,rect,{width:100,height:50},200,200),{x:0,y:0});
});

test('invalid calibration or another map cannot draw a start marker', () => {
  let arcs=0;
  const ctx={save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){arcs++;}};
  const rows=[{valid:false,map_id:'track',x:0,y:0,yaw:0},{valid:true,map_id:'other',x:0,y:0,yaw:0}];
  drawStartPointMarks(ctx,(x,y)=>({x,y}),rows,['track'],'token',1);
  assert.equal(arcs,0);
});

test('D-513 7: on the live camera picture a click goes through the camera pick', () => {
  const view = {siteMap: {maps: [{map_id:'track', polygon_m:[[-1,-.5],[1,-.5],[1,.5],[-1,.5]]}]},
    cameraPick: (x, y) => ({x: x / 1000, y: -y / 1000})};
  const rect = {left: 0, top: 0, width: 360, height: 640};
  const pose = pointerPose(view, rect, {width: 720, height: 1280}, 180, 160);
  assert.deepEqual(pose, {x: 0.36, y: -0.32});
  assert.equal(pointerPose({...view, cameraPick: () => null}, rect, {width: 720, height: 1280}, 180, 160), null);
});
