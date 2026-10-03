#!/usr/bin/env bash
# 9p 읽기 캐시 무효화: WSL 쪽에서 소스를 touch 한 뒤 복사한다.
# 이 스크립트가 든 체크아웃(메인이든 worktree 든)의 pilot 을 복사한다.
SRC="$(cd "$(dirname "$0")/.." && pwd)/middleware/ui/pilot"
for file in app.js sw.js styles.css screens/drive.js screens/drive-auto.js screens/drive-view.js screens/inputs.js screens/connect.js input-state.js vision.js stick.js link.js client.js index.html manifest.webmanifest; do
  touch "$SRC/$file"
done
cp "$SRC/app.js" /rosy/middleware/ui/pilot/app.js
cp "$SRC/sw.js" /rosy/middleware/ui/pilot/sw.js
cp "$SRC/styles.css" /rosy/middleware/ui/pilot/styles.css
cp "$SRC/index.html" /rosy/middleware/ui/pilot/index.html
cp "$SRC/manifest.webmanifest" /rosy/middleware/ui/pilot/manifest.webmanifest
for file in client.js stick.js link.js input-state.js vision.js; do
  cp "$SRC/$file" /rosy/middleware/ui/pilot/$file
done
cp "$SRC/screens/connect.js" /rosy/middleware/ui/pilot/screens/connect.js
cp "$SRC/screens/drive.js" /rosy/middleware/ui/pilot/screens/drive.js
cp "$SRC/screens/drive-auto.js" /rosy/middleware/ui/pilot/screens/drive-auto.js
cp "$SRC/screens/drive-view.js" /rosy/middleware/ui/pilot/screens/drive-view.js
cp "$SRC/screens/inputs.js" /rosy/middleware/ui/pilot/screens/inputs.js
cp "$SRC/drivers/registry.js" /rosy/middleware/ui/pilot/drivers/registry.js
cp "$SRC/drivers/pinky_core.js" /rosy/middleware/ui/pilot/drivers/pinky_core.js
echo "copied. verify:"
grep -c "data-pilot-screen" /rosy/middleware/ui/pilot/app.js
grep -c "skipWaiting" /rosy/middleware/ui/pilot/sw.js
grep -c "grid-template-rows: 1fr auto" /rosy/middleware/ui/pilot/styles.css
