"""Parameter-only sensitivity: centre ladder (stand-in odometry) at lower
bright_threshold values. No repo code changed."""
import sys, json, os, cv2
part=int(sys.argv[1]); sys.argv=["x","1"]
import replay as R
from control.sensing.lane_boundaries import LaneBoundaryTracker
from control.sensing.lane_bev import BirdsEye
TH=(140,150,165)
cap=cv2.VideoCapture(R.VIDEO%part)
vo=R.BevVO(BirdsEye(R.GROUND,R.W,R.H,R.X_OFF))
tr={t:LaneBoundaryTracker(camera_x_offset_m=R.X_OFF) for t in TH}
out=open(os.path.join(os.getcwd(),"out",f"whatif_p{part:02d}.jsonl"),"w"); i=0
while True:
    ok,f=cap.read()
    if not ok: break
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY); wm,_=R.wall_mask(g)
    pose=vo.step(g,wm); rec={"frame":i}
    for t in TH:
        kw=dict(R.CENTRE_KW); kw["bright_threshold"]=t
        o=tr[t].update(i/8.0,pose,f,R.GROUND,**kw)
        rec[str(t)]=tr[t].tier
    out.write(json.dumps(rec)+"\n"); i+=1
print("done",part,i)
