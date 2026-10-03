## D-445 Fleet 승격 경로와 중앙 착수 전제

**Status:** Proposed (2026-10-04, 계획 `docs/plans/2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md` §2 R3·R4, 사용자 승인 "권장안 하자". 이 ADR은 승격 경로와 착수 판단의 전제를 정하는 문서 결정이다. 승격 실행·중앙 Fleet 착수는 각각 별도 증거와 별도 ADR이다. 계획 배정표는 D-439/D-440으로 적었으나 착지 시점에 D-439–D-443이 다른 브랜치에 점유돼 있어 D-445로 옮겼다.)

## 배경

- fleet ROS-SIM 게이트의 차단 원인은 D-87(현재 트리 colcon install 부재)이고, D-426(Fleet↔Gazebo 종단 수용, Proposed)이 그것을 푸는 예정 경로다. ARTIFACT·DEVICE·FIELD는 PARKED다.
- API Ref §10.1–10.5의 중앙 Fleet 카탈로그(8081)는 "미구현. 중앙 Fleet 서버가 착수할 때 구현된다"로 명시돼 있고, 착수 시점의 판단 기준은 어디에도 적혀 있지 않다.
- D-437이 사이트 후보의 빌드(GitHub hosted runner)·서명(로컬 오프라인 키) 경로를 결정했지만 첫 실제 workflow 실행은 아직 없다.

## 결정

1. **사이트 시드(fleet)의 승격 경로를 고정한다.**
   - ROS-SIM: D-426 Gazebo 종단 수용을 현재 트리 colcon install로 실행해 통과한다(D-87 해소).
   - ARTIFACT: D-437의 `build-site-candidate.yml` 첫 실제 실행(사용자 승인 push 뒤) → `release.json` 서명(D-301) → 사이트 호스트 검증 통과. 이것이 fleet ARTIFACT의 첫 관측이다.
   - DEVICE: 서명된 사이트 후보를 사이트 PC에 D-437 절차 그대로 설치하고, 실물 2대의 gather·명령·estop 래치(D-421)를 확인한다.
   - FIELD: 위 세 게이트 이후 별도 판정.
2. **중앙 Fleet(8081 카탈로그, API Ref §10.1–10.5) 착수 판단의 전제 3개를 정한다.** ① fleet ROS-SIM·ARTIFACT·DEVICE GO, ② dashboard·pilot ARTIFACT GO(D-444), ③ 서명된 사이트 후보 릴리스 1건 이상. 세 전제가 모두 열리면 착수 여부를 **별도 ADR**로 사용자에게 올린다. 이 ADR은 착수를 승인하지 않고, 전제가 닫혀 있는 동안의 착수 논의를 게이트로 종식한다.
3. **수용됨-미구현 기능의 실행 순서(R4)를 함께 고정한다.** (a) hub listen/FleetAgent WS 전환(D-81 next step)이 먼저, (b) 로봇 셸 `store.js` 공유 WS 구독이 같은 계약 패턴(`/ws/state` 재사용)으로 따른다(폴링 폐지 순서·계약은 착수 시 별도 ADR, D-362 파일 예산 준수), (c) D-368 운전자 MJPEG은 pilot DEVICE GO 뒤, (d) D-361 등록은 사이트 PC 설치 때 로봇 1대를 화면 코드로 등록해 첫 실사용을 만든다.

## 결과

- 중앙 Fleet 착수 여부의 논쟁이 "지금 한다/안 한다"에서 "전제 3개가 열렸는가"로 바뀐다.
- 사이트 시드가 중앙 Fleet의 시행판이 된다. 시드의 승격 증거가 중앙 착수 ADR의 입력이다.
- WS 전환은 새 계약이 아니라 이미 수용된 방향(D-81, D-362의 state socket)의 실행 순서 고정이다.

## 검증

- 호스트: 경로·전제가 이 ADR과 계획 문서에서 일치하는지(절차 문서 수준).
- ROS-SIM: D-426 실행 기록. ARTIFACT: 첫 서명 후보 관측 기록. DEVICE: 사이트 설치 readback과 2대 실기 기록.
- 중앙 착수: 전제 3개의 게이트 상태 인용을 포함한 별도 ADR.

## 잇는 결정

D-81(v1 gather와 다음 단계), D-170·D-297(PRT-004 유보), D-275(표면·영상 소유권), D-290(ROSY Console 명명과 경계), D-301(사이트 후보 서명), D-316(결과 상관), D-362(웹 자산 예산), D-368(운전자 영상), D-361(등록), D-421(estop 래치와 cancel-all), D-426(Fleet↔Gazebo 수용), D-434(모델 PC·관제 PC 역할), D-437(빌드·서명), D-444(웹 표면 게이트), 계획 `2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md`.
