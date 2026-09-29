// Rosy Pilot 서비스 워커(D-323 T10, D-328). 앱 셸만 캐시한다.
// /api/*·/ws/* 는 절대 캐시하지 않는다 — 명령과 상태는 네트워크 전용이고,
// 오프라인에서 조종 경로를 열지 않는 것이 이 앱의 안전 계약이다(D-323 §7).

const CACHE = "rosy-pilot-shell-2026-09-29-5";   // 캐시 키 = 이미지 버전. 바뀌면 이 이름을 올린다.
const SHELL = [
  "/pilot",
  "/pilot/assets/styles.css",
  "/pilot/assets/app.js",
  "/pilot/assets/client.js",
  "/pilot/assets/recent.js",
  "/pilot/assets/stick.js",
  "/pilot/assets/link.js",
  "/pilot/assets/input-state.js",
  "/pilot/assets/vision.js",
  "/pilot/assets/drivers/registry.js",
  "/pilot/assets/drivers/pinky_core.js",
  "/pilot/assets/screens/connect.js",
  "/pilot/assets/screens/drive.js",
  "/common/tokens.css",
  "/common/components.css",
  "/common/ui.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();   // 새 SW 는 즉시 활성 — 이미지 버전마다 캐시가 바뀌므로 대기 무의미.
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;   // 네트워크 전용
  if (event.request.method !== "GET") return;
  event.respondWith(caches.match(event.request).then((hit) => hit ?? fetch(event.request)));
});
