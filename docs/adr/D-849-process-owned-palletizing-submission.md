## D-849 팔레타이징 제출 검증은 공정이 소유하고 Fleet은 주입된 제출 경계를 소비한다

**Status:** Accepted for implementation (2026-10-23). 사용자가 구조 검토 보고서에 따라 공정 결합 분리와 코드 구현을 지시했다. 소스 소유권 변경이며 배포·실물 정책 활성화·현장 수용을 뜻하지 않는다.

### Context

`rosy.execution.site.cell_submission`은 compiler를 주입받지만 `pallet.transfer`, pallet marker, box/slip_sheet, layer와 operator sheet 검증을 직접 소유한다. 이를 공통 실행에 남기면 다른 공정의 추가가 공통 모듈 수정으로 번진다. 기존 검증을 삭제하거나 아직 소비자가 없는 범용 registry를 만드는 대신 실제 팔레타이징 책임으로 옮긴다.

### Decision

1. 기존 Cell 제출 타입·재컴파일 검사·기하·marker·checkpoint·저장 문서는 `rosy.processes.palletizing.submission`이 소유한다. `plan_bundle`의 checkpoint ID도 같은 공정 구현을 사용한다. 옛 execution 모듈에 사본·역방향 import를 남기지 않는다.
2. 공통 `rosy.execution`은 기존 PlanBundle·시도·목표 근거·진행 계산을 유지한다. 공정은 공통 계약을 소비하며 Fleet·DB·ROS·장치 실행을 import하지 않는다.
3. Fleet과 gateway의 설치된 compiler는 `compile_submission(candidate, *, workcell_id, instance_id) -> dict`로 검증된 기존 저장 문서를 제공한다. Fleet resolver는 이 신뢰된 조립 port를 소비한다. 누락된 port는 구성 시 거절하며 외부 요청이 compiler를 선택하거나 대체할 수 없다.
4. 단일 팔의 기존 envelope, digest·Job ID 계산, `CELL_TRANSFER`, resource·marker·checkpoint·목표 근거 형식을 보존한다. recipe/3 다중 팔은 기존 별도 경로를 유지한다. 외부 API 버전·장치 grant·정지 세대를 변경하지 않는다.
5. 소스 이동은 공정 artifact digest를 바꿀 수 있다. 이전 제안을 새 revision에 맞춘 것으로 재해석하거나 자동 승인하지 않는다. 설치 wheel/sdist와 실제 Fleet·gateway 소비자를 함께 검증한다.
6. 이동으로 1,000줄 미만이 된 `site_execution`은 별도 size unit 등록을 제거하고 기존 Fleet holder의 부모 단위에 합산한다. 측정 대상·상한은 유지하고 `small` 예외나 코드 채우기를 추가하지 않는다. 앱 개발 샘플의 공정 digest fixture도 실제 소스 digest로 갱신한다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 기존 operations/processes와 site_execution root를 유지하며 구현 소유와 설치 소비만 수정한다 |
| D-429 | 공정은 계산·검증을, Fleet은 원장·admission·dispatch를 소유한다. 별도 서버나 명령 writer를 추가하지 않는다 |
| D-430 | CORE·OMX의 최종 명령, claim·stop/fence와 장치 재검사를 유지한다. safety-tagged 구현을 변경하지 않는다 |
| D-657 | 순수 목표 근거·진행 계산은 execution에 남기고 Fleet transaction 소유를 유지한다 |
| D-827·D-836 | 도메인 중립 방향 중 기존 공정 제출 소유권만 구체화한다. 범용 공정 API나 실물 dispatch 개방을 뜻하지 않는다 |

### Consequences and verification

지원되는 wire는 같고 내부 Python import는 새 공정 위치로 일괄 변경한다. 기존 compiler를 주입하는 내부 소비자는 제출 메서드를 제공해야 한다. 임의 공정·새 Skill을 수락하는 기능은 추가하지 않는다.

검증은 port 누락의 구성 시 거절, 실제 compiler의 정상·변조 제출, 기존 marker·checkpoint와 단일/다중 팔 회귀, 공통 execution의 공정 없는 import, checkout 밖 wheel/sdist의 제출 모듈·gateway 소비를 포함한다. 원격 시험 SHA와 결과는 별도 검증 기록에 둔다. host 시험 통과로 장치·물리 완료를 주장하지 않는다.
