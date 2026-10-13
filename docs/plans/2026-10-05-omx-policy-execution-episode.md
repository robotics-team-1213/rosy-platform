# OMX 동일 실행 Episode와 Fleet 결과 연결

Root 단독 writer, `feat/omx-policy-episode`. D-449 Proposed 계약의 별도 실행 profile을 구현한다. 시연 recorder와 DatasetStore/승격의 시연 profile 허용은 유지한다.

기존 parent capability에서 실제 ActionAPI v2 receipt와 이미 존재하는 SQLite journal singleton을 검증한다. parent/events/phases/identity 단일 BEGIN과 source/native 재읽기, 저장 I/O 이후 최종 TTL 검사를 수행한다. 원본 lease/intent/callback/설치 바이트/receipt를 새 Episode에 보존한다.

관측 stream은 metadata로 명시하고 raw RGB와 모델 추론은 unknown/false, Episode incomplete/task unknown을 유지한다. Fleet export는 전체 원본 tuple/journal 및 같은 native goal을 대조한다. 파일 해시는 receipt 인증·새 실행 권한이 아니다. 새로운 PICK_PLACE/CELL_TRANSFER 동작을 추가하지 않는다.

TDD 신규 producer 부재 RED 후 합성 driver/model HOST에서 actual runner/SQLite/ActionAPI/native callback→Episode→Fleet export를 검증한다. 누락·타 owner·reseal tuple/goal/source·만료·발행 중 변경·중복 output 거절, known_failures와 독립 검토 후 local ff/no push. native50ms/500ms/inference/task/device 및 실제 이동 수용은 별도 미완료. 전체 이동0.20m across all robots/attempts/coast/no reset; 이번 작업 motion 없음.
