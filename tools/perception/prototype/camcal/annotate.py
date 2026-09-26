import cv2,numpy as np,math,pickle
from getframes import get
from cammodel import Cam
S=3
cam=Cam(f=281.6,pitch_deg=8.0,roll_deg=0.9,h=0.067)
res=pickle.load(open("cw_corners.pkl","rb"))
keys,(K,d,rv,tv),rows=pickle.load(open("calib_cw.pkl","rb"))
lsd=cv2.createLineSegmentDetector(); rng=np.random.default_rng(0)
def P(p): return (int(round(p[0]*S)),int(round(p[1]*S)))
def vp_fit(g):
    s=lsd.detect(g)[0].reshape(-1,4); L=np.hypot(s[:,2]-s[:,0],s[:,3]-s[:,1])
    ang=np.degrees(np.arctan2(s[:,3]-s[:,1],s[:,2]-s[:,0]))%180; ymin=np.minimum(s[:,1],s[:,3])
    keep=(L>25)&(ymin>88)&(np.abs(ang-90)<75)&(np.abs(ang-90)>8); s=s[keep];L=L[keep]
    lines=np.cross(np.c_[s[:,:2],np.ones(len(s))],np.c_[s[:,2:],np.ones(len(s))]); lines/=np.linalg.norm(lines[:,:2],axis=1)[:,None]
    best=None
    for _ in range(400):
        a,b=rng.choice(len(s),2,replace=False); vp=np.cross(lines[a],lines[b])
        if abs(vp[2])<1e-9: continue
        vp=vp/vp[2]
        if not (-300<vp[0]<620 and -60<vp[1]<200): continue
        mid=(s[:,:2]+s[:,2:])/2; d1=vp[:2]-mid; dirs=(s[:,2:]-s[:,:2])/L[:,None]
        cr=np.abs(d1[:,0]*dirs[:,1]-d1[:,1]*dirs[:,0])/np.linalg.norm(d1,axis=1); inl=cr<math.sin(math.radians(1.0))
        if inl.sum()>=3 and (best is None or L[inl].sum()>best[0]): best=(L[inl].sum(),inl)
    inl=best[1]; A=lines[inl]; w=L[inl]
    sol=np.linalg.lstsq(A[:,:2]*w[:,None],-A[:,2]*w,rcond=None)[0]
    return s,inl,sol
def horizon(img,col=(0,0,255)):
    a,_=cam.project(np.array([[1e6,1e6*2,0],[1e6,-1e6*2,0]]))
    cv2.line(img,P(a[0]),P(a[1]),col,1,cv2.LINE_AA)
for (i,k) in [(1,200),(6,400),(1,400),(1,712)]:
    f=get(i,k); g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
    im=cv2.resize(f,None,fx=S,fy=S,interpolation=cv2.INTER_CUBIC)
    # row ticks
    for y in range(0,240,20): cv2.putText(im,str(y),(2,y*S+4),0,0.4,(0,255,255),1)
    horizon(im)
    txt=[]
    if k!=712:
        s,inl,vp=vp_fit(g)
        for sg in s[inl]:
            cv2.line(im,P(sg[:2]),P(sg[2:]),(0,255,0),2,cv2.LINE_AA)
            # extend to vp
            m=(sg[:2]+sg[2:])/2; cv2.line(im,P(m),P(vp),(0,200,0),1,cv2.LINE_AA)
        cv2.circle(im,P(vp),6,(255,0,255),2); txt.append("lane VP (%.1f, %.1f)  [%d edge segs]"%(vp[0],vp[1],inl.sum()))
    if (i,k) in res:
        o,ip=res[(i,k)]; j=keys.index((i,k))
        pr=cv2.projectPoints(o,rv[j],tv[j],K,d)[0].reshape(-1,2)
        for a,b in zip(ip,pr):
            cv2.circle(im,P(a),3,(0,255,0),-1); cv2.drawMarker(im,P(b),(0,255,255),cv2.MARKER_CROSS,8,1)
        txt.append("crosswalk corners: green=detected, yellow=reprojected (f=281.6)")
    if k==712:
        # wall top/base per column
        hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); V=hsv[:,:,2]; Sa=hsv[:,:,1]
        for u in range(10,310,3):
            col=(V[:,u]>150)&(Sa[:,u]<60)
            if not col[70:90].all(): continue
            t=70
            while t>0 and col[t-1]: t-=1
            b=90
            while b<239 and col[b+1]: b+=1
            cv2.circle(im,P((u,t)),2,(255,128,0),-1); cv2.circle(im,P((u,b)),2,(0,128,255),-1)
        txt.append("wall top (blue) / base (orange); 155 mm wall -> h ~= 67 mm here")
    txt.insert(0,"p%d frame %d | red = horizon from profile (row 80, roll 0.9 deg)"%(i,k))
    hb=18*len(txt)+6
    im=cv2.copyMakeBorder(im,0,hb,0,0,cv2.BORDER_CONSTANT,value=(0,0,0))
    for n,t in enumerate(txt): cv2.putText(im,t,(8,240*S+16+18*n),0,0.5,(255,255,255),1,cv2.LINE_AA)
    cv2.imwrite(f"out/annot_p{i}_{k:04d}.png",im)
print("ok")
