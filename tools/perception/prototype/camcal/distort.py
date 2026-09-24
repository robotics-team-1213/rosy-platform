import cv2,numpy as np,pickle
from getframes import get
rows=pickle.load(open("wallh.pkl","rb"))
sel=[r for r in rows if r[3]>=100]
print("frames with >=100 wall columns",len(sel))
out=[]
for i,k,h,n,sz in sel:
    f=get(i,k); hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); V=hsv[:,:,2].astype(float); S=hsv[:,:,1]
    U=[];T=[];B=[]
    for u in range(5,315):
        col=(V[:,u]>150)&(S[:,u]<60)
        if not col[70:90].all(): continue
        t=70
        while t>0 and col[t-1]: t-=1
        b=90
        while b<239 and col[b+1]: b+=1
        if t<=1 or b>=236: continue
        # subpixel edge: gradient peak along column
        gcol=np.abs(np.diff(V[:,u]))
        bb=b+ (0 if b+2>=239 else 0)
        U.append(u);T.append(t);B.append(b)
    U=np.array(U,float);B=np.array(B,float);T=np.array(T,float)
    for name,v in [("base",B),("top",T)]:
        p1=np.polyfit(U,v,1); r=v-np.polyval(p1,U)
        keep=np.abs(r)<3
        if keep.sum()<100: continue
        p2=np.polyfit(U[keep],v[keep],2)
        span=U[keep].max()-U[keep].min()
        sag=-p2[0]*(span/2)**2   # positive = ends lower than middle? (image v down)
        rowc=np.polyval(p2,160)
        out.append((i,k,name,round(rowc,1),round(span),round(sag,2),round(np.std(v[keep]-np.polyval(p2,U[keep])),2)))
for o in out: print(o)
a=np.array([(o[3],o[5]) for o in out])
# predicted sag for k1 at row y: line through distorted image
def pred(k1,y,f=281.6):
    xs=np.linspace(-150,150,31); yn=(y-120)/f; xn=xs/f; r2=xn**2+yn**2; yd=yn*(1+k1*r2)*f+120
    return yd[15]-(yd[0]+yd[-1])/2
for k1 in [-0.2,-0.1,-0.05,0.05]:
    print("k1",k1,"pred sag at row 40: %.2f row 140: %.2f row 200: %.2f"%(pred(k1,40),pred(k1,140),pred(k1,200)))
pickle.dump(out,open("distort.pkl","wb"))
