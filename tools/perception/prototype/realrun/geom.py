import os, sys, math, numpy as np
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..","..","..","src","core","control"))
from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_bev import BirdsEye, BEV_CELL_M
for name,(w,h,ch,p,hf,xo) in {"real":(320,240,0.067,0.1396,2*math.atan(160/281.6),0.034),
                          "sim":(320,180,0.060194,math.radians(25),1.1519,0.034)}.items():
    g=simulation_ground_plane(source="GAZEBO",simulation_enabled=True,use_sim_time=True,width_px=w,height_px=h,height_m=ch,pitch_rad=p,hfov_rad=hf,max_range_m=0.6)
    v=BirdsEye(g,w,h,xo); o=v.observable
    rows=v._pixel_row[o]; 
    xs=v.x[o]
    # lateral reach at a given forward x: max |y| observable
    def reach(x):
        sel=o & (np.abs(v.x-x)<BEV_CELL_M)
        return v.y[sel].max() if sel.any() else None
    print(name,"horizon",round(g.horizon_row,1),"img rows used",rows.min(),"-",rows.max(),"of",h,
      "| fwd from base_link",round(xs.min(),3),"-",round(xs.max(),3),"| cells",int(o.sum()),
      "| +-y reach at x=.15/.2/.25/.3/.4:",[None if reach(x) is None else round(reach(x),3) for x in (.15,.2,.25,.3,.4)],
      "| px rows per 1cm at 0.3m", round(abs(g.distance(0) or 0),2))
    for d in (0.10,0.2,0.3,0.4):
        ang=math.atan2(ch,d)-p; print("   cam range",d,"-> row",round(g.principal_y+g.focal_px*math.tan(ang),1))
