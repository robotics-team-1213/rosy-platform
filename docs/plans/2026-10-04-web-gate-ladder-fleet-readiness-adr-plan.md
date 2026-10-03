# 웹 게이트 사다리와 Fleet 승격 ADR 계획

**Status:** PLAN rev 1 (2026-10-04). 문서만이다. 기준은 로컬 `main` `5d521e6b0`(D-438 착지)과 그 시점 `STATUS.md`다.

**목적:** 앱·웹 표면의 HOLD 게이트를 하나의 사다리로 풀고, 그 위에서 Fleet(사이트 시드 → 중앙 착수 판단)과 수용됨-미구현 기능(D-368·D-361·WS 전환)의 실행 순서를 고정한다. 새 ADR 배정(D-439, D-440)을 포함하지만, 이 문서만으로는 어떤 ADR도 확정하지 않는다.

## 0. 경고 — 시작 전 필수

**2026-10-04 체크포인트:** P0(트리 정렬) 완료 — main이 origin/main을 merge(ahead 48, behind 0), lint 0 errors, 계약 시험 통과. D-444·D-445 착지와 함께 D-439–D-443 브랜치 점유를 adr_gaps에 선언했다. 아래 1·2항은 역사 기록으로 남긴다.

1. **로컬 `main`과 `origin/main`이 갈라져 있다** (ahead 45 / behind 91, 2026-10-04 기준 작성 시점). origin에만 있는 D-433·D-436·D-437 ADR과 PR #43 등이 로컬에 없고, 로컬의 D-438은 origin에 없다. 이 계획의 모든 착지는 먼저 fetch → rebase(또는 사용자가 정한 정렬)로 트리를 하나로 만든 뒤다. ADR 번호도 착지 직전에 ADR Log에서 다시 확인한다(`docs/adr/AGENTS.md` 규칙).
2. **D-427 소스 이동이 진행 중이다.** origin의 [`2026-10-04-d427-post-migration-follow-ups.md`](2026-10-04-d427-post-migration-follow-ups.md) P1(이동 마무리·동등성 증거·다음 release 배포)이 이 계획의 1단계 입력이다. 이 계획은 그 문서와 경쟁하지 않고, 그 위에 웹 표면 게이트를 얹는다. 경로는 이 문서에서 모듈 이름(dashboard, pilot, fleet)으로 부르고, 착지 시점의 실제 경로를 따른다.
3. **실물 로봇·사이트 PC는 공유 자원이다.** 동작을 일으키는 모든 단계(페달 측정, release 설치, 사이트 배포)는 사용자 승인 뒤에만 한다.

## 1. 배경 — 게이트 지도 (2026-10-04 기준)

| 표면 | 막힌 게이트 | 차단 원인 (`STATUS.md` blockers) |
|---|---|---|
| dashboard | ARTIFACT | `share/dashboard` 설치를 이미지에서 본 기록이 없다 |
| pilot | LOCAL(일부)·ROS-SIM(일부)·ARTIFACT·DEVICE | 전체 Pinky 경로 재측정, `share/pilot` 이미지 관측 없음, 실기 페달 hold-해제→정지 미확인 |
| fleet | ROS-SIM | D-87: 현재 트리 colcon install 부재 → D-426(Fleet↔Gazebo 종단 수용, Proposed)이 푼다 |
| fleet | ARTIFACT·DEVICE·FIELD | PARKED — 사이트 후보 빌드·서명(D-437/D-301) 첫 실행과 사이트 PC 설치가 아직 없다 |
| core/deploy | ARTIFACT·DEVICE | 서명 manifest·immutable digest 미발행, Pi bench 설치·`device-readback.sh --json` 증거 없음 |
| 제품 전체 UI/UX | HOLD (D-153) | 사람 G3 평가 기록, 실물 LCD 사진·현장 관측, 실물 readback 없음 |

같은 막힘이 세 겹으로 겹친다: **① 서명 릴리스 기계(core/deploy ARTIFACT) → ② 이미지 안 웹 자산 관측(dashboard/pilot ARTIFACT) → ③ 실기 증거(pilot DEVICE, core DEVICE)**. ①과 ②는 한 release 사이클에서 같은 산출물로 해결되고, ③은 그 이미지를 탄 로봇에서만 가능하다. 이것이 사다리다.

## 2. 결정 원칙 (새 ADR이 고정할 것)

