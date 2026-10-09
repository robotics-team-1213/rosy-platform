import test from 'node:test';
import assert from 'node:assert/strict';
import {drawStartPointMarks, picturePose} from '../../fleet/server/web/start-point-layer.js';

test('invalid calibration or another map cannot draw a start marker', () => {
  let arcs=0;
  const ctx={save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){arcs++;}};
  const rows=[{valid:false,map_id:'track',x:0,y:0,yaw:0},{valid:true,map_id:'other',x:0,y:0,yaw:0}];
  drawStartPointMarks(ctx,(x,y)=>({x,y}),rows,['track'],'token',1);
  assert.equal(arcs,0);
});

// topDownLayout(6.4×3.6 m, 640, 400, 0.1): 640/6.6 px per m, x0=-0.1, y1=3.7.
const K=640/6.6, toMap=[1/K,0,-0.1, 0,-1/K,3.7, 0,0,1];
const bounds={min_x:0,min_y:0,max_x:6.4,max_y:3.6}, size={width:640,height:368};

test('D-540 5: a picture pick inside the track gives the map pose', () => {
  const rect={left:10,top:20,width:640,height:368};
  const pose=picturePose(rect,size,toMap,bounds,10+320,20+184);
  assert.ok(Math.abs(pose.x-3.2)<1e-9 && Math.abs(pose.y-1.8)<.01);
});

test('the layout margin (track padding) never creates a pose', () => {
  const rect={left:0,top:0,width:640,height:368};
  assert.equal(picturePose(rect,size,toMap,bounds,3,184),null);    // x = -0.07 m
  assert.equal(picturePose(rect,size,toMap,bounds,320,366),null);  // y = -0.07 m
});

test('the contain letterbox never creates a pose in the margin', () => {
  const rect={left:0,top:0,width:640,height:800};  // picture drawn 640×368, centred vertically
  assert.equal(picturePose(rect,size,toMap,bounds,320,100),null);
  assert.ok(picturePose(rect,size,toMap,bounds,320,400));
});

test('no transform, an empty canvas or a degenerate projection gives no pose', () => {
  const rect={left:0,top:0,width:640,height:368};
  assert.equal(picturePose(rect,size,null,bounds,320,184),null);
  assert.equal(picturePose(rect,{width:0,height:0},toMap,bounds,320,184),null);
  assert.equal(picturePose(rect,size,[1,0,0, 0,1,0, 0,0,0],bounds,320,184),null);
});
