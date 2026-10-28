# 인증된 이송 복구 요청 원장 검증

현재 단계는 D-899의 내부 원장·승인 결속이다. 공개 HTTP/콘솔·실제 관측 생산자·장치 활성화·학습 수용은 포함하지 않는다.

## 구현과 근거

코드 revision `c36bfb48ad`. 원래 제안자의 요청, 요청보다 새로운 독립 관측, 별도 운영자의 정확한 승인 결속을 기존 Fleet 이벤트 원장에 보존한다. 자식 생성의 같은 DB 트랜잭션에서 원본 grant/receipt/assessment/generation/context와 최신 요청/근거·현재 제안자 권한을 확인한다. 자식 lineage의 역사적 요청 검증과 기존 내부 호출의 hash/실행 경계도 유지한다.

| Revision | 실제 원격 시험 | 결과 |
|---|---|---|
| `fb006de2b7` | 기존 recovery/flow/job/observer 4 suites | 74 passed, exit 0 |
| `d006bb7d4a` | 새 요청 원장 7 cases | 7 failed, 기대한 서비스 부재 RED |
| `5d5fcb9063` | 새 요청 + 기존 recovery/flow | 46 passed, exit 0 |
| `0c9d50cee4` | 직접 C 호출의 원본 판정 교체 반례 | 1 failed, 기대한 `DID NOT RAISE MissionConflict` RED |
| `342bec84f7` | 전체 원본 결속 수정 후 새 요청 + recovery/flow | 47 passed, exit 0 |
| `2a1a968b5b` | 읽기 전용 Account의 복구 요청 capability | 1 failed, 기대한 `True is False` RED |
| `c36bfb48ad` | 새 요청 + 이송 증거/원장/준비/제출/완료/dispatcher/observer/정지/판정/API 16 suites | 283 passed, 0 skipped, exit 0 |

각 행은 서로 다른 실행이며 고유 시험 개수로 합산하지 않는다. 로그는 개발 PC 시스템 임시 폴더의 `rosy-recovery-http-*` 아래에 있다. 새 실패를 baseline이나 quarantine에 추가하지 않았다. 최종 공식 착지·전체 영향 범위 결과는 후속 작업 기록에서 별도로 연결한다.

## 독립 검토와 수정

읽기 전용 계약 검토가 발견한 P1은 정상 서비스 호출과 달리 선택적 C 승인 결속에서 이전 인증 요청 A를 새 실패 판정 B와 섞을 수 있던 경로다. 새 회귀가 실제 자식 생성/claims 이전을 재현했고, 수정 후 새 승인과 역사적 lineage 모두 완전한 원본 tuple을 비교한다. 검토자가 source 수정을 재확인했다. 검토자는 원격 시험·장치 실행을 하지 않았다.

추가 self-review에서는 실제 mutation 권한은 막혀 있어도 read-only Account의 preview가 요청 가능으로 표시되던 문제를 RED/GREEN으로 고쳤다. API/화면에서 사용할 capability가 실제 `fleet.operate` grant와 일치한다.

## 한계와 남은 작업

- 합성 World 관측·fake owner를 사용하는 호스트 시험이다. 실제 Gazebo/실물 복구 성공률·센서 정답·모델 평가 근거가 아니다.
- resolver의 거래 내 호출과 권한 취소는 시험했으나 실제 PasswordSessions/Account HTTP 연결은 다음 HTTP 단계에서 구현·검증한다.
- 공유 recovery schema와 API version 등록, HTTP 설치, 실제 브라우저의 복구 UI는 후속 별도 착지 단위다. 현재 설치된 공개 API가 늘었다고 보고하지 않는다.
- metadata-only export의 학습 부적격·원래 실패 보존·root 단위 계보를 유지한다. RGB/행동 시연 수집이나 학습 승격을 하지 않았다.

CE: 해당 없음. 원본 결속과 권한 표시의 판단은 D-899·직접 회귀 시험·공통 원장 검증 코드에 남아 있으며, 추가 운영 교훈으로 확정할 별도 장치 장애를 해결한 것은 아니다.
