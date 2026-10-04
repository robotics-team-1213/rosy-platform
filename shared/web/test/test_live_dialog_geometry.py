"""Overlapping live controls must form one scrim opening, including viewport edges."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_live_control_union_keeps_intersections_open_without_exposing_other_area():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the browser-independent geometry check')
    asset = Path(__file__).resolve().parents[1] / 'live-dialog-geometry.js'
    result = subprocess.run([node, '--input-type=module', '-e', f"""
      import assert from 'node:assert/strict';
      import {{disjointRectangles}} from '{asset.as_uri()}';
      const rectangles=[{{left:0,top:0,right:10,bottom:10}},{{left:5,top:5,right:15,bottom:15}},{{left:2,top:2,right:8,bottom:8}}];
      const pieces=disjointRectangles([...rectangles,rectangles[1]],20,20);
      const covers=(r,x,y)=>x>=r.left&&x<r.right&&y>=r.top&&y<r.bottom;
      assert.equal(pieces.reduce((sum,r)=>sum+(r.right-r.left)*(r.bottom-r.top),0),175);
      for(let x=.25;x<20;x++) for(let y=.25;y<20;y++) assert.equal(pieces.filter(r=>covers(r,x,y)).length,rectangles.some(r=>covers(r,x,y))?1:0);
      const clipped=disjointRectangles([{{left:-10,top:-10,right:3,bottom:3}},{{left:NaN,top:0,right:5,bottom:5}},{{left:0,top:0,right:Infinity,bottom:5}},{{left:5,top:5,right:5,bottom:6}}],10,10);
      assert.deepEqual(clipped,[{{left:0,top:0,right:3,bottom:3}}]);
      const stop={{left:12,top:762.21875,right:378,bottom:832}};
      const off={{left:14,top:799.890625,right:135,bottom:843.890625}};
      assert.equal(disjointRectangles([stop,off],390,844).filter(r=>covers(r,74.5,821.9)).length,1);
    """], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