- **R1 — 웹 표면 ARTIFACT는 release 이미지 관측이다.** 별도 웹 빌드·배포 파이프라인을 만들지 않는다. dashboard/pilot의 ARTIFACT GO 조건은 "D-437/D-412 경로로 만든 서명 release 이미지(또는 payload) 안에 `share/dashboard`·`share/pilot`가 설치되어 있고, 그 이미지를 탄 기기에서 `GET /dashboard`·`GET /pilot`가 200"이다. 증거는 release receipt와 같은 묶음에 남긴다.
- **R2 — pilot DEVICE는 정지 계약 측정이다.** 실기 Pinky에서 (a) 페달 hold-해제 → `cmd_vel` 0 도달(운용 화면 e-stop Esc와 함께, D-367 응답 예산 안에서), (b) 카메라·명령 루프가 살아 있는 상태의 연속 조종 왕복. 측정 절차·합격선은 계량 문서로 남기고 `docs/validation/pilot-device-<date>/`에 증거를 둔다. 브라우저 시험 통과는 이 게이트가 아니다.
- **R3 — Fleet은 시드에서 중앙으로, 게이트가 연다.** 사이트 시드의 승격 경로(ROS-SIM D-426 → ARTIFACT D-437 첫 실행·D-301 서명 → DEVICE 사이트 PC 설치·2대 실기 → FIELD)를 고정하고, **중앙 Fleet(8081 카탈로그, API Ref §10.1–10.5) 착수는 별도 ADR의 결정 사항**으로 둔다. 이 계획은 착수 판단의 전제 조건만 정의한다.
- **R4 — 폴링에서 WS로의 전환은 순서가 있는 마이그레이션이다.** 로봇 셸 `store.js`(polling-only)와 Fleet v1 gather(REST 폴링, D-81)의 WS 전환은 이미 방향이 수용된 결정이다. 새 계약을 만들지 않고, 실행 순서(로봇 셸 → hub listen/FleetAgent)만 이 계획이 정한다.

## 3. 사다리 — 단계와 출구

### P0. 트리 정렬 (모든 것의 선행)

- 역할: 사용자(+release). 크기: M.
- 할 일: fetch → origin/main과 로컬 main 정렬(rebase 권장, D-438 포함 45 커밋). origin의 d427-followups P1-1~P1-3 상태를 확인해 이 계획 1단계의 입력으로 삼는다.
- 출구: `python tools/harness/rosy_harness.py lint` 0 errors, `main`과 `origin/main`의 ADR 목록이 하나다. D-439 이상 번호가 origin에서 이미 쓰였으면 이 계획의 배정표를 그때 고친다.

### P1. ARTIFACT 관측 (dashboard·pilot·fleet 한 묶음)

- 역할: release(+executor). 크기: M. 선행: P0, 그리고 d427-followups P1-2(동등성 증거)와 같은 release.
- 할 일:
  1. d427-followups P1-7의 "다음 정규 release"에 웹 자산 관측을 얹는다: 이미지/패키지 인벤토리에 `share/dashboard`, `share/pilot` 존재 확인(설치 스크립트·`ros2 pkg prefix` 목록).
  2. 그 이미지를 탄 벤치(Pi 또는 colcon overlay 부팅)에서 `GET /dashboard`, `GET /pilot`, `GET /console` 200 + CSP 헤더 확인.
  3. Fleet 사이트 후보: D-437의 `build-site-candidate.yml` 첫 실제 실행(사용자 승인 push 뒤 `gh workflow run`) → release.json 서명 → 사이트 호스트 검증 통과. 이것이 fleet ARTIFACT의 첫 관측이다.
- 출구: dashboard ARTIFACT GO, pilot ARTIFACT GO, fleet ARTIFACT 최초 관측 기록. 증거 `docs/validation/`에 release receipt와 함께.

### P2. DEVICE 증거 (pilot 정지 계약, core/deploy readback)

- 역할: operator(사용자 입회) + verifier. 크기: M~L. safety: 측정은 정지 동작을 포함하므로 사용자 승인·입회 필수.
- 할 일:
  1. **pilot 페달 계약(R2)**: 실기 Pinky, 한 대씩. 페달 hold-해제→정지 시간 측정(최소 5회, 기록: 명령 시각→`cmd_vel` 0→차체 정지), 화면 e-stop Esc 동일 측정. 합격선은 측정 전 계량 문서로 먼저 고정(제안: 기존 teleop stop-latency 예산 참조).
  2. core/deploy DEVICE: Pi bench 설치 + `device-readback.sh --json` (STATUS blockers의 원문 조건). dashboard는 이 readback에 `/dashboard` 200이 포함되면 같은 증거로 DEVICE 관측을 시작한다.
  3. UI/UX G3 사람 평가(d427-followups와 별개, `2026-09-29-uiux-craft-improvement-plan.md`의 프로토콜): 실물 LCD 사진·현장 관측 자료 수집 — 로봇이 벤치에 있을 때 같이 한다.
- 출구: pilot DEVICE GO(페달 계약), dashboard/pilot DEVICE 최초 관측, D-153 HOLD 해제 재료.

### P3. Fleet 승격 (ROS-SIM → DEVICE → 중앙 착수 판단)

