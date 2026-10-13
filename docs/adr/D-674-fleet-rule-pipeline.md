## D-674 Fleet 통합 규칙집과 자동 판단 파이프라인

**Status:** Accepted (2026-10-12)

### Context

Fleet의 고정 대응, AI-first, 실행 권한 검사와 결과 추적이 여러 파일에 있다. 규칙을 목록으로만 모으면 입력 → 제약 → 후보 → 허가 → 실행 → 재관측의 연결을 검증할 수 없다. 순차 전송 중 후보 생성 이후 E-stop·calibration·trip·사람 점유·사건이 바뀔 수 있다.

### Decision

1. [통합 규칙집](../reference/fleet-rulebook.md)을 Fleet 규칙의 탐색 입구로 둔다. 코드·SRS·기존 ADR이 세부 계약이며 문서 편집으로 런타임 정책을 바꾸지 않는다.
2. 이 규칙집의 `law`는 AI와 상황별 rule이 우회할 수 없는 실행 권한 제약이다. `rule`은 law를 만족하는 상황의 대응 선택이다. UI 디자인 문서의 Law 번호와 구분해 `FL-*` 식별자를 쓴다.
3. 기존 자동 stuck 파이프라인을 `fleet.stuck.pipeline`의 공통 law와 후보 선택으로 연결한다. 기존 resolver의 상태·예산·AI-first 설정·교행 geometry·오류 처리·재시도 의미를 보존한다. 사람 소유 사건은 자동 후보가 전송되지 않는다.
4. stuck, stalled, pose_lost 자동 전송 직전에 기존 SharedGather의 최신 가용 행 및 live trip owner를 다시 검사한다. E-stop·calibration·offline·변경된 stuck·trip의 비-WAIT 후보를 전송하지 않는다. await 동안 생긴 사람 점유를 다시 확인한다. SharedGather의 최대 1 s 캐시는 유지하며 CORE의 장치 사건/권한/안전 재검사는 최종 권한이다. 원자적 장치 실행 보장을 Fleet snapshot으로 주장하지 않는다.
5. CORE 접수는 성공 종결이 아니다. 기존 Outcomes/ProblemLog readback을 이어간다. offline은 resolved 근거가 아니며 기존 확인 제한 시간 뒤 unresolved로 남긴다.
6. Task/Mission과 교통은 각 기존 admission/stop fence/lease/상태기계로 집행한다. 자동 policy Task의 비활성화와 advisory deliberation의 비실행 경계를 유지한다. 서로 다른 소유자의 저장 트랜잭션을 새 범용 실행기로 합치지 않는다.

### Consequences

규칙집·공통 law·후보 선택·전송 전 admission·결과 추적을 함께 시험한다. 새 public API, YAML 정책 편집기, 임의 Python 표현식 평가, AI 자동 활성화는 추가하지 않는다. SOURCE/원격 시험과 배포·장치·현장 수용은 구분한다.
