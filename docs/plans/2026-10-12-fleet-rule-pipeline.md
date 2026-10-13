# Fleet 통합 규칙집과 실행 파이프라인

**Goal:** 기존 Fleet 자동 대응을 law → rule/AI 후보 → 실행 전 재검사 → CORE → readback 순서로 연결하고 같은 규칙집에서 추적한다.

**Architecture:** 기존 stuck resolver, AI-first, outcome, Task/Mission admission을 재사용한다. 자동 대응의 공통 law와 후보 선택을 `fleet.stuck.pipeline`으로 모으며 stuck와 stalled/pose_lost의 전송 직전 같은 law를 검사한다. 외부 API·명령·설정 형식과 CORE 권한은 유지한다.

**Tech Stack:** Python 표준 라이브러리, 기존 Fleet pytest fakes, 원격 pytest.

1. D-674와 규칙집에서 law(우회 불가 제약), rule(상황별 대응), AI-first의 설정 가능한 검사, 단계 입출력 및 현재 연결 범위를 명시한다.
2. `test_stuck_resolver_loop.py`에 후보 생성 후 E-stop·calibration·trip·사건 변경·사람 점유 경합을 재현한다. `test_ai_first.py`에 기타 문제의 calibration 및 전송 전 상태 변경, offline readback을 추가한다. 먼저 커밋 후 원격 실행하여 RED를 확인한다.
3. `fleet/stuck/pipeline.py`에 기존 공통 law와 후보 선택을 모으고 `resolver.py`, `loop.py`, `problems.py`에서 호출한다. 기존 오류 처리·재시도·UNKNOWN YIELD 비재발행을 유지한다.
4. `outcome.py`에서 offline 관측을 resolved 근거로 쓰지 않는다. 제한 시간 뒤 unresolved로 종결한다.
5. 원격 Fleet 관련 시험 및 affected 구조/문서 guards, `known_failures.py`, harness lint를 실행한다. 실패는 이 브랜치에서 수정하고 재검증한다.
6. 규칙집을 README에서 연결하고 변경 로그를 기록한다. 사용자 요청 전 main 착지·push·배포는 수행하지 않는다.

현장 검증은 별도다. SharedGather는 기존 최대 1 s 캐시를 공유하며 CORE가 장치에서 사건·권한·안전을 다시 검사한다. 이 작업은 캐시를 강제로 갱신하거나 AI 토론을 자동 활성화하지 않는다.
