import pickle,numpy as np,math,json
rec=pickle.load(open("vp_rec.pkl","rb"))
F=281.6; tr=math.tan(math.radians(0.91))
from cammodel import Cam
c=Cam()
# horizon slope in image from model
a=c.project(np.array([[1e6,1e6*0.5,0],[1e6,-1e6*0.5,0]]))[0]; slope=(a[1,1]-a[0,1])/(a[1,0]-a[0,0]); print("model horizon slope px/px %.4f"%slope)
g=[(i,k,r) for i,k,r in rec if r and r[4]>20 and r[2]>=3 and r[3]>150 and -200<r[0]<520]
vh=np.array([r[1]+(160-r[0])*slope for i,k,r in g])
print("n",len(g),"of",len(rec))
print("vh median %.1f mean %.1f sd %.1f IQR %.1f-%.1f p5-p95 %.1f-%.1f"%(np.median(vh),vh.mean(),vh.std(),*np.percentile(vh,[25,75]),*np.percentile(vh,[5,95])))
# robust sd via MAD
mad=np.median(np.abs(vh-np.median(vh)))*1.4826; print("robust sd %.2f px -> %.2f deg"%(mad,math.degrees(math.atan(mad/F))))
pitch=np.degrees(np.arctan((120-vh)/F)); print("pitch median %.2f deg"%np.median(pitch))
# per part
for p in range(1,8):
    v=np.array([r[1]+(160-r[0])*slope for i,k,r in g if i==p])
    if len(v): print("part",p,len(v),"median %.1f MAD-sd %.2f"%(np.median(v),np.median(np.abs(v-np.median(v)))*1.4826))
# temporal jitter: consecutive-frame differences
d=[]; 
for (i1,k1,r1),(i2,k2,r2) in zip(g,g[1:]):
    if i1==i2 and k2-k1==1: d.append((r2[1]+(160-r2[0])*slope)-(r1[1]+(160-r1[0])*slope))
d=np.array(d); print("consecutive diffs n %d, MAD-sd %.2f px, frac |d|>5px %.3f"%(len(d),np.median(np.abs(d))*1.4826/math.sqrt(2),np.mean(np.abs(d)>5)))
# outliers (bumps): frames with vh deviating >8px
out=np.abs(vh-np.median(vh))>8; print("frac >8px from median %.3f, >4px %.3f"%(out.mean(),(np.abs(vh-np.median(vh))>4).mean()))
hist=np.histogram(vh,bins=np.arange(60,101,2)); print(list(zip(hist[1][:-1].astype(int),hist[0])))
json.dump(dict(n=len(g),vh_median=float(np.median(vh)),vh_mad_sd=float(mad),series=[(i,k,float(v)) for (i,k,_),v in zip(g,vh)]),open("vp_series.json","w"))
