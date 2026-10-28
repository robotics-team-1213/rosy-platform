## D-899 인증된 이송 복구 요청과 독립 운영자 승인

**Status:** Accepted for implementation (2026-10-27, 사용자 “바로 처리”, “해”). simulation용 계약·구현 승인이다. 제품 활성화·실물·실제 Gazebo 생산자·학습 수용은 별도다.

### Context

D-895는 내부 호출에서 원래 제안자·별도 운영자·독립 관측을 검증하지만, 공개 요청의 로그인 주체가 복구를 제안했다는 영속 근거와 복구 관측 ingress는 없다. body의 제안자 이름으로 내부 호출을 구성하면 그 경계를 증명하지 못한다. 실패 작업의 원래 실행을 초기화하지 않고 요청과 자식의 관계를 보존해야 한다.

### Decision

1. Fleet의 기존 `fleet_cell_events`에 인증된 원래 제안자의 복구 요청과 독립 observer의 근거를 불변 이벤트로 보존한다. 요청 키·부모·정확한 grant/receipt/assessment/generation·제안자 권한 snapshot·digest를 결속하고 비밀 credential은 저장하지 않는다. 요청은 claims 이전이나 실행을 하지 않는다.
2. 복구 전제 관측은 기존 receipt와 판정뿐 아니라 해당 요청 생성 시점보다 새로워야 한다. 일반 실행 관측·다른 요청·새 label을 붙인 이전 frame은 복구 권한을 만들지 않는다. producer 인증과 사용자 인증을 분리한다.
3. 별도 named operator가 정확한 요청 ID·proposal/evidence digest·generation을 승인한다. 최신 요청/근거, 원래 제안자의 현재 권한, 기존 dispatch/owner/claims/관측 검사는 D-895 자식 생성의 동일 `BEGIN IMMEDIATE`에서 검증한다. 별도 승인 커밋이 자식 없이 성공한 상태를 만들지 않는다.
4. 자식 생성과 원래/자식 lineage에 공개 승인 결속을 함께 저장한다. 기존 내부 호출의 hash/동작은 바꾸지 않는다. 정확한 승인 replay는 보존된 요청과 근거를 역사적으로 대조하며 현재 TTL·최신 요청·owner 응답을 요구해 새 시도를 만들지 않는다. 새 승인은 현재 권한과 근거를 요구한다.
5. 부모 실패/HOLD는 보존하고 자식은 별도 새 PRE_DISPATCH/POST_ACTION 관측으로 기존 제출·완료 경로를 거친다. root당 자식 하나와 최대 1회 복구 예산을 유지한다. 운영 승인과 학습 라벨 검수는 분리한다.
6. 공개 HTTP 계약은 D-18에 따라 공유 schema/API reference에 등록하고 별도 계약 브랜치로 먼저 검증한다. 그 뒤 기존 simulation 콘솔에 요청·관측 대기/만료·별도 승인·자식 결과를 연결한다. 실제 관측 생산자가 없으면 관측 대기와 승인 차단을 표시한다. 합성 생산자는 시험 fixture이며 배포 기본값이 아니다.

### 기존 경계와의 관계

| 기준 | 유지하는 경계 |
|---|---|
| D-427 | Fleet이 요청·원장·승인·자원을 소유한다. World는 측정 사실을 제공한다. |
| D-429 | observer 사실·운영자 승인·owner 실행·학습 검수는 서로의 권한을 대신하지 않는다. |
| D-430 | 기존 CORE/owner의 명령·정지·grant 경계를 우회하지 않는다. 연결된 권한/원장 경로를 독립 검토한다. |
| D-895 | 기존 시도와 1회 복구 후손을 보존하며 새 public intent 결속만 추가한다. |

### Verification and limits

원래 제안자 위조·자기 승인·권한 취소·관측 재사용/만료·요청 대체·동시 승인·재시작/replay·owner 장애를 원격 시험한다. API·브라우저의 합성 World/fake owner 시험은 실제 Gazebo 과제·실물 동작·모델 성능 수용을 대신하지 않는다. 계약·원장·HTTP·콘솔의 실제 구현과 시험 상태는 모듈 검증 기록에 별도로 남긴다.
