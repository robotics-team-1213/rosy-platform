## D-366 Rosy Pilot 의 조종 대상 확장은 기기 종류별 드라이버 레지스트리로 수용하며, 장치별 조종 컨트롤(그리퍼·팔 위치 등)은 그 장치의 계약이 열 때 프런트에 반영한다

**Status:** Accepted (2026-09-29, 로드맵·프런트 경계 결정). Pinky 가제보 주행이 최우선이며,
OMX-AI 등 타 장치의 실기·시뮬레이션 수용은 각 장치의 게이트를 따른다.

## Context

Pilot 의 첫 대상은 Pinky 주행이고, 검증 대장정은 가제보다(사용자 결정, D-323·D-365).
추후에는 OMX-AI 팔(그리퍼 개폐·위치 이동) 등 다른 장치도 시뮬레이션 포함 조종 대상이
된다. 장치별 조종은 ROS 측 컨트롤·토픽·액션의 반영이므로, 프런트(아이콘·컨트롤)는 그
계약이 있을 때 나타나야 한다 — 계약보다 먼저 아이콘을 보여주면 없는 능력을 광고하는
것이고, 이는 CAP-001 이 막는 거짓말이다. D-296 은 팔 최종 명령 소유를 OMX 로컬로
고정하고, D-273 은 OMX 카메라·팔 제어의 구현 순서를, D-299 는 LeRobot 실험 경로를
분리해 둔다.

## Decision

1. 조종 대상 확장은 `drivers/registry.js` 의 기기 종류 → 드라이버 매핑으로만 수용한다
   (D-323 §10). 장치 추가 = 드라이버 하나 + 화면 컴포넌트(`screens/<device>.js`) 추가이고,
   공통 셸·게이트·세션(link.js)은 바뀌지 않는다.
2. 장치별 조종 컨트롤(그리퍼, 팔 조그, 위치 이동 등)과 그 아이콘은 **그 장치의 API 계약이
   노출하는 능력에서만** 생긴다. 프런트는 계약에 없는 조종을 미리 렌더링하지 않고,
   capability 게이트(409 `CAPABILITY_WITHHELD`) 뒤에서만 활성화된다.
3. 조종 컨트롤의 아이콘·배치·상태 표기는 web_common 어휘(tokens·`ui-*`·오버레이 칩
   규칙)를 따른다. 장치별 화면 파일 하나가 장치별 컨트롤 전체를 소유한다.
4. 우선순위: **Pinky 가제보 주행이 최우선**이다. OMX-AI 는 D-273 의 순서(실물 제어
   기준선 → 상부 RGB → 집기 → 손목)와 D-296·D-299 경계가 열어주는 대로 레지스트리에
   등록되며, 시뮬레이션 쪽은 D-322 의 Isaac 경로와 가제보 경로를 모두 쓸 수 있다.

## Consequences and rollout

프런트는 장치 계약의 뒤를 따른다(역방향 없음) — 계약 없는 아이콘은 기술 부채가 아니라
거짓 광고다. 타 장치 드라이버가 등록되면 게이트·세션·녹화 등 공용 구조는 재사용되고,
장치별 화면만 새로 붙는다. 각 장치의 운영 수용은 해당 장치의 DEVICE/FIELD 게이트로
별도 판정한다.

**Related:** [D-323](D-323-rosy-pilot-teleop-app.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md),
[D-296](D-296-device-middleware-and-site-orchestration-terminology.md),
[D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-322](D-322-isaac-sim-rosy-integration.md),
[D-365](D-365-pilot-pwa-first.md).

---
