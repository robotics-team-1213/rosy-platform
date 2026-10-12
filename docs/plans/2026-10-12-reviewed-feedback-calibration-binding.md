# 실제 모델 원장의 독립 보정 입력 Implementation Plan

**Goal:** 실제 저장된 모델 prediction과 별도 검수 자료를 같은 사건·시도·프로파일에 결속해 기존 보정/비교 CLI로 평가한다.

1. 실제 SQLite producer→model export→검수 행→기존 계산과 CLI를 연결하는 원격 RED를 작성한다. 다른 사건·profile·receipt·확률·누락/UNKNOWN·중복·split 재사용과 위조된 검수 dataset hash를 검사한다.
2. 기존 root 도구의 실행 연결 함수와 `--from-feedback`을 구현한다. 기존 판단 검증과 export 검증을 재사용하며 행에 source binding을 넣고 외부 고정 hash를 유지한다. 정상 무호출을 가짜 model prediction으로 만들지 않는다.
3. 기존 보정/비교 CLI·제공자·설치/구조 회귀와 독립 검토, 적격 PC 원격 시험·known-failures·lint 후 승인된 로컬 병합을 한다.

실제 팀 검수 자료·지연 원본·출처 수용과 모델 성능은 별도다. UNKNOWN과 정상 상태 등 전체 운영 분모는 기존 operational_comparison에서 유지한다. 실제 모델·배포·현장과 개선 승격/복귀는 후속이며 통합 목표는 ACTIVE다.
