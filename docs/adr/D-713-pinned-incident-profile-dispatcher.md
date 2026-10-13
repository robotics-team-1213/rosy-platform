# D-713 기존 Fleet runtime의 pinned 모델 worker 분배

**Status:** Accepted (2026-10-12, source contract)

기존 install_incident_runtime이 opt-in `profile_workers` 설정에서 같은 사건 store·board·관측·사람 인수 연결을 사용하는 최대 8개 고정 프로파일 worker와 단일 dispatcher를 구성한다. 기존 flat config와 기본 미활성 동작은 유지한다. 각 worker의 admission/current_profiles/보정 검증은 바꾸지 않고 routed 새 사건은 D-712의 원자적 선택 일치가 필수다. shared clock은 runtime 구성에서 지정하며 worker별 시계 변경은 거절한다.

dispatcher는 기존 Fleet loop의 feed/aclose와 기존 outbox receipt 준비 슬롯 하나를 소유한다. active·인수 대기 사건의 고정 profile worker와 현재 선택의 worker에 해당 로봇의 공개 CORE 상태만 분배한다. 새 사건 생성의 최종 선택 확인은 같은 DB 트랜잭션에서 수행한다. receipt 준비는 같은 트랜잭션에서 기존 case의 scope 또는 현재 선택에 맞는 worker 하나로만 보낸다. current가 설치되지 않았으면 새 사건의 모델 호출을 하지 않는다. 기존 사건·예산·UNKNOWN은 다른 worker에 넘기거나 초기화하지 않는다.

DB 읽기는 poll event-loop 밖에서 수행하고 최종 종료는 모든 worker의 기존 취소/UNKNOWN 처리 완료를 기다린다. 선택·설치 목록은 모델 품질 수용이 아니다. signed 운영 수용·실제 설치 trust·현장 결과와 부족한 coverage는 별도 검증한다. 새 서비스·CORE publisher·외부 API는 추가하지 않는다.
