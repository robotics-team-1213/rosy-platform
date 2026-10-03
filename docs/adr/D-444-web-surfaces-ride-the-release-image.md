## D-444 웹 표면 게이트는 release 이미지를 탄다

**Status:** Proposed (2026-10-04, 계획 `docs/plans/2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md` §2 R1·R2, 사용자 승인 "권장안 하자". 이 ADR은 관측 절차와 측정 계약을 정하는 문서 결정이다. ARTIFACT 관측·실기 페달 측정은 별도 실행이며 이 ADR만으로 게이트가 움직이지 않는다. 계획 배정표는 D-439/D-440으로 적었으나 착지 시점에 D-439–D-443이 다른 브랜치에 점유돼 있어 D-444로 옮겼다.)

## 배경

- dashboard ARTIFACT 게이트의 차단 원인은 "share/dashboard 설치를 이미지에서 본 기록이 없다"(STATUS.md blockers)다. pilot ARTIFACT도 같은 문제(share/pilot)다.
- pilot DEVICE 게이트의 차단 원인은 "실기 Pinky에서 페달 hold-해제가 실제 정지로 이어지는 확인 전"이다.
- 웹 자산만을 위한 별도 빌드·배포 검증 파이프라인을 만들면, 그 증거가 로봇에 실제로 실리는 서명 release(D-145·D-412·D-437)와 어긋날 수 있다. 로컬 colcon install에서의 브라우저 시험(LOCAL/ROS-SIM)은 이미 통과했고, 남는 구멍은 "제품 이미지 안에 웹 자산이 있는가"와 "실기에서 정지 계약이 지켜지는가"뿐이다.

## 결정

1. **dashboard·pilot의 ARTIFACT GO 증거는 서명 release 산출물 안의 관측이다.** D-437/D-412 경로가 만든 서명 release 이미지(또는 payload) 안에 `share/dashboard`·`share/pilot`가 설치되어 있고, 그 이미지를 탄 기기에서 `GET /dashboard`·`GET /pilot`(역할 화면 `/console` 포함)가 200+CSP 헤더로 응답하는 것으로 한다. 웹 표면을 위한 별도 빌드·배포 파이프라인은 만들지 않는다. 증거는 release receipt와 같은 검증 묶음(`docs/validation/`, D-226)에 남긴다.
2. **pilot DEVICE GO 증거는 실기 정지 계약 측정이다.** 실기 Pinky에서 한 대씩, 사용자 입회 아래: (a) 페달 hold-해제 → `cmd_vel` 0 도달까지의 시간, (b) 운용 화면 e-stop(Esc) → 정지까지의 시간. 각각 최소 5회 측정하고, 합격선은 측정 시작 전에 계량 문서로 먼저 고정한다(기존 teleop stop-latency 측정·D-367 응답 예산 참조). 증거는 `docs/validation/pilot-device-<date>/`에 둔다. 브라우저 시험·호스트 pytest 통과는 이 게이트가 아니다.
3. **dashboard DEVICE 관측은 core/deploy의 device-readback에 얹는다.** Pi bench 설치·`device-readback.sh --json`(STATUS blockers의 core/deploy DEVICE 조건)에 `GET /dashboard` 200이 포함될 때 dashboard의 DEVICE 관측을 시작한다. dashboard를 위해 별도 실기 절차를 만들지 않는다.

## 결과

- 웹 표면의 ARTIFACT 게이트가 release 증거와 한 묶음이 된다. release 이미지가 다시 빌드되지 않는 한 웹 자산의 ARTIFACT GO를 주장할 수 없다.
- pilot 실기 측정은 정지 동작을 포함하므로 사용자 승인·입회가 선행한다(공유 자원 규칙).
- 기존 LOCAL/ROS-SIM 증거(브라우저 suite, Playwright)는 그대로 유효하며 이 ADR이 대체하지 않는다.

## 검증

- 호스트: 이 ADR의 관측 조건이 release 검증 문서·패키지 인벤토리 시험에 반영되었는지. 게이트 자체는 아니라 절차 문서 수준의 검증이다.
- ARTIFACT: 서명 release 안 `share/dashboard`·`share/pilot` 존재 + 기기 응답 200 관측 기록.
- DEVICE: 페달·e-stop 측정 기록(측정 전 고정된 합격선과 함께).

## 잇는 결정

D-23(내장 대시보드), D-75(정적 자산), D-145·D-212(artifact 경로), D-191(장치 준비 매트릭스), D-213(장치→현장 승격), D-323(Pilot PWA), D-367(Pilot 응답 예산), D-412(서명 release 자동 갱신), D-437(빌드·서명 경로), 계획 `2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md`.
