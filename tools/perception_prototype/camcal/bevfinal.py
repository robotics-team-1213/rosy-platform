import cv2,numpy as np,math,json
from cammodel import Cam
from getframes import get
cam=Cam(f=281.6,pitch_deg=8.0,roll_deg=0.9,h=0.067)
R=0.002; rep={}
for (i,k) in [(1,200),(6,400),(1,615)]:
    f=get(i,k); b,X,Y=cam.bev(f,xr=(0.10,0.80),yr=(-0.30,0.30),res=R)
    g=cv2.cvtColor(b,cv2.COLOR_BGR2GRAY); m=g>np.percentile(g[g<200],50)+50
    pts=[]
    for r in np.flatnonzero((X>0.12)&(X<0.6)):
        cols=np.flatnonzero(m[r])
        for ru in (np.split(cols,np.flatnonzero(np.diff(cols)>2)+1) if len(cols) else []):
            if 6<=len(ru)<=25: pts.append((X[r],Y[int(ru.mean())],len(ru)*R))
    pts=np.array(pts); rng=np.random.default_rng(1); fits=[]; rem=pts
    for _ in range(3):
        best=None
        for _ in range(400):
            a,c=rng.choice(len(rem),2,replace=False)
            if abs(rem[a,0]-rem[c,0])<0.1: continue
            sl=(rem[c,1]-rem[a,1])/(rem[c,0]-rem[a,0]); ic=rem[a,1]-sl*rem[a,0]
            inl=np.abs(rem[:,1]-(ic+sl*rem[:,0]))/math.sqrt(1+sl*sl)<0.006
            if best is None or inl.sum()>best.sum(): best=inl
        if best is None or best.sum()<25: break
        p=np.polyfit(rem[best,0],rem[best,1],1); fits.append((p,int(best.sum()),float(rem[best,2].mean()))); rem=rem[~best]
    fits.sort(key=lambda t:-t[1]); lanes=sorted(fits[:2],key=lambda t:t[0][1])
    out=cv2.resize(b,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
    def pix(x,y): return (int((Y[0]-y)/R*2),int((X[0]-x)/R*2))
    for x in np.arange(0.1,0.81,0.1):
        cv2.line(out,pix(x,Y[0]),pix(x,Y[-1]),(0,200,255),1); cv2.putText(out,"%.1fm"%x,(pix(x,Y[0])[0]+3,pix(x,Y[0])[1]-3),0,0.45,(0,200,255),1)
    for y in np.arange(-0.3,0.31,0.1): cv2.line(out,pix(X[0],y),pix(X[-1],y),(0,200,255),1)
    for p,n,w in lanes: cv2.line(out,pix(0.12,np.polyval(p,0.12)),pix(0.6,np.polyval(p,0.6)),(0,0,255),1)
    (p1,_,w1),(p2,_,w2)=lanes
    ang=math.degrees(math.atan(p1[0])-math.atan(p2[0])); sl=(p1[0]+p2[0])/2
    sep=[abs(np.polyval(p1,x)-np.polyval(p2,x))*math.cos(math.atan(sl))*1000 for x in (0.2,0.3,0.5)]
    t="angle %.2f deg | c-c sep @0.2/0.3/0.5m: %.0f/%.0f/%.0f mm | widths %.0f,%.0f mm"%(ang,*sep,w1*1000,w2*1000)
    cv2.rectangle(out,(0,out.shape[0]-24),(out.shape[1],out.shape[0]),(0,0,0),-1); cv2.putText(out,t,(6,out.shape[0]-8),0,0.45,(255,255,255),1)
    cv2.imwrite(f"out/bev_p{i}_{k:04d}.png",out); rep[f"p{i}_{k}"]=dict(angle_deg=ang,sep_mm_at_0p2_0p3_0p5=sep,widths_mm=[w1*1000,w2*1000]); print(i,k,t)
json.dump(rep,open("out/bev_check.json","w"),indent=1)
