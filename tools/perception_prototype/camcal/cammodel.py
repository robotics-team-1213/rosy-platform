import numpy as np, math, cv2
class Cam:
    def __init__(s,f=281.6,cx=160.,cy=120.,pitch_deg=8.09,roll_deg=0.91,h=0.0694,fy=None):
        s.K=np.array([[f,0,cx],[0,fy or f,cy],[0,0,1.]]); s.h=h
        th=math.radians(pitch_deg); ph=math.radians(roll_deg)
        x=np.array([0,-1.,0]); z=np.array([math.cos(th),0,-math.sin(th)]); y=np.cross(z,x)
        xr=math.cos(ph)*x-math.sin(ph)*y; yr=math.sin(ph)*x+math.cos(ph)*y
        s.Rcw=np.c_[xr,yr,z]   # columns: camera axes in world (robot frame X fwd,Y left,Z up)
        s.C=np.array([0,0,h])
    def project(s,P):  # P Nx3 world
        pc=(P-s.C)@s.Rcw
        uv=pc@s.K.T; return uv[:,:2]/uv[:,2:3], pc[:,2]
    def ground(s,uv):
        d=np.c_[uv,np.ones(len(uv))]@np.linalg.inv(s.K).T
        dw=d@s.Rcw.T
        t=-s.h/dw[:,2]; P=s.C+dw*t[:,None]
        P[dw[:,2]>=0]=np.nan; return P
    def horizon_row(s,u=160.):
        # far point straight ahead direction projected
        P=np.array([[1e6,0,0]]); uv,_=s.project(P); return uv[0]
    def bev(s,img,xr=(0.08,1.2),yr=(-0.45,0.45),res=0.002):
        X=np.arange(xr[1],xr[0],-res); Y=np.arange(yr[1],yr[0],-res)
        YY,XX=np.meshgrid(Y,X)
        P=np.c_[XX.ravel(),YY.ravel(),np.zeros(XX.size)]
        uv,z=s.project(P)
        mx=uv[:,0].reshape(XX.shape).astype(np.float32); my=uv[:,1].reshape(XX.shape).astype(np.float32)
        out=cv2.remap(img,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(40,0,40))
        return out,X,Y
