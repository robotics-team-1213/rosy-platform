## D-328 Rosy Pilot 설치형은 PWA 로 우선하고 Capacitor 래퍼는 네이티브 전용 수요가 실측될 때까지 보류한다

**Status:** Accepted (2026-09-29, 설치 형식 결정). 구현·장치·현장 수용은 별도 HOLD.

## Context

1차 조종 기기는 현장 태블릿(Lenovo 1200×2000)이다. "앱처럼 쓰고 싶다"는 요구에
두 갈래가 있다: PWA(manifest + service worker, 로봇 이미지가 앱을 함께 배포)와
Capacitor 네이티브 래퍼(APK 빌드·서명·배포). D-323 은 조종 중 카메라 녹화·
WebSocket·미디어를 전부 표준 브라우저 API 로 풀기로 했고, 네이티브 전용 기능
(백그라운드 조종, 스토어 배포)은 아직 수요 근거가 없다. 앱을 로봇 이미지에서
분리하는 순간 앱↔CORE API 버전 스큐(이 저장소가 계약 시험으로 막아온 문제)가
새로 생긴다. Capacitor 는 Android SDK·Gradle 빌드라인과 APK 서명·업데이트
경로라는 두 번째 배포 원장을 요구한다.

## Decision

1. 설치형은 **PWA 로 우선**한다. `manifest.webmanifest`(`start_url=/pilot`,
   `scope=/pilot`, standalone, 가로 기준), 서비스 워커(앱 셸 캐시,
   캐시 키=이미지 버전), 설치 아이콘(토큰 색)을 `/pilot` 에 둔다.
2. 서비스 워커는 `/api/*`·`/ws/*` 를 **절대 캐시하지 않는다** — 명령과 상태는
   네트워크 전용이고, 오프라인에서 조종 경로를 열지 않는 것이 안전 계약이다
   (D-323 §7). 조종 중 화면 꺼짐 방지는 Wake Lock API 로 처리한다(T7).
3. **Capacitor 는 보류(비목표)**. 재고 조건은 실측 수요다: 스토어/APK 배포
   요구, 화면이 꺼진 상태의 조종, 브라우저가 못 만지는 기기 API. 이 중 하나가
   실측 근거로 생기면 그때 후속 ADR 로 연다.

## Consequences and rollout

설치·업데이트가 브라우저 흐름(Chrome "앱 추가")을 따르고 아이콘·전용 창을
얻는다. 앱과 CORE API 의 버전 정합은 이미지 단위로 유지된다. Capacitor 로
갈아타더라도 화면·로직은 그대로 웹 자산이라 재포장 비용만 남는다. 구현과
장치·현장 수용은 실행 계획 T10·T11 이후 별도 게이트로 남는다.

**Related:** [D-323](D-323-rosy-pilot-teleop-app.md), [D-23](D-23-rosy-os-fastapi.md),
[D-197](D-197-docker-exits-the-product-chain.md).

---
