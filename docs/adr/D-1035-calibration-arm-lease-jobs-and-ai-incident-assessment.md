## D-1035 셀 팔은 리스 하나로 점유하고, 보정은 Calibration 앱의 작업으로 요청하며, 팔 incident는 AI 판정 기록으로 해제한다

**Status:** Accepted (2026-11-17, 사용자 결정: "사람 해제가 필요없는게 이제 파이프라인으로 ai 가 확인해서 상황판단해서 처리하기로 했어", "ui ux 로도 calibration … 아니면 api 나 기타로라도", "바로 파이프라인을 완성시켜줄래"; 구현·원격 시험의 수용이며 관제 PC 배포·실물 수용은 별도)

**관련:** D-951(Calibration 앱) · D-1004(Account, `calibration.operate`) · D-911(감독 시험) · D-932(현장은 착지한 main) · D-971(팔 incident와 hold) — 이 기록이 D-971의 "해제는 Fleet에서 사람이"를 고친다.

## Context

2026-11-16 밤~11-17 새벽 같은 셀에서 두 주체가 서로 보이지 않게 팔을 움직였다.
- 한쪽은 이 노트북의 세션, 다른 쪽은 다른 기기에서 Tailscale SSH로 들어온 작업이었다.
- 다른 쪽의 `human-hold`·`stop`이 이 세션의 arm_b 세션을 끊었고, 공용 설치본(`omx-tools-current`)이 두 번 바뀌었다.
- 셀 PC 안의 파일 잠금(`session_lock(arm)`)은 한 세션 동안만 잡혀 세션 사이 점유를 드러내지 않는다.
- 보정 단계(지도 정합, 기준점, 깊이 검증)는 즉석 SSH 명령으로 돌았고, 착지하지 않은 코드가 현장에서 돌았다(D-932 위반, 양쪽 모두).

## Decision

1. **팔 리스.** 팔마다 리스 하나를 둔다(`deploy/robot/omx/cell_arm_lease.py`, 셀 PC 상태 폴더). 리스는 주인(owner), 목적, 만료, 리비전을 적는다.
   - `record_session`은 세션 잠금 직후 리스를 잡는다. 다른 주인의 살아 있는 리스가 있으면 팔을 열지 않고 주인·목적·만료를 말하며 거절한다.
   - 주인은 `ROSY_ARM_LEASE_OWNER`이고, 없으면 사용자·접속지에서 만든다. 같은 주인은 갱신한다.
   - 만료가 지났거나 세션 프로세스가 죽은 리스는 살아 있지 않다.
2. **보정 작업 API.** Calibration 앱이 상태판과 작업을 낸다.
   - `GET /api/calibration/status`: 팔별 리스, incident, 설치 리비전, 자리별 지도(LOO·점수·지문)·바이어스·면 높이.
   - `POST /api/calibration/jobs`: 허용 단계(`check`, `depth-verify`, `pivot-near`, `rebase`, `remap`)만 받는다. `calibration.operate` 세션과 같은 출처가 필요하다. 팔을 움직이는 단계는 요청에 감독 확인(D-911)이 있어야 하고, 앱이 리스를 잡은 뒤 셀 엔진을 돌린다. 결과·로그·리비전을 작업 기록으로 남긴다.
   - 앱은 셀 값을 손으로 쓰지 않는다(D-951 2항). 실행은 엔진(`cell_calibrate.py`)이다.
3. **AI incident 판정.** 팔 incident 해제는 사람 대신 AI 판정 기록으로 한다.
   - 판정은 증거(카메라 프레임 해시, 관절 상태, 토크)를 함께 남긴다(`POST /api/calibration/assessments`).
   - 해제(`POST /api/calibration/incidents/<arm>/clear`)는 10분 안의 `clear` 판정이 있고, 측정 조건이 먼저 통과할 때만 한다: 그 팔에 세션이 없고, 다른 주인의 리스가 없다.
   - 측정이 거부권을 쥔다. 모델 판정은 측정이 남긴 경우에만 해제한다.
4. **착지 리비전.** 작업 기록은 실행한 설치 리비전을 적는다. 착지 확인의 강제는 배포 경로(`omx_autoupdate`)의 몫이며 이 결정 범위 밖이다.

## Consequences

- 다른 기기의 SSH 작업도 `record_session`을 거치는 한 리스에서 막히고, 누가 쓰는지 보인다.
- 보정 단계를 화면·API로 요청하고 결과를 한곳에서 본다. 즉석 SSH 보정은 리스를 지키는 한에서만 남는다.
- D-971의 사람 해제는 AI 판정 기록으로 바뀐다. 판정과 근거가 남지 않은 해제는 하지 않는다.
- 관제 PC 배포·HTTPS·Account 권한 부여는 D-1004 순서를 따른다.
