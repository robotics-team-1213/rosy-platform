import math, numpy as np, cv2, sys
sys.argv=["x","1"]
import replay as R
from control.sensing.perception.lane_bev import BirdsEye
g=R.GROUND
rng=np.random.default_rng(0)
tex=cv2.GaussianBlur((rng.random((800,800))*255).astype(np.float32),(0,0),3)
tex=cv2.normalize(tex,None,0,255,cv2.NORM_MINMAX)
def render(pose):
    img=np.zeros((240,320),np.uint8)
    rows,cols=np.mgrid[0:240,0:320]
    X=np.full(rows.shape,np.nan);Y=np.full(rows.shape,np.nan)
    for r in range(240):
        d=g.distance(r)
        if d is None: continue
        for c in range(0,320):
            X[r,c]=d+R.X_OFF; Y[r,c]=-g.lateral(c,r)
    x,y,th=pose
    wx=x+X*math.cos(th)-Y*math.sin(th); wy=y+X*math.sin(th)+Y*math.cos(th)
    u=(wx/0.0025+400); v=(wy/0.0025+400)
    ok=np.isfinite(u)
    img[ok]=cv2.remap(tex,v.astype(np.float32),u.astype(np.float32),cv2.INTER_LINEAR)[ok]
    return img
vo=R.BevVO(BirdsEye(g,320,240,R.X_OFF))
wall=np.zeros((240,320),bool)
for pose in [(0,0,0),(0.02,0,0),(0.04,0.0,0.1),(0.05,0.01,0.2)]:
    p=vo.step(render(pose),wall); print("true",pose,"est",tuple(round(a,4) for a in p), vo.last_inliers)
