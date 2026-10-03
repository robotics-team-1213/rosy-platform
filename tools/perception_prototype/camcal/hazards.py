import cv2,numpy as np,json,math
from common import frames
R=[]
for i,k,f in frames():
    if k%2: continue
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY).astype(float); hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    H,S,V=hsv[:,:,0],hsv[:,:,1].astype(float),hsv[:,:,2].astype(float)
    low=g[170:]; lowS=S[170:]
    carpet_med=np.median(low)
    white=(g>carpet_med+45)&(S<70)
    # wall: bright low-sat run crossing horizon rows 75-85 extended upward
    wallcols=white[72:88].all(0)
    wall_pix=g[30:72][:,wallcols][white[30:72][:,wallcols]] if wallcols.sum()>20 else np.array([])
    wall_low=0
    if wallcols.sum()>0:
        # does wall extend into lower band (close wall)? rows 170+
        wall_low=white[170:][:, wallcols].mean()
    tape=low[white[170:]]
    tape_ok=len(tape)>150 and wallcols.sum()<40
    carpet=low[~white[170:]]
    # carpet texture: std and local std
    lap=cv2.Laplacian(g[130:].astype(np.float32),cv2.CV_32F)
    sharp=float(lap.var())
    blue=((H>=100)&(H<=130)&(S>100)&(V>60))
    glare=(V>=250)&(S<40)
    glare_floor=glare[90:].mean()
    R.append(dict(i=i,k=k,carpet_med=float(carpet_med),carpet_std=float(carpet.std()),carpet_p99=float(np.percentile(carpet,99.5)),
      carpet_gt180=float((carpet>180).mean()),
      tape_med=float(np.median(tape)) if tape_ok else None, tape_p10=float(np.percentile(tape,10)) if tape_ok else None,
      tape_gt180=float((tape>180).mean()) if tape_ok else None,
      wall_med=float(np.median(wall_pix)) if len(wall_pix)>200 else None, wall_gt180=float((wall_pix>180).mean()) if len(wall_pix)>200 else None,
      wall_frac=float(wallcols.mean()), sharp=sharp, blue_frac=float(blue.mean()), blue_gray=float(np.median(g[blue])) if blue.sum()>50 else None,
      blue_V=float(np.median(V[blue])) if blue.sum()>50 else None, glare_floor=float(glare_floor), glare_any=float(glare.mean()),
      sat_frac=float((g>=250).mean())))
json.dump(R,open("hazards_raw.json","w"))
print(len(R))
