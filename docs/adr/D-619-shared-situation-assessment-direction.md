# D-619 공통 상황 판단과 장치별 처리 방향

**Status:** Accepted (2026-10-10, 사용자 요구: 영상 해석 검증·상황 유형화·빠른 처리 방향, 로봇암까지 공통 구조).

## 문제

코너가 보이는 영상에 Qwen이 `lane_lost`만 반복하거나 원형 구간 중앙에 로봇이 있다고 추정했다. 독립 영상 검토에서는 곡선 경계와 연결 바닥이 보이고 원형 구간 중앙은 비어 있었다. 모델 confidence 0.98과 설명 문장만으로 해석의 정확성이나 이동 가능성을 인정할 수 없다. 이동 로봇에 한정한 명령 단어를 공통 상황 모델로 쓰면 로봇암의 대상·파지·공구 상황을 설명할 수 없다.

## 결정

1. `core_common.protocol.situation`에 ROS-free 공통 판단 계약을 둔다. `domain`은 mobility/manipulation, 상황 유형은 `geometry`, `obstruction`, `visibility_limited`, `target_missing`, `target_misaligned`, `resource_conflict`, `action_unconfirmed`, `unknown`이다. geometry는 지금 보이는 구조이며 비교 기준 없이 변화를 확정하지 않는다. 실행 실패·파지 성공은 실제 receipt 없이 확정하지 않는다.
2. 처리 방향은 `hold`, `reobserve`, `recover`, `replan`, `human_review`, `continue`다. 이는 다음 처리의 분류이며 장치 명령·속도·조인트·좌표가 아니다. Fleet이 기존 capability/allowlist/admission에 연결하고 장치 CORE가 최종 재검사한다. 현행 lane-stuck에는 기존 D-577 decision만 사용한다. 로봇암 실제 실행 어댑터는 이번 변경 범위 밖이며 공통 계약이 새 capability를 광고하지 않는다.
3. 관찰은 실제 입력 영상 source와 frame_id에 묶고 불확실한 부분은 별도 목록으로 반환한다. 모델의 `verification`은 항상 `unverified`다. 모델이 verified라고 주장한 응답은 거절한다. 센서 일치·독립 검토·현장 수용은 별도 신뢰된 기록이며 모델 설명에서 생성하지 않는다. 픽셀·오버레이만으로 몸체 통과 가능성, 3D 자세, 파지 성공을 확정하지 않는다.
4. 기존 proposal의 선택 `evidence.assessment`로 추가한다. 기존 응답과 명령 권한을 유지하고 Fleet API 경계에서 같은 계약 validator를 사용한다. 새로운 모델 프롬프트 버전은 기록하고 이전 프롬프트와 평가 결과를 혼동하지 않는다.
5. 신속한 처리는 현재 비동기 단일 모델 작업·1 s Fleet 폴링·2 s heartbeat·6 s 추론 제한을 재사용한다. 로컬 안전 정지는 모델을 기다리지 않는다. 같은 요청은 8 s 재판단 간격, 새 프레임으로 다시 읽는다. deadline/TTL/사례 ID가 바뀌면 기존 규칙으로 돌아가며 늦은 응답이 다음 작업을 승인하지 않는다. 실제 응답 시간을 기록하되 몇 건의 결과로 p95를 주장하지 않는다.
6. 영상 해석 검증은 동일 영상과 모델 출처를 보존한 재생, 센서·지도 대조, 독립 검토, 사람의 정답 라벨을 구분한다. 같은 모델의 재질문을 독립 검증으로 세지 않는다. 실제 모델 결과·계약용 fake 결과·CORE 수락·물리 완료를 각각 보고한다. 기존 incident review/episode/outcome 기록을 재사용한다.

## 상황별 처리 방향

| 상황 | 분류 | 우선 방향 | 장치 실행 전 증거 |
|---|---|---|---|
| 코너·곡선 경계가 보이고 진행 방향 불확실 | geometry | reobserve | 최신 지도·차선 방향·실제 차체 여유 |
| 벽·물체·사람 때문에 경로가 막힌 것으로 보임 | obstruction | hold | CORE 거리·정지·후방/사각 확인 |
| 영상 누락·가림·입력끼리 불일치 | visibility_limited / unknown | reobserve / human_review | 새 영상·센서·독립 검토 |
| 두 로봇 또는 두 작업이 같은 자원을 기다림 | resource_conflict | replan | 현재 자원 소유·trip/Skill admission |
| 로봇암 대상이 보이지 않거나 목표와 어긋남 | target_missing / target_misaligned | reobserve | 대상 식별·보정 frame·허용 Skill |
| 파지·작업 완료를 영상만으로 확인할 수 없음 | action_unconfirmed | hold / human_review | 실제 실행 receipt·그리퍼/힘/대상 상태 |

## 검증

공통 계약의 미지원 유형·허위 검증·잘못된 프레임 연결 거절, 두 도메인의 같은 형식, 기존 proposal 호환성, 실제 VLM 출력과 Fleet API 경계 시험을 원격에서 검증한다. 로봇암 장치 시험이나 자율 코너 통과 성공은 이 계약 시험으로 대체하지 않는다.

**Related:** D-18, D-392, D-430, D-516, D-577, D-610, D-618.
