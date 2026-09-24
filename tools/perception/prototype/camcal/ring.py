import cv2,numpy as np,math,pickle
from common import frames
from cammodel import Cam
VH=80.3
found=[]
for i,k,f in frames():
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY); hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    fl=np.median(g[200:]); m=((g>fl+45)&(hsv[:,:,1]<70)).astype(np.uint8); m[:86]=0
    cs,hier=cv2.findContours(m,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
    if hier is None: continue
    for j,c in enumerate(cs):
        if hier[0][j][3]!=-1: continue
        x,y,w,h=cv2.boundingRect(c)
        if w<100 or x<=1 or x+w>=319 or y+h>=238 or y<88: continue
        ch=hier[0][j][2]; holes=[]
        while ch!=-1: holes.append(cs[ch]); ch=hier[0][ch][0]
        if not holes: continue
        hole=max(holes,key=cv2.contourArea)
        hx,hy,hw,hh=cv2.boundingRect(hole)
        if hw<0.6*w or cv2.contourArea(hole)<300: continue
        # ring should be ellipse-like: fit ellipse to outer & inner contours, check residual
        found.append((i,k,c.reshape(-1,2).astype(float),hole.reshape(-1,2).astype(float)))
print("ring frames",len(found))
def aniso(pts,cam):
    P=cam.ground(pts)[:,:2]; P=P[np.isfinite(P).all(1)]
    if len(P)<20: return None
    el=cv2.fitEllipse(P.astype(np.float32)*1000)
    (cx,cy),(a,b),ang=el
    return min(a,b)/max(a,b),(a+b)/4
res=[]
for i,k,o,h in found:
    row=[]
    for f in range(220,361,5):
        cam=Cam(f=f,pitch_deg=math.degrees(math.atan((120-VH)/f)))
        ro=aniso(o,cam); ri=aniso(h,cam)
        row.append((f,ro,ri))
    res.append((i,k,row))
pickle.dump((found,res),open("ring.pkl","wb"))
# best f per frame: maximise mean of axis ratios (outer & inner)
bests=[]
for i,k,row in res:
    sc=[(f,(ro[0]+ri[0])/2, ro[1],ri[1]) for f,ro,ri in row if ro and ri]
    if not sc: continue
    fb=max(sc,key=lambda t:t[1])
    bests.append((i,k,fb[0],fb[1],fb[2],fb[3]))
for b in bests: print(b)
