#!/usr/bin/env bash
# /mnt/f → /rosy 바이너리 안전 동기화 (tar, 9p 캐시 무시)
set -e
SRC="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"

# 소스를 tar로 묶어서 /rosy에 풀기 (바이너리 안전)
echo "== pilot 패키지 =="
rm -rf /rosy/middleware/ui/pilot
tar -C "$SRC" -cf - middleware/ui/pilot | tar -C /rosy -xf -

echo "== web_common =="
mkdir -p /rosy/shared/web
cp "$SRC/shared/web/evidence.js" /rosy/shared/web/evidence.js 2>/dev/null || \
  tar -C "$SRC" -cf - shared/web/evidence.js | tar -C /rosy -xf -

echo "== 검증 =="
head -1 /rosy/middleware/ui/pilot/vision.js
head -1 /rosy/middleware/ui/pilot/app.js
node --check /rosy/middleware/ui/pilot/vision.js && echo "vision OK"
node --check /rosy/middleware/ui/pilot/app.js && echo "app OK"
node --check /rosy/middleware/ui/pilot/screens/connect.js && echo "connect OK"
node --check /rosy/middleware/ui/pilot/screens/drive.js && echo "drive OK"
node --check /rosy/middleware/ui/pilot/screens/drive-auto.js && echo "drive-auto OK"
node --check /rosy/middleware/ui/pilot/screens/drive-view.js && echo "drive-view OK"
echo "== 한글 확인 =="
grep -c "운전 토큰" /rosy/middleware/ui/pilot/screens/connect.js || echo "connect 한글 없음!"
grep -c "sequence" /rosy/middleware/ui/pilot/vision.js
echo "== DONE =="
