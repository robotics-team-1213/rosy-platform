# 독립·중첩 관제 구성

관제 하나는 자기 SQLite 원장·직접 소유 자원·기명 운영자를 가진 Fleet 인스턴스다. 상위 연결 없이 독립 실행할 수 있고, 같은 구조를 하위에 넣어 최대 3수준으로 구성한다. 상위는 작업 후보를 전달하고, 최종 대상 관제의 기명 운영자가 승인한다. CORE의 최종 주행 권한과 기존 Task admission·dispatch 닫힘은 유지한다.

이 문서는 소프트웨어 설정 절차다. 실제 서비스 배포·장치 운행·현장 수용을 실행한 기록이 아니다. 계약은 [D-855](../adr/D-855-control-unit-wire-and-scoped-cancel.md)와 [API reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md)를 따른다.

## 예제 R → A → A1

[설정 예제](../../deploy/site/control-unit.example.yaml)는 A1용이며 주소·로봇은 합성 값이다. 같은 manifest와 revision을 사용해 다음 세 인스턴스를 준비한다. 파일·DB·자격을 인스턴스 사이에 공유하지 않는다.

| 인스턴스 | 직접 로봇 목록 | peers에 필요한 이웃 | 수신 users의 service principal |
|---|---|---|---|
| R | `robots: []` | A | `control-unit:A` |
| A | `robots: []` | R, A1 | `control-unit:R`, `control-unit:A1` |
| A1 | `example-robot`만 | A | `control-unit:A` |

각 peers 항목의 `token_file`은 **상대 관제**가 그 호출자를 service로 인증하는 별도 비밀 파일이다. `users-file`에는 수신 토큰의 hash와 `role: service`, 위 principal ID를 등록한다. 기명 운영자는 별도의 `operator` 자격이다. 장치·운영자 토큰을 관제 사이의 service 토큰으로 재사용하지 않는다. 실제 비밀·주소·설정은 승인된 private 위치에 둔다.

각 인스턴스는 기존 `fleet console`에 다음 인자를 더한다. 아래 경로는 배치 시 정하는 예시다.

```sh
fleet console --robots /etc/rosy/robots.yaml \
  --users-file /etc/rosy/site-users.yaml --tasks-db /var/lib/rosy/fleet.sqlite3 \
  --control-unit-config /etc/rosy/control-unit.yaml
```

기본 loopback 바인드를 유지하고, 실제 이웃 연결은 승인된 TLS·네트워크 배치로 제공한다. peers URL은 고정 origin만 허용하며 사용자 요청의 주소·토큰을 사용하지 않는다. redirect를 따라가지 않는다. 설정이 없으면 기존 Fleet 동작을 유지한다.

## 요청과 결과 확인

1. R의 작업 화면에서 대상 A1·그 직접 소유 로봇·목표 좌표를 지정해 후보를 요청한다. `origin_id`는 R 서버가 정한다. 요청 접수는 실행 승인이 아니다.
2. A1의 작업 화면에서 출처·대상·목표·원장 상태를 확인하고 기명 운영자로 승인한다. A와 R의 운영자는 A1을 대신해 승인할 수 없다. 서비스 자격도 승인할 수 없다.
3. 승인 시 같은 journal transaction에서 기존 Task에 위임을 결속한다. 실행은 기존 dispatch 재무장·로봇 상태·안전·자원 검사를 통과해야 한다. 이 기능이 dispatch를 자동 재무장하지 않는다.
4. R은 A를 통해 A1의 원래 작업 결과를 읽는다. 같은 identity와 본문의 재전달은 새 Task를 만들지 않는다. 응답이 유실됐으면 identity를 바꾸지 않고 원장을 다시 확인한다.

최근 위임 조회는 최대 100건, 미완료 복구 대상은 최대 256건이다. 완료 기록이 많아도 오래된 미완료 항목을 복구한다. 완료 이력의 보관·DB 유지보수는 기존 현장 journal 운영 절차를 따른다.

## 취소·단절·재시작

- 취소는 같은 위임의 요청으로 전달한다. 미제출 후보는 닫을 수 있다. 제출된 Task는 원래 boot/run/correlation의 조건부 취소만 사용하며 구형 무조건 취소로 대체하지 않는다.
- 취소 receipt는 실제 정지나 자원 해제 증거가 아니다. 기존 native 결과·quiescence 재조정이 Task claim을 해제한다. 현재 facade가 새 실행을 가리킬 수도 있으므로 원래 receipt의 범위를 확인한다.
- 상위에서 받은 위임의 승인 직전 직접 부모부터 조상까지 같은 배정의 취소 여부와 연결을 확인한다. 단절 때 해당 위임의 새 승인을 막는다. 이미 admission을 마친 유한 Action은 기존 owner가 처리한다. 자동 대체·재배정·재무장은 없다.
- 미완료 owner 투영은 마지막 성공 조회 뒤 5초가 지나면 stale이다. 원장 상태가 바뀌지 않아도 재대조로 신선도를 확인한다. 확정된 종단 결과는 단절 뒤에도 원래 결과로 보존한다.
- 재시작해도 위임·승인자·Task identity를 유지하며 dispatch는 기존 startup 정책대로 닫힌다. Task 없는 승인 중 기록은 운영자가 최신 상태로 다시 확인한다.
- 미완료 위임이 있는 구성 revision 변경은 시작을 거절한다. 기존 구성에서 원래 작업을 조정·해결한 뒤 계획된 변경을 수행한다. DB를 새 unit ID에 재사용하지 않는다.

## 검증 경계

관제 HTTP·SQLite·권한·재시작 시험과 CORE 조건부 취소 시험은 호스트 소프트웨어 검증이다. 실제 actuator 동작·물리 정지·현장 네트워크 단절과 복구·운영 PC 화면 수용은 별도로 확인해야 한다. 세부 상태가 Proposed인 D-851 전체를 이 구현으로 일괄 수용하지 않는다.
