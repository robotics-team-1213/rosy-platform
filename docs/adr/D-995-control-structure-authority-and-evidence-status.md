## D-995 관제 구조는 논리 단위·실행 owner·공통 서비스·호스트로 구분하고 구현과 현장 수용을 따로 기록한다

**Status:** Accepted (2026-11-08, 사용자 지시: 구조를 더 살펴보고 GitHub·관련 문서와 ADR까지 정확하게 갱신). 문서 정본과 책임 구분을 확정한다. 실행·권한·배포 구성은 변경하지 않는다. D-965의 결정 당시 팔 위임 미구현 설명과 D-994 2항의 같은 설명을 현재 소스 상태에 한해 대체한다. 두 ADR의 연결 대상·권한·배치 원칙은 유지한다.

### Context

N100 목표 배치를 정리한 뒤 R·셀·장치 owner·공통 서비스와 연결 문서를 현재 소스에 대조했다. 조사 기준은 로컬 main `9130e7ba67`와 그 위 D-994다. 소스 존재를 실물 배포·수용의 증거로 사용하지 않는다.

| 우선순위 | 확인된 문제 | 근거와 처리 |
|---|---|---|
| 높음 | 주행 위임 승인과 팔 이송 admission이 같은 경로처럼 읽힌다 | `control_unit_service.py`의 `approve`는 ARM을 `CONTROL_UNIT_ARM_ADMIT_AT_CELL`로 거절한다. 배포 안내에 주행 `/approve`와 셀 ARM `/admit`을 나눠 적는다 |
| 높음 | 일반 3단계 관제 tree가 모든 ARM 경로의 지원 범위로 오해될 수 있다 | `arm_transfer_relay_routes.py`의 `forward`는 직계 자식만 허용하고 더 깊은 셀의 증거·재검사를 `ARM_TRANSFER_RELAY_DEPTH`로 거절한다. 제한을 명시한다 |
| 보통 | “팔 위임 미구현”, “관제 PC는 브라우저”, “단위마다 PC 한 대”가 현재 설명에 남아 있다 | ARM wire·job 결속은 구현돼 있다. D-893·D-974의 논리 단위와 호스트 분리를 현재 안내에 적용하고 옛 날짜 기록은 보존한다 |
| 보통 | 앱 이름표와 실제 화면 제목이 다르다 | `cell/cell.html`은 `Rosy Fleet — 팔레트 적재`다. 앱 목록의 옛 제목만 바로잡고 id·URL·작업 종류는 유지한다 |

### Decision

1. **책임을 네 층으로 읽는다.** 관제 단위는 자기 원장·승인·admission과 범위별 조정을, 장치 owner는 최종 실행·안전·정지·복구를, 공통 서비스는 앱 사이의 제한된 공유 기능을, 호스트는 프로세스 실행을 맡는다. R은 직접 소유 장치와 하위 관제의 중계 역할을 함께 가질 수 있다. PC 수로 관제 단위 수를 정하거나 같은 PC라는 이유로 원장·승인·장치 권한을 합치지 않는다. 사람의 소유자 권한과 소프트웨어 owner도 구별한다.
2. **같은 사실은 같은 기준 문서로 연결한다.**

   | 사실 | 정본 |
   |---|---|
   | 관제 역할·현재/목표 호스트·연결 절차 | [관제 단위 배포 안내](../deployment/control-units.md). 실제 배치표는 이곳에만 둔다 |
   | 공통 서비스·공용 코드의 소유·분류 | [공통 서비스 카탈로그](../reference/common-services.md), 소스 holder는 `platform_parts.yaml` |
   | 앱 이름·사용자 작업·API/상태 owner | [앱 이름과 역할](../reference/app-names-and-roles.md), [앱별 작업과 책임](../reference/app-responsibilities.md) |
   | HTTP 경로·입력·응답·권한 | [API reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md)와 protocol schema |
   | 결정 이유·대체 관계 | 개별 ADR과 [ADR Log](../reference/ROSY%20ADR%20Log.md) |

   README·개발 가이드와 Confluence의 PC·하드웨어·소프트웨어·책임 지도는 이 기준의 요약과 링크를 제공한다. Confluence에 별도의 실시간 호스트 목록이나 장치 승인 규칙을 만들지 않는다. 기존 날짜 기록·그림은 당시 상태로 보존하고 최신 안내에서 그 범위를 밝힌다.
