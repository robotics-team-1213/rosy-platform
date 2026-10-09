from pathlib import Path
import json,subprocess
import numpy as np
import onnxruntime as ort
from PIL import Image,ImageDraw
root=Path('X:/DevTemp/rosy-drivable-candidate-20261008')
video=Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/video')
out=root/'full-1006'/'samples';out.mkdir(exist_ok=True)
s=ort.InferenceSession(str(root/'model.onnx'),providers=['CPUExecutionProvider']);key=s.get_inputs()[0].name
samples={'082612':[192,884,2129,2453,2458],'091340':[630]}
for session,indices in samples.items():
    source=video/f'teleop_rosy_26_20261006T{session}Z.mp4'
    for idx in indices:
        frame=out/f'{session}_{idx:04}.png'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(source),'-vf',f'select=eq(n\\,{idx})','-vsync','0','-frames:v','1','-y',str(frame)],check=True)
        im=Image.open(frame).convert('RGB');assert im.size==(320,240)
        rgb=np.asarray(im);x=np.ascontiguousarray((rgb.astype(np.float32)/255).transpose(2,0,1)[None])
        logits=s.run(None,{key:x})[0];labels=logits[0].argmax(axis=0)
        arr=rgb.astype(np.float32).copy()
        for role,color in [(1,(0,220,255)),(2,(0,220,255)),(3,(255,210,0)),(4,(255,110,0)),(5,(0,235,75))]:
            m=labels==role;arr[m]=arr[m]*.45+np.array(color)*.55
        canvas=Image.new('RGB',(640,270),'white');canvas.paste(im,(0,30));canvas.paste(Image.fromarray(arr.astype(np.uint8)),(320,30))
        d=ImageDraw.Draw(canvas);d.text((5,7),f'{session} frame {idx} original',fill='black');d.text((325,7),'CANDIDATE green=drivable',fill='black')
        canvas.save(out/f'{session}_{idx:04}.overlay.png')
        print(session,idx,round(float((labels[144:]==5).mean()),3))
