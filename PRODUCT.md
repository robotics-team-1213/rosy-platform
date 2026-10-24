# Product

<!-- impeccable:product-schema 1 -->

## Platform

웹, Android 앱, 로봇 LCD

앱 이름과 현재 구현·소유의 기준은 [앱 이름과 역할](docs/reference/app-names-and-roles.md)이다(D-806). Robot·Fleet·Pilot·Cam·Learning·Games를 구분한다. 별도 저장소 업무 앱이던 Vault·Device는 rosy-vault 은퇴(2026-10-24)로 개발하지 않으며, 외부 업무 앱은 [지원 계약](docs/reference/application-contract-support.md)을 따른다(첫 사례 항만 앱 Harbor). Cell은 Fleet의 팔레타이징 작업 준비, Account는 공용 계정 기능이며 얼굴 LCD와 Pilot 연결 로비는 상위 앱의 하위 화면이다.

## Users

- 운용자(감시·조종), 설치자/정비자, 관리자(장치·네트워크·릴리스) — 역할별 `/console` `/setup` `/device`. 노트북 1366×768, 전화 390×844.
- 사이트 관제자 — Fleet `/console`. 관제 PC 1920×1080, 모바일 390/320.
- 경기 운영자 — Rosy Games 경기 보드 1280×800.
- 원격 운전자 — Pilot 웹 조종 화면과 Android 태블릿 연결 로비.
- 행인·운용자 — 로봇 얼굴 LCD 320×240. 1.5m 거리에서 약 0.5초 판독이 계약이다.
- 카메라 설치자 — Rosy Cam(천장 카메라 Android 폰 앱).
- 학습 검수자 — Rosy Learning(학습 관리 센터). 학습 결과를 찾고 실패 이유를 확인하며 객체 라벨을 수정·명시 승인한다.

## Product Purpose

**목표(2026-10-24 사용자 결정):** ROSY Platform은 업무 앱이 플랫폼 코드를 고치지 않고 로봇(Pinky 주행, OMX 팔)에 작업을 맡기는 범용 실행 플랫폼이다. 첫 적용 사례는 HarborLogi 항만 앱 Harbor다. 플랫폼은 장치 능력·관측(World)·작업 실행과 자원 조정(Fleet)·실행 권한(CORE·device-core)을, 업무 앱은 업무 목표·도메인 모델·정책·화면을 소유하고 버전 고정 공개 계약과 어댑터로만 연결한다.

완료 조건(시뮬 기준, 실물·현장은 DEVICE·FIELD 게이트로 따로 판정):

1. Harbor 첫 흐름이 공개 계약만으로 끝까지 돈다: 회수 전 변경 지시 → 방해 화물 처리 → 목표 운송 → S 하역 → 방해 화물 정리·팔 퇴피.
2. 항만 정책 하나를 바꿔도 이 저장소의 diff가 0이다.
3. 최종 명령은 주행은 CORE, 팔은 OMX owner만 낸다(D-858: device-core 은퇴, 실물 Dynamixel 경로는 owner로 흡수). 실물 owner 조립·수용(D-858 S4·S5)이 끝나기 전까지 owner의 실물 동작은 꺼져 있다.

Pinky 차로 주행과 OMX 집기는 이 목표의 능력 증명 마일스톤이고, Rosy Cell 팔레타이징은 Harbor 흐름에 흡수한다.

ROSY Platform은 ROS 2 Jazzy 기반으로 관측한 세계 상태, 현장 작업 조정, 장치별 안전한 실행, 오프라인 학습·평가를 연결하는 로봇 작업 플랫폼이며 첫 하드웨어는 Pinky Pro다. UI 표면의 일은 사람이 로봇을 안전하게 감시·개입·설치·점검하게 돕는 것이다. 성공 = 운용자·설치자·검수자가 각 표면의 선언 질문에 근거 있게 답하고 다음 안전한 작업을 끝낼 수 있는 것(D-153).

## UI/UX Goal

ROSY의 모든 활성 사용자 표면은 **현대적이고, 쉽게 쓰이며, 정돈되고, 구조가 분명하고, 한 제품처럼 이어져야 한다.** 이는 장식의 양이 아니라 다음 관찰 결과로 판단한다.

