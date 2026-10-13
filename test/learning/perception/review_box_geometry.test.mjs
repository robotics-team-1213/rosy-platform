import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drawnBox, dragBox, hitBox } from '../dataset/review_app_web/box-geometry.mjs';

test('draw reversed and out-of-image endpoints in original coordinates', () => {
  assert.deepEqual(drawnBox([50,40],[-10,10],320,240),[0,10,50,40]);
  assert.deepEqual(drawnBox([20,30],[500,300],320,240),[20,30,320,240]);
});
test('move keeps size and stays within the original image', () => {
  assert.deepEqual(dragBox([10,20,40,60],'move',[20,30],[500,500],320,240),[290,200,320,240]);
  assert.deepEqual(dragBox([10,20,40,60],'move',[20,30],[-20,-10],320,240),[0,0,30,40]);
});
test('corner and edge resizing cannot invert or escape the image', () => {
  assert.deepEqual(dragBox([10,20,40,60],'se',[40,60],[500,500],320,240),[10,20,320,240]);
  assert.deepEqual(dragBox([10,20,40,60],'nw',[10,20],[80,80],320,240),[38,58,40,60]);
  assert.deepEqual(dragBox([10,20,40,60],'w',[10,40],[0,40],320,240),[0,20,40,60]);
});
test('hit distinguishes selected handles, overlapping top box and background', () => {
  const boxes=[{bbox_xyxy:[10,20,40,60]},{bbox_xyxy:[20,30,50,70]}];
  assert.deepEqual(hitBox(boxes,[25,35],2,null),{index:1,mode:'move'});
  assert.deepEqual(hitBox(boxes,[10,20],3,0),{index:0,mode:'nw'});
  assert.equal(hitBox(boxes,[100,100],3,0),null);
});
