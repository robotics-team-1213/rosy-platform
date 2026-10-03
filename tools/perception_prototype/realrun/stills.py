import cv2, json, os, numpy as np
S=[
 (1,288,"good_straight","Straight, both lines: centre BOTH conf 1.00 err +0.04 (correct). Device line mode says -0.57 (hard left) - centroid pulled to the brighter near left line."),
 (6,104,"good_curve","Left curve, both lines in view: BOTH conf 1.00 err -0.02 - correct centre-line target."),
 (5,261,"good_roundabout","Roundabout outer arc: ONE (right memory = ring) err -0.47 conf 0.80 - plausible arc following."),
 (3,91,"corner_one","Chevron corner: ONE from left line err -0.44 conf 0.80; device lane mode +0.18 conf 0.26 disagrees in sign."),
 (4,572,"junction_opens","Junction mouth: RIGHT_OPENS signal fires, ONE on left line err +0.03 - correct behaviour."),
 (1,440,"junction_branch_stop","Crossing a lane at an angle: BRANCH signal, tier STOP (no lane-width pair to seed). Device line mode would steer +0.22 on it."),
 (2,56,"crosswalk","Crosswalk at 0.17 m: centre STOP (bars are < 0.15 m, lines out of the 59 deg FOV at this range). road.py reports a crosswalk AND a false stop line (nearest bar, 0.14 m)."),
 (1,600,"threshold_fragmented","Both lines plainly visible but STOP: right tape peaks 169-185 grey vs threshold 180, so it breaks into 1-2 cell specks; no lane-width pair, no seed."),
 (1,704,"threshold_dim_line","Dim chevron line (peak < 180) in view, BEV empty: STOP. Device line mode meanwhile follows the wall (err +0.14)."),
 (4,492,"wall_ahead_BOTH","Facing a wall 0.2 m ahead: wall face projects into BEV as a 10 cm wide 'line'; ladder says BOTH conf 1.00 err -0.01 = drive straight into the wall."),
 (6,742,"wall_as_boundary","Wall beside the lane taken as the RIGHT boundary (it lies at y=+0.14 m, left of the robot): BOTH conf 1.00 err -0.48, steering toward the wall."),
 (4,126,"wall_as_right_line","Wall taken as the RIGHT lane boundary (a 10.5 cm wide BEV blob, 97% wall pixels): ONE err -0.24 conf 0.80."),
 (2,160,"wall_glare_line_mode","Wall glare fills the band: centre STOP (fine), but device line mode outputs err +0.49 conf 1.00 with 86% of its lit pixels on the wall."),
 (4,748,"wall_fills_view","Wall fills the view: centre and line both fail closed (washed). road.py still reports a stop line at 0.48 m (wall base)."),
 (4,624,"blur_and_shoes","Motion blur + a person's white shoes in view: shoe/leg read as a left line, ONE err -0.33 conf 0.60."),
 (6,579,"chevron_memory","Chevron V: right memory bends, ONE on it err +0.39 conf 0.80 while the robot sits still (VO 0 cm)."),
]
os.makedirs("out/stills",exist_ok=True); meta=[]
for p,f,slug,cap in S:
    im=cv2.imread(f"out/raw/p{p:02d}/{f:04d}.jpg")
    bar=np.full((44,im.shape[1],3),255,np.uint8)
    words=cap.split(); lines=[""]
    for w in words:
        if len(lines[-1])+len(w)>92: lines.append("")
        lines[-1]+=w+" "
    bar=np.full((16*len(lines)+8,im.shape[1],3),255,np.uint8)
    for k,t in enumerate(lines): cv2.putText(bar,t,(6,16+16*k),cv2.FONT_HERSHEY_SIMPLEX,0.42,(0,0,0),1,cv2.LINE_AA)
    name=f"p{p:02d}_{f:04d}_{slug}.jpg"
    cv2.imwrite("out/stills/"+name,np.vstack([im,bar]),[cv2.IMWRITE_JPEG_QUALITY,90])
    meta.append(dict(file="stills/"+name,part=p,frame=f,caption=cap))
json.dump(meta,open("out/stills/captions.json","w"),indent=1); print(len(meta))
