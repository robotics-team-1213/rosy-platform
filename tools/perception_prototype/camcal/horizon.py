import cv2,numpy as np,pickle,math
from common import *
F=281.6; ROLL=math.radians(0.91)
lsd=cv2.createLineSegmentDetector()
rng=np.random.default_rng(0)
rec=[]
for i,k,f in frames():
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
    segs=lsd.detect(g)[0]
    if segs is None: rec.append((i,k,None));continue
    s=segs.reshape(-1,4)
    L=np.hypot(s[:,2]-s[:,0],s[:,3]-s[:,1])
    ang=np.degrees(np.arctan2(s[:,3]-s[:,1],s[:,2]-s[:,0]))%180
    ymin=np.minimum(s[:,1],s[:,3])
    # floor segments: long, not near-horizontal, not near-vertical, fully below row 90
    keep=(L>25)&(ymin>88)&(np.abs(ang-90)<75)&(np.abs(ang-90)>8)
    s=s[keep];L=L[keep]
    # also require brightness contrast: tape edges -> check one side bright
    if len(s)<3: rec.append((i,k,None));continue
    lines=np.cross(np.c_[s[:,:2],np.ones(len(s))],np.c_[s[:,2:],np.ones(len(s))])
    lines/=np.linalg.norm(lines[:,:2],axis=1)[:,None]
    best=None
    for _ in range(200):
        a,b=rng.choice(len(s),2,replace=False)
        vp=np.cross(lines[a],lines[b])
        if abs(vp[2])<1e-9: continue
        vp=vp/vp[2]
        if not (-300<vp[0]<620 and -60<vp[1]<200): continue
        # distance of vp to each line, angular consistency
        mid=(s[:,:2]+s[:,2:])/2
        d1=vp[:2]-mid; dirs=(s[:,2:]-s[:,:2])/L[:,None]
        cross=np.abs(d1[:,0]*dirs[:,1]-d1[:,1]*dirs[:,0])/np.linalg.norm(d1,axis=1)
        inl=cross<math.sin(math.radians(1.0))
        # distinct angles
        if inl.sum()>=3:
            angs=ang[keep][inl] if False else None
            sc=L[inl].sum()
            if best is None or sc>best[0]: best=(sc,inl,vp)
    if best is None: rec.append((i,k,None));continue
    sc,inl,vp=best
    # refine LSQ
    A=lines[inl]; w=L[inl]
    M=(A[:,:2]*w[:,None]); bb=-A[:,2]*w
    sol=np.linalg.lstsq(M,bb,rcond=None)[0]
    # need angular spread among inliers
    a_in=np.degrees(np.arctan2(s[inl,3]-s[inl,1],s[inl,2]-s[inl,0]))%180
    spread=a_in.max()-a_in.min()
    rec.append((i,k,(sol[0],sol[1],int(inl.sum()),float(sc),float(spread))))
pickle.dump(rec,open("vp_rec.pkl","wb"))
good=[r for r in rec if r[2] and r[2][4]>20 and r[2][2]>=3 and r[2][3]>150]
print(len(rec),len(good))
