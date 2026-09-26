import json,numpy as np
R=json.load(open("hazards_raw.json"))
def arr(key,cond=lambda r:True): return np.array([r[key] for r in R if r[key] is not None and cond(r)])
n=len(R); print("frames sampled",n)
cm=arr("carpet_med"); print("carpet gray median %.0f (p5-p95 %.0f-%.0f); within-frame std median %.1f; carpet p99.5 median %.0f; carpet>180 frac median %.4f, frames with >0.5%% carpet>180: %.3f"%(np.median(cm),*np.percentile(cm,[5,95]),np.median(arr("carpet_std")),np.median(arr("carpet_p99")),np.median(arr("carpet_gt180")),np.mean(arr("carpet_gt180")>0.005)))
t=arr("tape_med"); print("tape frames %d, tape gray median %.0f (p5-p95 %.0f-%.0f); tape p10 median %.0f; tape>180 frac median %.2f"%(len(t),np.median(t),*np.percentile(t,[5,95]),np.median(arr("tape_p10")),np.median(arr("tape_gt180"))))
w=arr("wall_med"); print("wall frames %d (%.2f), wall gray median %.0f (p5-p95 %.0f-%.0f); wall>180 frac median %.2f"%(len(w),len(w)/n,np.median(w),*np.percentile(w,[5,95]),np.median(arr("wall_gt180"))))
both=[(r["wall_med"],r2) for r in R for r2 in [None]]
# same-frame comparison: wall vs tape where both measured with relaxed tape condition
# use per-part medians
for p in range(1,8):
    tp=arr("tape_med",lambda r:r["i"]==p); wp=arr("wall_med",lambda r:r["i"]==p)
    if len(tp) and len(wp): print(" part",p,"tape %.0f wall %.0f  wall-tape %+.0f"%(np.median(tp),np.median(wp),np.median(wp)-np.median(tp)))
wf=arr("wall_frac"); print("frames where wall covers >50%% of horizon row: %.2f, >20%%: %.2f"%(np.mean(wf>0.5),np.mean(wf>0.2)))
b=arr("blue_frac"); print("blue tape visible (>0.2%% px): %.2f of frames, >2%%: %.2f; blue gray median %.0f, blue V median %.0f"%(np.mean(b>0.002),np.mean(b>0.02),np.median(arr("blue_gray")),np.median(arr("blue_V"))))
gf=arr("glare_floor"); print("glare (V>=250,S<40) on floor rows>=90: frames with >0.1%%: %.2f, >1%%: %.2f; any saturated >1%% frame: %.2f"%(np.mean(gf>0.001),np.mean(gf>0.01),np.mean(arr("sat_frac")>0.01)))
s=arr("sharp"); med=np.median(s); print("sharpness (Laplacian var, rows>=130) median %.0f; frames < 0.5x median: %.2f, < 0.33x: %.2f"%(med,np.mean(s<0.5*med),np.mean(s<0.33*med)))
json.dump(dict(n=n),open("hazards_summary.json","w"))
