import os, cv2, numpy as np
D=os.environ.get("ROSY_TELEOP_DIR",os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..","..","..","data","teleop","learning"))+os.sep
def frames():
    for i in range(1,8):
        c=cv2.VideoCapture(D+f"teleop_20260919_151213_part0{i}.mp4"); k=0
        while True:
            ok,f=c.read()
            if not ok: break
            yield i,k,f; k+=1
def load_all():
    return [(i,k,f) for i,k,f in frames()]