- 처음 보는 사용자가 선언된 화면 폭에서 현재 상태, 그 근거, 다음 안전한 행동을 찾는다. 비상 정지와 주된 예외가 화면 밖에 밀리지 않는다.
- 나란한 동등한 창은 같은 너비를 쓰고, 간격·어휘는 공용 규칙을 따른다. 다른 역할의 정보는 표면 문법에 따라 구분한다. 좁은 화면에서는 중요한 순서를 유지하며 가용 폭을 채운다.
- `fresh`·`delayed`·`disconnected`·`unavailable`과 조작의 요청·접수·완료를 혼동하지 않는다. 할 수 없는 조작은 이유와 함께 막는다.
- 모든 활성 표면은 D-153의 G1(기계), G2(선언 상태·뷰포트), G3(근거를 남긴 8항 검토)를 표면별로 통과해야 UI/UX GO다. 새 표면도 D-153의 재평가 트리거에 따라 카드를 만든다. LOCAL 캡처는 장치·현장 수용을 뜻하지 않는다.
- 제품 전체 수용은 모든 활성 표면의 GO와 실제 사용자 작업 검토, 해당되는 실물 폰·태블릿·로봇·사이트 PC의 화면과 상태 readback까지 확인한 뒤에만 선언한다.

## Positioning

현재 World(`operations/world`)는 받은 관측·운영자 pin·odom으로 지금 자세를 만든다. Fleet은 `rosy.world.state.projections.map_pose`를 직접 읽고 작업 원장을 소유한다. CORE와 OMX owner가 각 장치의 실행 경계를 지킨다. 행동 조건부 미래 예측은 후속 계획이다. 층의 그림은 [README 「인지와 판단」](README.md#인지와-판단), 폴더 배치는 [현재 폴더 책임](docs/reference/platform-folder-responsibilities.md)이다.

- 증거 기반 상태 표시: `fresh`/`delayed`/`disconnected`/`unavailable` 4상태를 값마다 구분하고 미확인을 정상으로 그리지 않는다.
- CORE 단일 게이트웨이: 외부 클라이언트는 ROS를 말하지 않는다(CORE SRS §1.3).
- 제품 성격: 차분한 지능에 은은한 따뜻함(D-280).

## Operating Context

- 로봇 AP/현장 LAN. 관제실 모니터, 현장 전화·태블릿, 로봇 LCD는 거리·장갑·조명 조건이 다르므로 각 표면의 선언 뷰포트에서 검토한다.
- 로봇 역할 웹은 프레임워크 없는 정적 UI이며 FastAPI가 in-process로 서빙하고 CSP가 인라인 스타일·스크립트를 금지한다. Cam·Pilot Shell은 Android 네이티브, 로봇 얼굴은 LCD 표시다.

## Capabilities and Constraints

- 닫힌 토큰 집합(`shared/web/tokens.css` 단일 출처), 공유 컴포넌트(`shared/web/ui.js` 커스텀 엘리먼트 16종 + 클래스 부품, 실측 — D-398), 표면 문법 4종(spatial/exception/focal/procedure).
- 시각 체계 안내는 [`DESIGN.md`](DESIGN.md)다(D-359 §8). 계약은 ADR과 시험이 소유하고, 충돌하면 ADR이 이긴다.
- D-220 정지 계약(장식 애니메이션 금지), D-202 색 대비, D-214 텍스트 대비 바닥 4.5:1.
- 토큰·부품·문법의 추가는 ADR 동반만 허용된다(사용자 확인 2026-09-29: 이번 개선 계획에서 ADR 확장 허용).
- UI/UX 판정은 D-153 G1/G2/G3이고 판정 단위는 표면이다. 현재 제품 전체 판정은 HOLD다.

## Brand Commitments

- D-280 다섯 원칙(정직·위계·복잡함의 단순화·작은 온기·정교한 품질).
- ROSY 장미색은 이름 식별에만 쓴다(D-277). 운용자 어휘는 한국어 평문이다.

## Evidence on Hand

- 회차 기록: `docs/validation/uiux-surfaces-*`의 표면별 LOCAL 캡처와 시험 결과. 현재 판정은 각 회차의 증거 셀을 따른다.
- 이 제품 UI/UX 수용에 부족한 것: 모든 활성 표면의 G3 사용자 작업 기록, 선언 G2 상태·폭 전체, 해당 실물 화면과 상태 readback. 기존 기능 DEVICE 시험은 별도 근거다.

## Product Principles

1. 아는 만큼 말한다 — 상태의 출처·신선도·검증 범위를 정확히 드러낸다.
2. 중요한 것이 먼저 보인다 — 안전, 현재 상태, 다음 행동의 순서가 분명하다.
3. 복잡함을 사람이 다룰 수 있게 만든다 — 원인·복구·재확인 단계를 권한에 맞게 준다.
4. 따뜻함은 작은 곳에 둔다 — 운용 화면은 차분하게 유지한다.
5. 현대성은 정교한 품질로 만든다 — 위계·읽힘·여백·일관성으로 다듬는다.
