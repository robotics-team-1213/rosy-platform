#!/usr/bin/env bash
# 9p 읽기 캐시 무효화: WSL 쪽에서 소스를 touch 한 뒤 복사한다.
# 이 스크립트가 든 체크아웃(메인이든 worktree 든)의 pilot 을 복사한다.
SRC="$(cd "$(dirname "$0")/.." && pwd)/src/hmi/pilot"
for file in app.js sw.js styles.css screens/drive.js screens/drive-auto.js screens/drive-view.js screens/inputs.js screens/connect.js input-state.js vision.js stick.js link.js client.js index.html manifest.webmanifest; do
  touch "$SRC/$file"
done
cp "$SRC/app.js" /rosy/src/hmi/pilot/app.js
cp "$SRC/sw.js" /rosy/src/hmi/pilot/sw.js
cp "$SRC/styles.css" /rosy/src/hmi/pilot/styles.css
cp "$SRC/index.html" /rosy/src/hmi/pilot/index.html
cp "$SRC/manifest.webmanifest" /rosy/src/hmi/pilot/manifest.webmanifest
for file in client.js stick.js link.js input-state.js vision.js; do
  cp "$SRC/$file" /rosy/src/hmi/pilot/$file
done
cp "$SRC/screens/connect.js" /rosy/src/hmi/pilot/screens/connect.js
cp "$SRC/screens/drive.js" /rosy/src/hmi/pilot/screens/drive.js
cp "$SRC/screens/drive-auto.js" /rosy/src/hmi/pilot/screens/drive-auto.js
cp "$SRC/screens/drive-view.js" /rosy/src/hmi/pilot/screens/drive-view.js
cp "$SRC/screens/inputs.js" /rosy/src/hmi/pilot/screens/inputs.js
cp "$SRC/drivers/registry.js" /rosy/src/hmi/pilot/drivers/registry.js
cp "$SRC/drivers/pinky_core.js" /rosy/src/hmi/pilot/drivers/pinky_core.js
echo "copied. verify:"
grep -c "data-pilot-screen" /rosy/src/hmi/pilot/app.js
grep -c "skipWaiting" /rosy/src/hmi/pilot/sw.js
grep -c "grid-template-rows: 1fr auto" /rosy/src/hmi/pilot/styles.css
