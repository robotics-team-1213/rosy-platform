import cv2,sys
from common import D
def get(i,k):
    c=cv2.VideoCapture(D+f"teleop_20260919_151213_part0{i}.mp4"); c.set(cv2.CAP_PROP_POS_FRAMES,k); ok,f=c.read(); return f
