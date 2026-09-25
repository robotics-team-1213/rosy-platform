# 디자인 시스템 롤아웃 설계 — D-233을 ADR로 나눠 하나씩 처리한다

**Date:** 2026-09-25
**Status:** Proposed (설계). 이 파일은 실행 근거가 아니라 작업 순서의 초안이다.
**Parent:** [D-233](../adr/D-233-design-system-component-token-draft.md) (Proposed)

## 1. 목표

D-233 초안의 인벤토리를 ADR 단위로 나눠, 한 번에 하나씩만 Accepted로 올린다.
한 ADR은 한 컴포넌트(또는 한 묶음) + 그 게이트만 다룬다. 병렬 추진 금지 —
어휘·토큰 drift는 동시 커밋에서 나온다(D-130 Context).

## 2. 비목표

* 새 L1 어휘를 이 계획에서 직접 추가하지 않는다. 추가는 각 ADR의 결정이다.
* 확인 모달 신설 없음(D-218 졸업 유지). 게임·진단의 권한 체계 개편 없음
  (관전 readonly, 진단 격리는 각 ADR에서 다룸).
* `src/hmi/web` 밖에 새 공유 패키지를 만들지 않는다(D-157, D-231, D-242).

## 3. ADR 분할 (순서대로)

| 순 | ADR(예정) | 범위 | 왜 이 순서인가 |
|---|---|---|---|
| 1 | D-245 EStopBlock 문구 통일 파일럿 | 4벌 E-Stop의 문구·kind·확인 횟수를 하나로, 마크업은 각 표면에 둠 | 가장 작고, D-218 PINNED_CONFIRMS 표 갱신으로 프로세스(어휘+게이트+회차)를 한 바퀴 증명한다 |
| 2 | D-248 AuthBar | CORE auth-drawer + Fleet tokenbar의 상태머신 통합, 저장소 규칙(D-193 6)은 유지 | E-Stop 다음으로 중복이 크고, 역할 행렬의 전제다 |
| 3 | D-249 FieldMap | 레이어 툴바·legend·empty·적합 계약 통합. 래스터 팔레트는 PNG 파이프라인과 함께 동결 | 지도 3벌 중 가장 drift 위험이 큼. D-201 적합 게이트의 소유자를 정한다 |
| 4 | D-250 TeleopPad + L2 TeleopHold | hold-to-drive 100ms를 headless로 1회, 시각은 표면 소유 | 첫 L2 headless. D-130.2 자격(로직 + 2표면)의 선례가 된다 |
| 5 | D-251 HostCard / SettingsFormRow | 점검뷰 host 카드 3종 + 설정 카드 8종의 폼 행·메시지·`bindFormSave` 통합 | 절차 문법의 반복을 줄임. D-201 "편집은 절차로"의 그릇을 만든다 |
| 6 | D-252 Fleet 큐·대형 (P2) | QueuesPanel을 `ui-triage` 위로, FormationForm 슬롯 미리보기 | Fleet은 예외 문법이라 CORE와 합치지 않고 Fleet 안에서만 통합 |
| 7 | D-253 게임·진단 마무리 (P3·P4) | 게임 관전 readonly + ScoreBoard, 진단 토큰 합치 + 기능 동결 선언 | 영향 최소. 마지막에 처리해도 drift가 안 번진다 |

(번호 근거: D-245는 이 파일럿, D-246은 런타임 유연성이다. D-244는 빈 번호다. D-247은 장치 관측 초안이 같은 날에 잡았다.)

D-245가 Accepted되기 전까지 D-248 이후는 설계만 있고 코드를 건드리지 않는다.
각 ADR은 Proposed로 올리고, 파일럿(D-245) 결과로 D-233 본문을 amendment한다.

## 4. 각 ADR의 공통 출구 기준

1. 어휘 표 + `styleguide.html` + 게이트 시험을 같은 커밋에 동반 (D-233 결정 5의
   Consequences 선행 적용).
2. D-153 G1(기계 게이트 전체 녹색) + G2(선언 뷰포트 캡처, `docs/validation/uiux-surfaces-<date>/`).
3. D-201 적합 3항(문서 스크롤 없음·분쇄 없음·안전조작 가시성) 실측.
4. D-218 대화상자 계약(`test/test_web_dialog_contract.py`) 녹색 유지.
5. `src/hmi/web/test` + 해당 표면 시험 녹색.

## 5. 실행 순서 (하나씩)

1. D-245 Proposed 작성 → 리뷰 → 파일럿 커밋 → 회차 캡처 → Accepted.
2. D-245 회고로 D-233 amendment (틀린 인벤토리·순서 수정).
3. D-248 → … → D-253 동일 반복. 한 번에 open된 Proposed ADR은 최대 1건.
4. 전부 끝나면 D-233을 Accepted로 승격(또는 후속 통합 ADR).

## 6. 위험

* R1: 파일럿에서 L1/L2 경계가 흔들리면 — D-234 안에서 경계를 다시 긋고 D-233을
  고친다. 뒤 ADR에 drift를 넘기지 않는다.
* R2: Fleet/게임의 뷰포트 캡처 수단이 없으면 — 해당 ADR은 HOLD로 두고 앞 ADR과
  묶지 않는다(D-153: 찍지 못한 상태는 평가되지 않은 것이다).
* R3: 토큰 변경 유혹 — 이 계획 안에서는 토큰 값을 바꾸지 않는다. 필요하면 별도
  ADR로 분리하고 전 표면 회차를 연다.

## References

D-92, D-129, D-130, D-153, D-157, D-194, D-195, D-201, D-218, D-233,
`src/hmi/web_common/template.html`, `docs/validation/` (회차 폴더).
