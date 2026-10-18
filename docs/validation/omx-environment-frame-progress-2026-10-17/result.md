# OMX 불규칙 프레임 간격과 fresh 재조회 — 2026-10-17

[환경 v3 실행](../omx-environment-readiness-2026-10-17/result.md) 뒤 실제 암실에서
소스가 fresh인데 환경 모니터는 STALE로 보고하는 경우를 조사했다.12회 실물 읽기에서
top의 같은 stamp/sequence가 여러 poll에 걸쳐 유지되다가 새 sample이 들어왔다.
예를 들어 top seq966의 시각은 여러0.25초 poll 동안 같았고 이후968로 진행했다.
카메라 source 주기와 monitor poll 주기가 같다는 가정이 원인이었다.

## 수정과 검사

`c6c9366d8`은 정확한 stamp·sequence·복사 보존된 원본 품질이 모두 같고 아직 fresh인
재조회를 WAITING_FRAME으로 처리한다. 확인 횟수와 FSM의 pending/epoch/cooldown/budget/
exhaustion은 보존한다. 새 확인·밝기 이력·best 갱신·제어를 추가하지 않으며 READY를
갱신하지 않는다. 실제 stale·역행·누락/상충하는 품질은 확인을 초기화한다.

`4d01a7823`의 반복 간격 통합 시험과 확인 보존 시험에서 RED2건을 확인했다.
중복 identity의 품질이 달라지는 경우도 `2f06c6333`에서 RED를 확인한 뒤 원본 품질을
비교하도록 고쳤다. 최종 관련47개 원격 검사가 실제 Chromium 포함 통과했다.
기존 구조의 `7333e966b`는 별도 원격 가드247개·관련558개 통과(기본 실행에서 browser2개
skip, 별도 opt-in 실행은 통과) 후 로컬 main에 들어갔다. 새 수정의 착지는 그와 구분한다.

독립 source 리뷰는 재조회가 READY나 제어를 갱신하지 않고 실제 stale을 계속 거부함을
확인했으며 남은 material finding을 보고하지 않았다. reviewer는 장치나 pytest를 실행하지 않았다.

## 실제 source 이전

새 source를 별도 immutable 경로에 staging했다. profile bytes와 service unit은 그대로이며,
기존 environment state directory·원본 baseline·rolling budget·환경 이력을 재사용했다.
소유한 tuner를 중지하고 원본 readback 복구를 확인한 뒤 viewer를 중지하고 source 경로만 바꿨다.

첫 이전의 검증 helper는 서비스 시작 직후 observations가 아직 없는 정상 warmup receipt를
배열에 넣은 뒤 role을 직접 조회해 KeyError를 냈다. helper가 이전 source로 자동 원복했으며
실패 receipt와 source를 보존했다. 실제 v3 monitor의 warmup 처리 오류라는 증거는 아니다.
두 번째 helper는 실제 두 fresh 관측이 있는 sample을 검사하도록 고쳐 실행했다.

실제24개 현재 assessment(역할48개) 중 WAITING_FRAME35건, fresh 관측의 false STALE0건을
확인했다. 원본 baseline bytes, 아직 유효한 이전 budget entries, 기존 ledger prefix가 보존됐고
두 새 source service는 active였다. 모두 motion_admitted=False, 실제 시연0회다.
이는 해당 관측 구간의 판정이며 임의 프레임률·무기한 신뢰성 보장이 아니다.

Fleet private `~/rosy-test/omx-camera-environment-c6c9366d8/`에 source hash·동일 profile,
이전 env/budget, 첫 실패/원복 receipt, 두 번째 성공 receipt와24개 assessment를 보존했다.
실제 device identity·raw 영상은 공개하지 않는다. 강조도 현장 수용, episode/학습 manifest
binding, 환경 저하와 수집 owner stop 결선, 첫 실제 시연 데이터는 계속 미완료다.
