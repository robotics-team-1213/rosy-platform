# OMX 물체 판독·문맥 개선 실행 계획

상태: P0 오프라인 실험 완료, P1의 교육 배치 선정 완료·나머지 미완료. P2 이후 미실행.
설계는 [문맥 설계](2026-10-15-omx-object-context-design.md), 결과는
[20회 실험 기록](../validation/omx-object-context-2026-10-15/result.md)을 따른다.
목표는 **흰 원형 용기의 딸기를 꺼내 놓고 다시 넣기**다. 실물 운용 완료를 뜻하지 않는다.

## P0. 고정 영상에서 실패를 재현한다 — 완료

- [x] 동일 top/front 이미지와 모델 digest 고정, 두 PC 독립 호출·응답 보존.
- [x] 자유 서술→구조화→상대좌표→문맥→decoder schema를 비교.
- [x] 실제 상대 응답 교환 1회씩. JSON 문법·요청 계약·의미 오류를 별도 집계.
- [x] 사용자 용기 확인을 v3로 분리하고 두 PC에서 역할·출처 readback 확인.
- [x] 간단한 색 제안의 오검출과 9영역 임시 참조를 기록. 독립 정답으로 표시하지 않음.

## P1. 과제·시야·정답을 확보한다

**담당:** 작업셀 운영자·독립 검수자. **입력:** 용기 역할은 확인됨.
사용자 위임으로 임시 위치는 흰 용기 오른쪽 위 중앙, top pixel 중심 (330,230),
구역 [290,190,370,270]으로 선정했다. [선정 기록](../validation/omx-strawberry-placement-2026-10-15/result.md).
장면별 교육 배치이며 실제 놓기·도달성·보정은 미확인이다.

1. 딸기 실물/모형·용기 내부/테두리·임시 구역을 실제 영상과 연결한다. 임의 크기/질량은 넣지 않는다.
2. 딸기·용기·임시 구역이 전체 작업 동안 보이는 fresh top/front 시퀀스를 확보한다.
   현장 확인이 어려우면 기존 프레임 분석까지만 하고 카메라를 원격으로 임의 이동하지 않는다.
3. 사람 검수로 객체 정체·완전/경계/가림·inside/outside/unknown을 확정한다.
   빈 용기·딸기 inside/outside·가림·로봇 빨간 부품·예상 밖 물체를 포함한다.

**종료:** 역할·장면 상태를 분리한 과제 카드, 임시 구역, 독립 표식과 불명확 예시가 있다.
현재 2장만으로 시계열 시험 데이터나 과제 성공률을 만들지 않는다.

## P2. 최소 관측 경로를 구현한다

**범위:** 기존 Decision 후보/ObservationSnapshot·situation vision의 schema 호출을 먼저 조사한다.
runtime 경로를 정하기 전에 모듈 AGENTS·D-427/D-516·API reference와 기존 caller/fixture를 대조한다.

1. 제공자 좌표 규약·strict decoder·사후 범위/필드 검사와 거절 사유를 기존 소비자에서 구현한다.
2. 프레임 hash·시각·context revision을 묶고 stale/규약 미지정/필수 필드 누락은 거절한다.
3. 경계 접촉 진단과 원본 모델 출력을 함께 보존한다. 색 제안은 후보로만 사용한다.
4. 실제 새 프레임에서 target association·가림/소실을 시험한다. 모델 PC 재평가는 비동기 오프라인으로 둔다.

**실패 시험:** `[945,]`, 범위 밖·뒤집힌 box, pixel/normalized 혼동, 필드 누락,
문맥 변경/rig 불일치/stale, 빨간 로봇부품으로 identity 전이, 장비를 loose target으로 세기.
원격 RED→최소 구현→GREEN→known_failures NEW 0. frozen 분석 스크립트를 운영 parser로 복사하지 않는다.

## P3. 관측을 왕복 과제 증거와 연결한다

**선행:** P1/P2, 실제 실행은 기존 BENCH/owner/정지·보정 수용 별도.

1. 용기 안/밖·임시 놓기·복귀마다 fresh 증거와 독립 verifier를 정한다.
2. 2D overlap/최종 상태/명령 접수만으로 전체 성공을 만들지 않는 replay 시험을 작성한다.
3. 실패·미판정·개입과 parent cycle을 기록하고 IL split·SIM RL evaluator에 같은 의미를 사용한다.
4. 각 단계 뒤 실제 readback을 확인한다. 처음에는 shadow 관측, 이후 감독된 물리 과제로 나눈다.

**종료:** 완전 cycle과 부분 cycle/순서 뒤바뀜/낙하/가림 사례가 구별된다.
실물 수용 전에도 오프라인 시퀀스 검수는 가능하지만 로봇 성공으로 표시하지 않는다.

## P4. 기존 UI와 운영 루프를 닫는다

1. Fleet Cell/Pilot/episode review의 등록 표면·권한·소유자를 대조하고 context·근거·가림·단계별 outcome을 연결한다.
2. 수정 revision→새 프레임→AI 후보→Fleet 검증→원장 readback을 실제로 확인한다.
   대화 reply receipt와 작업 admission/실행/성공을 각각 표시한다.
3. timeout·GPU 장애·카메라 stale·context 변경 뒤 복구를 검증한다. 관측 실패가 motion으로 이어지지 않아야 한다.
4. 운영자 교대·재촬영·수정·rollback 과제를 실제 브라우저와 장치에서 확인한다.

**완료 기준:** 오프라인 결과, 원격 계약 시험, Fleet 소비, 설치/실행, 독립 물리 왕복 수용을
각각 별도 증거로 남긴다. 현재 P0과 P1의 배치 선정만 완료됐다. 후속 구현은 이 문서만으로 API를 발명하지 않는다.
