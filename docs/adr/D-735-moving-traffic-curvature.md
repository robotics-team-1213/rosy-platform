## D-735 이동 후보의 교통 감속은 곡률을 보존하고 제자리 회전은 유지한다

**Status:** Accepted (2026-10-12, SOURCE 계약). 사용자 지도 완주 수정 권한과 독립 재생 검토에 근거한다. 제품 구현·원격 회귀·Gazebo·실물 수용은 별도 증거다.

## 배경

기존 ENFORCED는 이동 후보를 `(s*v,w)`로 감속하여 곡률을 `k/s`로 바꾼다. Leg6 원본 맵 실행에서 APPROACH 48개 관측은 첫 페인트 겹침보다 먼저 발생했다. 같은 위치·같은 명령 값의 정적 재생에서 sim37.209의 `s=0.4873688`, 후보 곡률 `3.7833`은 최종 `7.7627`이 됐다. 동일 이동 거리 12cm를 2mm raster로 비교하면 후보는 8.8cm 뒤, 최종 호는 0.4cm 뒤 처음 페인트와 겹쳤다. 원래 후보도 더 전진하면 겹치므로 감속을 유일 원인으로 주장하지 않는다. 가까운 수신 시각과 값 일치는 소비 프레임 증명이 아니다.

근거는 [기존 교통 곡률 연구](../plans/2026-10-12-traffic-speed-curvature-research.md), [구현 설계](../plans/2026-10-12-moving-traffic-curvature-design.md), 관리된 X 세션의 `evidence/leg6-static-traffic-replay.json`이다. 연구의 Nav2 공식 문헌은 기하 곡률과 속도 규제 분리 원칙을 설명하며 ROSY의 실물 수용을 대신하지 않는다.

## 결정

1. 공유 TrafficPolicyManager의 ENFORCED FOLLOW/APPROACH/PROCEED에서 `v != 0`이면 `(s*v,s*w)`를 반환한다. 직진과 음의 선속도도 같은 비율을 적용한다.
2. `v == 0`이면 제자리 회전의 기존 `w`를 유지한다. timed turn의 각속도·시간 계약을 바꾸지 않는다. zero는 zero다.
3. DISABLED/MONITOR_ONLY는 후보를 바꾸지 않고, HOLD·stale·충돌·map/scene/revision 거절은 기존 zero를 유지한다. 새 옵션·필드·모드·threshold는 없다.
4. 기존 clip·current revision 검사·issued trail·CommandManager의 최종 곡률 보존과 CORE 최종 명령 권한을 유지한다. static profile clip 이후의 판정된 호를 보존하며 그 이전의 독립 축 clip 의미는 바꾸지 않는다.
5. D-422의 ENFORCED 이동 감속이 선속도만 줄인다는 부분을 이 결정으로 대체한다. D-422 본문은 기록으로 보존한다. 기존 tighter-arc family 쓸기는 원래 호를 포함하는 보수적 상위 집합으로 남기고 제거하거나 clearance를 완화하지 않는다.

## 수용 경계

TDD 원격 계약과 독립 SOURCE 검토 뒤에도 벽 STOP 오탐, 관측 중심과 목표 호의 차이, 계획 cap 전달, 실제 Gazebo 완주·실물 주행은 별도 문제다. 같은 후보와 실제 traffic scale, 최종 명령·몸 경계를 후속 실행에서 읽어야 한다.
