import cv2,numpy as np,pickle
from common import *
out=[]
for i,k,f in frames():
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    floor=np.median(g[200:,:])
    m=((g>floor+45)&(hsv[:,:,1]<70)).astype(np.uint8)
    m[:85]=0
    n,l,st,c=cv2.connectedComponentsWithStats(m)
    cand=[j for j in range(1,n) if 60<st[j,4]<4000 and st[j,3]<80 and st[j,2]<90 and st[j,1]>85]
    # group by similar centroid y and similar area
    best=None
    for a in cand:
        grp=[b for b in cand if abs(c[b,1]-c[a,1])<6 and 0.5<st[b,4]/st[a,4]<2 and abs(st[b,3]-st[a,3])<max(4,0.3*st[a,3])]
        if len(grp)>=4 and (best is None or len(grp)>len(best)): best=grp
    if best and len(best)==4:
        xs=sorted(c[b,0] for b in best); d=np.diff(xs)
        if d.max()/d.min()<1.6:
            out.append((i,k,[tuple(st[b]) for b in best]))
print(len(out))
from collections import Counter
print(Counter(o[0] for o in out))
runs=[];prev=None
for o in out:
    key=(o[0],o[1])
    if prev and prev[0]==o[0] and o[1]-prev[1]<=3: runs[-1].append(o[1])
    else: runs.append([o[0],o[1]])
    prev=key
for r in runs: print(r[0], r[1], r[-1], len(r)-1)
pickle.dump(out,open("cw_frames.pkl","wb"))
