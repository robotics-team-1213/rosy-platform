"""Side-by-side sheet: real teleop frames vs real-profile sim frames."""
import glob
import sys

import cv2
import numpy as np

real = sorted(glob.glob(r"X:\DevTemp\sim-real-profile\real\real_*.png"))
sim = sorted(glob.glob(sys.argv[1] + r"\*.png"))
out = sys.argv[2]
old = r"F:\Dev\Control\Robot\ROS\Rosy\Rosy OS\.worktrees\pilot-teleop\src\runtime\sensing\map\map_v2_fleet\review\camera_start_161132.png"


def tile(path, label, colour):
    im = cv2.imread(path)
    im = cv2.resize(im, (320, 240)) if im.shape[:2] != (240, 320) else im
    im = im.copy()
    cv2.line(im, (0, 80), (319, 80), (0, 255, 255), 1)
    cv2.putText(im, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, colour, 1)
    return cv2.copyMakeBorder(im, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(40, 40, 40))


n = min(len(real), len(sim), 20)
pairs = [np.hstack([tile(real[i], "REAL " + real[i][-6:-4], (0, 0, 255)),
                    tile(sim[i], "SIM " + sim[i].split("\\")[-1][:-4], (255, 128, 0))])
         for i in range(n)]
while len(pairs) % 2:
    pairs.append(np.zeros_like(pairs[0]))
rows = [np.hstack([pairs[i], pairs[i + 1]]) for i in range(0, len(pairs), 2)]
sheet = np.vstack(rows)
cv2.imwrite(out, sheet)
g = lambda p: cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2GRAY)
for name, files in (("real", real[:n]), ("sim", sim[:n])):
    b = [float(np.median(g(f)[180:240, 60:260])) for f in files]
    print(name, "bottom-band median grey", round(float(np.median(b)), 1),
          "range", round(min(b), 1), round(max(b), 1))
print("sheet", out, sheet.shape)
