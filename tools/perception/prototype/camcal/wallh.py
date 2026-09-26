import cv2,numpy as np,math,pickle
from common import frames
from cammodel import Cam
base=Cam()
Hs=np.arange(0.040,0.110,0.0005)
cams=[Cam(h=h) for h in Hs]
def hfit(u,vt,vb):
    # for each h: ground point of base, project top at 0.155
    errs=[]
    for c in cams:
        P=c.ground(np.c_[u,vb]); P[:,2]=0.155
        uv,_=c.project(P); errs.append(uv[:,1]-vt)
    errs=np.array(errs)  # nh x n
    # per column root via interpolation
    hs=[]
    for j in range(errs.shape[1]):
        e=errs[:,j]; s=np.flatnonzero(np.sign(e[:-1])!=np.sign(e[1:]))
        if len(s): a=s[0]; hs.append(Hs[a]+(Hs[a+1]-Hs[a])*e[a]/(e[a]-e[a+1]))
    return np.array(hs)
def linefit(u,v,rng):
    best=None
    for _ in range(100):
        a,b=rng.choice(len(u),2,replace=False)
        if u[a]==u[b]: continue
        s=(v[b]-v[a])/(u[b]-u[a]); r=np.abs(v-(v[a]+s*(u-u[a]))); inl=r<1.0
        if best is None or inl.sum()>best.sum(): best=inl
    return best
rng=np.random.default_rng(0); rows=[]
for i,k,f in frames():
    if k%2: continue
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); V=hsv[:,:,2].astype(int); S=hsv[:,:,1]
    wall=(V>150)&(S<60)
    U=[];T=[];B=[]
    for u in range(10,310,2):
        col=wall[:,u]
        if not col[70:90].all(): continue
        t=70
        while t>0 and col[t-1]: t-=1
        b=90
        while b<239 and col[b+1]: b+=1
        if t<=1 or b>=236: continue
        # edges must be sharp: top: background darker by >40
        if V[max(0,t-3),u] > V[t+2,u]-40: continue
        if V[min(239,b+3),u] > V[b-2,u]-50: continue
        U.append(u);T.append(t-0.5);B.append(b+0.5)
    if len(U)<40: continue
    U=np.array(U,float);T=np.array(T);B=np.array(B)
    it=linefit(U,T,rng); ib=linefit(U,B,rng); inl=it&ib
    if inl.sum()<40: continue
    hs=hfit(U[inl],T[inl],B[inl])
    if len(hs)<30: continue
    rows.append((i,k,float(np.median(hs)),int(inl.sum()),float(np.median(B[inl]-T[inl]))))
pickle.dump(rows,open("wallh.pkl","wb"))
a=np.array([r[2] for r in rows]); print("frames",len(rows),"h median %.1f mm, MAD-sd %.1f, p10-p90 %.1f-%.1f"%(np.median(a)*1000,np.median(np.abs(a-np.median(a)))*1482.6,*(np.percentile(a,[10,90])*1000)))
for r in rows[::max(1,len(rows)//25)]: print(r)