3. **팔 위임은 구현됐지만 배치·실물 수용은 별개다.** 외부 앱은 R의 기존 `POST /api/fleet/arm-transfers/jobs`로 제안한다. R의 relay가 workcell 소유 셀을 찾아 같은 request identity를 위임하고, 셀 inbox는 자기 ARM job을 기존 store에 결속한다. R은 셀 결과를 투영하며 하위 장치에 직접 명령하지 않는다.
   - 주행 위임은 기존 `/api/fleet/control-unit/delegations/{origin}/{identity}/approve`를 쓴다. ARM은 이 경로로 승인하지 않고 해당 셀의 `POST /api/fleet/arm-transfers/jobs/{mission_id}/admit`과 현재 부모 증명 검사를 거친다. 실물 팔의 기명 운영자 승인과 제안자 자기 승인 거절을 유지한다. 정책 admission worker는 기존 `simulation` 범위이며 실물 자동 승인으로 확대하지 않는다.
   - ARM job 투영·receipt와 별개인 physical-evidence·recheck 중계는 현재 직계 자식까지만 지원한다. 일반 topology의 최대 3수준을 모든 ARM 경로의 지원 완료로 쓰지 않는다. 깊은 셀이 필요하면 중간 관제의 증거·재검사 중계와 실패·권한 시험을 먼저 구현한다. 앱이 셀에 직접 연결하거나 장치 자격을 복사하는 우회는 하지 않는다.
4. **상태를 근거별로 기록한다.** 결정 채택, 현재 소스 구현, 해당 SHA의 원격/CI 시험, 서명 산출물·설치, 실제 호스트 연결, DEVICE/FIELD 수용은 서로 다른 사실이다. 오래된 ADR의 “미구현”은 결정 당시 사실로 남기고 후속 ADR에서 현재 상태를 정정한다. 소스·호스트 시험만으로 N100 이전·처리 용량·물리 동작을 완료로 바꾸지 않는다.
5. **다음 구조 개선은 R 배포의 서비스 구성을 먼저 검증한다.** 현재 `deploy/site/compose.yaml`은 Fleet뿐 아니라 Vision·Media·Postgres 등을 같은 서비스 묶음에 둔다. 작은 R 호스트에서 어떤 서비스를 실제로 실행할지와 CPU·메모리·디스크·영상 비용을 먼저 확정한다. 기존 서명 candidate의 선택 배포 지원을 확인하고, 부족하면 역할별 서비스 선택·필수 의존·서명 검증·rollback의 일관성을 별도 구현·시험한다. 이 ADR은 임의 Compose 삭제·미서명 overlay·서비스 이전을 실행하지 않는다. N100 수용은 D-994의 부하·장애 시험을 따른다.

### Evidence and verification

다음 소스와 기존 시험을 검증 대상으로 사용한다. 실제 실행한 SHA·수량·실패/skip은 원격 보고서와 GitHub PR에 남긴다.

- [ARM 후보·inbox schema](../../contracts/foundation/core_common/protocol/control_units.py), [위임·job 결속·부모 증명·승인 분리](../../operations/fleet/fleet/server/ledger/control_unit_service.py).
- [R의 ARM relay·직계 자식 제한](../../operations/fleet/fleet/server/work/arm_transfer_relay_routes.py), [셀 ARM admission·시뮬레이션 정책 경계](../../operations/fleet/fleet/server/work/arm_transfer_job_routes.py).
- `operations/fleet/test/test_control_unit_arm_{delegation,admission,http_pipeline,app_wiring}.py`: 제안·결속·부모 단절·취소·실제 앱 HTTP 경계의 소프트웨어 시험. 장치 모터를 구동한 증거가 아니다.
- 기존 관제 구성·자격·정지 owner 시험, 문서·하네스·앱 역할·공통 서비스 구조 시험과 변경 문서의 상대 링크 검사를 함께 확인한다.

### Existing decisions

| 결정 | 관계 |
|---|---|
| D-427 | 기존 소스 holder와 디렉터리를 유지한다 |
| D-429·D-430 | 원장·admission과 CORE/OMX 최종 실행, 독립 정지·복구 경계를 유지한다 |
| D-893·D-960·D-974 | 관제 단위·프로그램·물리 호스트·화면의 구분을 현재 문서에 일관되게 적용한다 |
| D-965·D-994 | 결정 당시 “팔 위임 미구현” 설명을 현재 소스 상태에 한해 대체한다. 외부 앱의 R 단일 입구와 N100 목표는 유지한다 |
| D-807·D-955·D-987 | 공통 사람 Account와 기계 자격·장치 허가·앱 업무 원장을 분리한다 |
| D-977 | 실물 팔 기명 승인과 simulation 정책 admission 경계를 유지한다 |

### Consequences

운영자는 이름·실행 호스트·업무 승인·최종 장치 명령을 혼동하지 않고 현재 구현과 현장 수용을 따로 확인할 수 있다. 대신 문서·GitHub·Confluence의 갱신은 같은 검증 revision을 참조해야 하며 동시 변경과 미게시 상태를 숨기지 않는다. 이번 변경은 문서 정정이며 원격 제어 기능 추가·실물 동작·배포 전환을 수행하지 않는다.