- 역할: executor + verifier + 사용자(착수 판단). 크기: L. 선행: P1 3(fleet ARTIFACT 관측).
- 할 일:
  1. **ROS-SIM**: D-426 Gazebo 종단 수용을 현재 트리 colcon install로 실행 → fleet ROS-SIM GO (D-87 해소).
  2. **DEVICE**: 서명된 사이트 후보를 사이트 PC에 설치(D-437 절차 그대로), 실물 2대 gather·명령·estop 래치(D-421) 확인.
  3. **중앙 Fleet 착수 조건 확인**: ① fleet ROS-SIM·ARTIFACT·DEVICE GO, ② dashboard/pilot ARTIFACT GO, ③ 사이트 후보 서명 릴리스 1건 이상 — 세 조건이 모두 열리면 중앙 Fleet(8081) 착수 여부를 **별도 ADR**(D-440이 조건을 정의, 착수 자체는 그때의 새 ADR)로 사용자에게 올린다.
- 출구: fleet ROS-SIM/DEVICE GO, 중앙 착수 판단 요청 기록.

### P4. 수용됨-미구현 기능 (기타)

순서대로, 각각 이미 수용된 ADR의 실행이다. 새 ADR은 하나만 후보다.

1. **hub listen/FleetAgent WS 전환**(D-81 next step, R4): P3-2 뒤. gather 폴링을 hub WS로 바꾸고 콘솔은 같은 스냅샷 계약을 유지.
2. **로봇 셸 `store.js` 공유 WS 구독**(R4): hub 전환과 같은 계약 패턴(`/ws/state` 재사용). 후보 ADR "웹 표면 실시간 구독 통일"(폴링 폐지 순서·계약) — 착수 시 번호 배정, D-362 파일 예산 준수.
3. **D-368 운전자 MJPEG 라이브 영상**: pilot DEVICE GO 뒤(실기 페달 계약이 우선).
4. **D-361 등록(enrollment) 실사용**: P3-2 사이트 PC 설치 때 로봇 1대를 화면 코드로 등록해 첫 D-361 로봇을 만든다.
5. **D-247·D-260 승격 판정**(Proposed): P2-3 현장 관측 자료로 수용/유보를 사용자에게 올린다.

## 4. 새 ADR 배정표 (착지 시점에 확정)

| 배정 | 제목(초안) | 고정하는 것 | 상태 |
|---|---|---|---|
| **D-444** | 웹 표면 게이트는 release 이미지를 탄다 | R1+R2: dashboard/pilot ARTIFACT 관측 조건, pilot DEVICE 페달 정지 계약·측정 절차·합격선, 증거 위치 | **착지 완료 (2026-10-04, Proposed)** — `docs/adr/D-444-web-surfaces-ride-the-release-image.md`. 계획 배정표의 D-439는 착지 시점에 다른 브랜치가 점유해 재번호 |
| **D-445** | Fleet 승격 경로와 중앙 착수 전제 | R3: 사이트 시드 승격 경로(ROS-SIM→ARTIFACT→DEVICE→FIELD), 중앙 Fleet 착수의 3전제, 착수 자체는 별도 ADR | **착지 완료 (2026-10-04, Proposed)** — `docs/adr/D-445-fleet-promotion-path-and-central-start-preconditions.md`. 계획 배정표의 D-440은 재번호 |
| (번호 미배정) | 웹 표면 실시간 구독 통일 | R4 실행 계약: 폴링 폐지 순서, `store.js`·gather의 WS 전환 | P4-2 착수 시 배정 |

두 ADR 모두 착지 전에 §0-1의 번호 재확인을 한다. 이 계획 문서가 먼저 사용자 승인을 받는다.

## 5. 검증

- 이 계획 자체: `python tools/harness/rosy_harness.py lint`, `python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q`.
- 각 단계의 증거는 `docs/validation/<topic>-<date>/`(D-226). 호스트 pytest 통과는 장치·현장 수용이 아니다.
- 게이트가 움직일 때마다 해당 모듈 `progress.md` 갱신 → `rosy_harness.py generate`.

## 6. 완료 정의

- P1: dashboard·pilot ARTIFACT GO, fleet 후보 첫 서명 릴리스 관측.
- P2: pilot DEVICE GO(페달 계약), core/deploy DEVICE readback 증거, G3 재료 확보.
- P3: fleet ROS-SIM/DEVICE GO, 중앙 착수 판정 요청.
- P4: WS 전환 2건, D-368·D-368·D-361 실행, D-247/D-260 판정.
- 이 계획의 완료가 FIELD 수용을 뜻하지 않는다.

## 7. 열린 질문

1. P0 정렬 방식(rebase 권장)과 D-438의 upstream 반영 순서 — 사용자 결정.
2. pilot 페달 정지 합격선의 수치(기존 teleop stop-latency 측정값 참조) — P2 착수 전 계량 문서로.
3. P4-2 후보 ADR의 번호는 착수 시 배정(이 계획이 예약하지 않는다).
