import cv2,numpy as np,json
from common import frames
out=[]
for i,k,f in frames():
    if k%4: continue
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY).astype(float); S=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)[:,:,1]
    white=(g>np.median(g[180:])+45)&(S<70)
    wallcols=white[72:90].all(0)
    # wall columns whose wall run ends above row 160 (so lower band is floor)
    ok=[]
    for u in np.flatnonzero(wallcols):
        b=90
        while b<239 and white[b+1,u]: b+=1
        if b<150: ok.append(u)
    ok=np.array(ok)
    if len(ok)<30: continue
    wall=g[35:72][:,ok][white[35:72][:,ok]]
    floorband=white[175:].copy(); floorband[:,ok]&=True
    tape=g[175:][white[175:]]
    if len(tape)<150 or len(wall)<300: continue
    carpet=g[175:][~white[175:]]
    out.append((i,k,float(np.median(tape)),float(np.percentile(tape,10)),float(np.median(wall)),float(np.percentile(wall,90)),float(np.median(carpet))))
a=np.array([o[2:] for o in out])
d=a[:,2]-a[:,0]
print("same-frame n",len(a))
print("tape median gray %.0f, wall median %.0f, carpet %.0f"%tuple(np.median(a[:,[0,2,4]],0)))
print("wall - tape (median of per-frame diffs) %+.0f, p10-p90 %+.0f..%+.0f"%(np.median(d),*np.percentile(d,[10,90])))
print("frames wall median >= tape median: %.2f ; wall p90 >= tape p10: %.2f ; wall >= tape-10: %.2f"%(np.mean(d>=0),np.mean(a[:,3]>=a[:,1]),np.mean(d>=-10)))
print("tape-carpet contrast median %.0f; wall-carpet %.0f"%(np.median(a[:,0]-a[:,4]),np.median(a[:,2]-a[:,4])))
json.dump(out,open("tape_vs_wall.json","w"))
