import cv2,numpy as np,pickle,math
res=pickle.load(open("cw_corners.pkl","rb"))
keys=sorted(res)
obj=[res[k][0] for k in keys]; img=[res[k][1] for k in keys]
def run(flags,K0,d0=None):
    d0=np.zeros(5) if d0 is None else d0
    rms,K,d,rv,tv=cv2.calibrateCamera(obj,img,(320,240),K0.copy(),d0.copy(),flags=flags)
    return rms,K,d,rv,tv
K0=np.array([[250,0,160],[0,250,120],[0,0,1.]])
base=cv2.CALIB_USE_INTRINSIC_GUESS|cv2.CALIB_FIX_ASPECT_RATIO|cv2.CALIB_ZERO_TANGENT_DIST|cv2.CALIB_FIX_K1|cv2.CALIB_FIX_K2|cv2.CALIB_FIX_K3
for name,fl in [("fixpp,nodist",base|cv2.CALIB_FIX_PRINCIPAL_POINT),("freepp,nodist",base),("fixpp,k1",(base|cv2.CALIB_FIX_PRINCIPAL_POINT)&~cv2.CALIB_FIX_K1)]:
    rms,K,d,rv,tv=run(fl,K0)
    print(name,"rms %.3f"%rms,"f %.1f cx %.1f cy %.1f"%(K[0,0],K[0,2],K[1,2]),"k1 %.3f"%d.ravel()[0], "hfov %.1f"%(2*math.degrees(math.atan(160/K[0,0]))))
    if name=="fixpp,nodist": sol=(K,d,rv,tv)
K,d,rv,tv=sol
rows=[]
for k,r,t in zip(keys,rv,tv):
    R,_=cv2.Rodrigues(r); C=(-R.T@t).ravel()
    zc=R.T@np.array([0,0,1.]); xc=R.T@np.array([1,0,0.])
    # object Z axis: (X right, Y forward, Z) -> check sign
    s=1 if C[2]>0 else -1
    h=s*C[2]; pitch=math.degrees(math.asin(-s*zc[2])); roll=math.degrees(math.asin(s*xc[2]))
    dist=math.hypot(C[0]-60,C[1])
    per=cv2.projectPoints(res[k][0],r,t,K,d)[0].reshape(-1,2)
    e=np.sqrt(((per-res[k][1])**2).sum(1)).mean()
    rows.append((k,h,pitch,roll,dist,e))
    print(k,"h %.1f mm pitch_down %.2f roll %.2f dist %.0f mm err %.2f px"%(h,pitch,roll,dist,e))
a=np.array([r[1:] for r in rows])
print("h mean %.1f sd %.1f | pitch mean %.2f sd %.2f | roll mean %.2f sd %.2f"%(a[:,0].mean(),a[:,0].std(),a[:,1].mean(),a[:,1].std(),a[:,2].mean(),a[:,2].std()))
pickle.dump((keys,sol,rows),open("calib_cw.pkl","wb"))
