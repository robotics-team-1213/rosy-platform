import cv2,numpy as np,pickle
from common import *
cw=pickle.load(open("cw_frames.pkl","rb"))
want={(o[0],o[1]):o[2] for o in cw}
res={}
os_=[];dbg=[]
def quad(mask):
    cs,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    cnt=max(cs,key=cv2.contourArea)
    # fit 4 lines: use approxPoly then refine by line fitting on contour segments
    peri=cv2.arcLength(cnt,True)
    for e in np.linspace(0.02,0.15,30):
        ap=cv2.approxPolyDP(cnt,e*peri,True)
        if len(ap)==4: break
    else: return None
    ap=ap.reshape(4,2).astype(float)
    pts=cnt.reshape(-1,2).astype(float)
    # assign contour pts to nearest edge, fit lines
    lines=[]
    for q in range(4):
        a=ap[q];b=ap[(q+1)%4];d=b-a;L=np.linalg.norm(d);d/=L;nrm=np.array([-d[1],d[0]])
        t=(pts-a)@d; s=(pts-a)@nrm
        sel=pts[(t>0.2*L)&(t<0.8*L)&(np.abs(s)<2.5)]
        if len(sel)<3: sel=np.array([a,b])
        vx,vy,x0,y0=cv2.fitLine(sel.astype(np.float32),cv2.DIST_L2,0,0.01,0.01).ravel()
        lines.append((np.array([x0,y0]),np.array([vx,vy])))
    cor=[]
    for q in range(4):
        (p1,d1),(p2,d2)=lines[q-1],lines[q]
        A=np.array([d1,-d2]).T
        try: tt=np.linalg.solve(A,p2-p1)
        except: return None
        cor.append(p1+tt[0]*d1)
    return np.array(cor)
for i,k,f in frames():
    if (i,k) not in want: continue
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    floor=np.median(g[200:,:])
    thr=(floor+np.percentile(g[g>floor+45],50))/2  # mid between floor and tape
    ok=True; img=[]; obj=[]
    bars=sorted(want[(i,k)],key=lambda s:s[0])
    for j,(x,y,w,h,a) in enumerate(bars):
        if x<=1 or y<=1 or x+w>=319 or y+h>=239: ok=False;break
        sub=g[max(0,y-3):y+h+3,max(0,x-3):x+w+3]
        m=(sub>thr).astype(np.uint8)
        q=quad(m)
        if q is None: ok=False;break
        q=q+[max(0,x-3),max(0,y-3)]
        # order: far-left, far-right, near-right, near-left
        q=q[np.argsort(q[:,1])]
        far=q[:2][np.argsort(q[:2,0])]; near=q[2:][np.argsort(q[2:,0])]
        X0=j*40.0;X1=X0+26
        img+= [far[0],far[1],near[1],near[0]]
        obj+= [(X0,121,0),(X1,121,0),(X1,0,0),(X0,0,0)]
    if ok:
        res[(i,k)]=(np.array(obj,np.float32),np.array(img,np.float32))
print(len(res))
pickle.dump(res,open("cw_corners.pkl","wb"))
