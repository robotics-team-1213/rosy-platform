# 실제 모델 원장의 독립 보정 입력 Implementation Plan

**Goal:** 실제 저장된 모델 prediction과 별도 검수 자료를 같은 사건·시도·프로파일에 결속해 기존 보정/비교 CLI로 평가한다.

## Source checkpoint

최신 main 통합 commit `70cff59396a5338346ff6c65e3b7a836d99632e0`를 로컬 착지했다. 적격 Model PC 8.1GB의 관련 20개 파일 원격 통합은 569 passed, terminal exit 0, known-failures NEW 0과 lint를 통과했다. 기존 보정/비교/새 feedback CLI·구조·release·관련 운영/도구 회귀를 포함한다. 고정 로그는 세션 `logs/reviewed-feedback-land-70cff59396/run-1.txt`다. 아래 127개는 통합 전 원격 회귀이며 실제 제공자·검수 자료의 진위·운영 성능을 입증하지 않는다. push·배포·현장 수용은 수행하지 않았다.

commit `d9a1424ce0`의 적격 Model PC 8.4GB 원격 관련 6개 파일 시험은 127 passed, terminal exit 0, known-failures NEW 0이다. 실제 SQLite producer→export /1·/2·/3→검수 source binding→기존 보정과 실제 CLI·동일 정답 비교를 포함한다. 로그는 세션 `logs/reviewed-feedback-green-3/run-1.txt`다. 최초 RED 10 NEW는 미구현 경로를 재현했으며 기존 실패 목록에 넣지 않았다. 독립 검토의 domain/text 지원 검증 지적을 수정했고 재봉인된 잘못된 domain/modality 원장과 미검수 추가 시도도 거절한다.

main 통합과 lint·remote·known-failures는 착지 도구로 확인했다. 원본 측정·검수자 인증·실제 모델 품질·현장 운영을 위 source 증거로 승인하지 않으며 외부 고정 hash를 변경하지 않는다.

1. 실제 SQLite producer→model export→검수 행→기존 계산과 CLI를 연결하는 원격 RED를 작성한다. 다른 사건·profile·receipt·확률·누락/UNKNOWN·중복·split 재사용과 위조된 검수 dataset hash를 검사한다.
2. 기존 root 도구의 실행 연결 함수와 `--from-feedback`을 구현한다. 기존 판단 검증과 export 검증을 재사용하며 행에 source binding을 넣고 외부 고정 hash를 유지한다. 정상 무호출을 가짜 model prediction으로 만들지 않는다.
3. 기존 보정/비교 CLI·제공자·설치/구조 회귀와 독립 검토, 적격 PC 원격 시험·known-failures·lint 후 승인된 로컬 병합을 한다.

실제 팀 검수 자료·지연 원본·출처 수용과 모델 성능은 별도다. UNKNOWN과 정상 상태 등 전체 운영 분모는 기존 operational_comparison에서 유지한다. 실제 모델·배포·현장과 개선 승격/복귀는 후속이며 통합 목표는 ACTIVE다.
