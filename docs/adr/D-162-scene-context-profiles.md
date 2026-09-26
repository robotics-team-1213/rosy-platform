## D-162 학습된 장면은 설정이지 권한이 아니다 — 장면 상황 프로파일은 등록·리비전·보수 폴백으로만 적용한다

**Date:** 2026-09-22

**Status:** Proposed

**Context:** 카메라가 "학습된 장면"을 통해 일반적으로 처리되려면, 장면마다
다른 인지 파라미터와 장면 상태를 다룰 무언가가 필요하다. D-139가 인지의
자리를 열어두었고 D-151이 도로 인식·정책·명령을 분리했지만, 장면별 프로파일을
어디에 두고 누가 적용하는지에 대한 결정은 없었다. 프로파일을 정책처럼
다루면 관제 권한 모델이 흔들리고, 학습을 디바이스에서 하면 fail-closed
리비전 문화(D-47)와 충돌한다.

**Decision:** 학습된 장면(scene context)은 설정이지 권한이 아니다.

1. 장면은 상황 기반 context id로 정의하고 집합은 닫는다. v0는
   `generic`, `lane_follow`, `stop_line`, `crosswalk`뿐이다. 위치(place)
   기반 장면은 귀환/토폴로지 임무가 생길 때 확장으로 남긴다.
2. 프로파일은 오프라인에서 저작하고 `profile_revision`을 붙여 등록한다.
   디바이스에서 학습하거나 자기 갱신하지 않는다. 등록되지 않은 장면과 알
   수 없는 리비전은 존재하지 않는 것과 같다(fail-closed).
3. 제네릭 보수 프로파일이 기본값이고 매칭 성공은 업그레이드다. 일반화
   (새 사이트 제로샷 포함)는 폴백 품질로 충족하며, 불확실성은 항상
   능력을 줄이는 방향으로만 결합한다.
4. context 전환은 히스테리시스로만 일어나고 인지 파라미터만 바꾼다.
   최종 `cmd_vel`, 정지 판정, mode 전환 권한은 D-2/D-38/D-151 그대로
   CORE와 메트릭 센서가 소유한다. context는 정지·감속의 직접 사유가
   아니다.
5. 신경망 장면 서술자(L1)가 필요해지면 Hailo 게이트(D-29/T5)를 공유한다.
   CPU-only 환경에서 저작 규칙 매칭(L0)만으로 본 결정은 성립한다.

**Alternatives:** 장면별 매개변수를 CORE 정책 테이블로 올려 관제가
선택하는 안은 D-151 supervisory 변경 절차를 매 프레임 분류에 붙여야 하고
CORE→Control 하향 채널을 새로 만들어야 하므로 v0로 거절한다. 디바이스에서
관측을 쌓아 스스로 프로파일을 갱신하는 안은 검증·재현이 불가능해
거절한다. 장면을 위치 기반(VPR)으로 시작하는 안은 재배치에 약하고 데이터
요구가 커서, 상황 기반을 먼저 하기로 한다.

**Consequences:** 장면 프로파일은 D-47/D-48과 같은 리비전 경계 검증을
통과해야 적용되고, 미매칭 시 항상 안전한 기본 동작이 보장된다. 대신
장면별 성능 이득은 프로파일 튜닝 증거(DEVICE gate)가 쌓이기 전까지는
없으며, v0 프로파일 값은 제네릭과 동일하게 둔다. context evidence를
소비하는 CORE 정책 파라미터 테이블은 별도 슬라이스에서 gate를 다시
탄다.

**Validation / Transition:** `src/core/control/test/test_scene_context.py`가
프로파일 경계, store 계약(닫힌 집합·중복 금지·generic 필수·미등록
KeyError), 히스테리시스(진입/이탈 프레임, conflict 동결, 우선순위,
reset)를 고정한다. 이후 순서: road_observer_node wiring과 additive
payload 필드(T3) → CORE translate/traffic_policy 수용(T5) → ROS-SIM →
DEVICE 조명·시간대 유지율 측정 후 D-162를 Accepted로 뒤집는다.

**References:** D-47, D-48, D-137, D-139, D-143, D-151,
`docs/plans/2026-09-22-scene-context-road-design.md`,
`docs/plans/2026-09-22-scene-context-road.md`.

**부분 검증 기록 (2026-09-25, Proposed 유지):** D-162 슬라이스(road_observer_node + scene context)가
2026-09-22 노드 그래프 검증을 통과했다(STATUS 기록). 단 본 ADR의 Accepted 조건(DEVICE 조명·시간대 유지율 측정)은
미충족이므로 뒤집지 않는다.
