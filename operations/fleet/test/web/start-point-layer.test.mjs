import test from 'node:test';
import assert from 'node:assert/strict';
import {drawStartPointMarks} from '../../fleet/server/web/start-point-layer.js';

test('invalid calibration or another map cannot draw a start marker', () => {
  let arcs=0;
  const ctx={save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){arcs++;}};
  const rows=[{valid:false,map_id:'track',x:0,y:0,yaw:0},{valid:true,map_id:'other',x:0,y:0,yaw:0}];
  drawStartPointMarks(ctx,(x,y)=>({x,y}),rows,['track'],'token',1);
  assert.equal(arcs,0);
});
