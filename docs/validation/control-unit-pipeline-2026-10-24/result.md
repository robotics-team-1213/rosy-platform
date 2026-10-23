# 관제 위임 파이프라인 소프트웨어 검증

**현재 판정:** 집중 검증 통과. 최종 통합 검사·공식 로컬 main 착지는 아직 대기한다. 실물·배포·현장 수용 기록이 아니다.

## 연결한 경로

정적 manifest → 자기 unit에 묶인 SQLite 위임 원장 → 직접 이웃 HTTP → 최종 target의 기명 운영자 승인 → 기존 Task 생성 transaction의 위임 결속 → 기존 dispatch·native owner 검사 → CORE 실행 receipt → 기존 native 결과·quiescence 재조정 → 원래 위임 결과의 상위 투영을 연결했다.

독립 관제와 R/A/B/A1 구성을 지원한다. 각 인스턴스는 자기 DB·직접 로봇 목록·인증을 사용하며, 상위와 service principal은 하위의 사람 승인을 대신하지 못한다. 요청은 유한 navigation 후보 하나이며 D-851 전체를 일괄 수용하지 않는다. 계약은 D-855·API v1.297, 배치는 [구성 안내](../../deployment/control-units.md)를 따른다.

## 실행 증거

모두 커밋된 SHA를 공식 `tools/remote/remote_pytest.py`로 모델/AI 시험 PC pool에 전달했다. 아래 실행들은 범위가 겹치므로 합산하지 않는다. 원본 로그는 개발 PC 외부 임시 폴더의 `<로그 이름>/run-1.txt`에 보존하며 SHA-256은 아래와 같다. 원격 push·CI 증거로 해석하지 않는다.

| 실행 SHA | 범위 | 실제 결과 | 로그 이름 |
|---|---|---|---|
| `fe7ef2f475` | 조건부 취소 CORE receiver·목표/trip lease·Fleet sender/transport | 201 PASS, 종료 0, NEW 0 | `rosy-scoped-final-green` |
| `6655eb3061` | 실제 Fleet 앱 startup/shutdown·CLI·기존 앱/복구 설정 | 132 PASS, 종료 0, NEW 0 | `rosy-control-bootstrap-green` |
| `987092ef9c` | 무로봇 독립 aggregate CLI와 기존 CLI | 52 PASS, 종료 0, NEW 0 | `rosy-control-root-green` |
| `26bba0703f` | store·위임 서비스·인증 routes·고정 HTTP·3곳 재시작 | 47 PASS, 종료 0, NEW 0 | `rosy-control-simplified` |
| `a7aaaed472` | 잘못된 peer port 거절·실제 앱/CLI·CORE 종단 | 16 PASS, 종료 0, NEW 0 | `rosy-control-peer-port-green` |
| `290c8344a0` | 실제 Chromium, 1366/320 × dark/light·미확인 요청 재적재·확정 거절 복구 | 6 PASS, 종료 0, NEW 0 | `rosy-control-browser-retained` |

```text
rosy-scoped-final-green       a977dd587e2d461c239631727a974a02fd80b5c2cc86e02235d2f8ac5f7dc3b3
rosy-control-root-green       54712af26765b35fe9dc4fca1781a4256d5dd1124ef5b35cb6fd0cd68121c98a
rosy-control-simplified       41bf5e5767fecdf2f21472ca7c3fcc78cc6dfd60dde6dffc696113c6ff79130d
rosy-control-peer-port-green  b1800f92c8ddc434c5a037617648ba21207ad83f00e82f582abc0bd5b7549a0f
rosy-control-browser-retained d17e625821906363d3501a1abb4c949d5f767b1bc1f1286b0be6af291bb6c3d8
```

기반 원장·구성의 먼저 착지한 범위는 [별도 기록](../control-unit-foundation-2026-10-23/result.md)에 있다. 공유 wire의 FULL 검증과 착지 상태는 별도 의존성이다. 이 표의 집중 GREEN이 그 검사나 최종 통합 검사를 대신하지 않는다.

## 실제로 확인한 것

- 독립 unit의 자기 작업 승인·대기 취소, 무로봇 aggregate의 실제 CLI 기동을 확인했다. 중첩에서 다른 자식·조상 직통·잘못된 자원·순환·중복 소유·초과 깊이를 거절한다.
- R→A→A1의 실제 HTTP 경로에서 inbox DB 커밋 뒤 ACK 유실을 주입했다. 같은 identity 재전달 후 한 행·한 Task·같은 승인자를 유지하며 R/A/A1 각각의 재시작에서도 같은 결속을 조회한다. B는 호출하지 않는다.
- 별도 종단은 R/A/A1 서비스, 실제 FleetConsole·Task scheduler·HTTP RobotClient·CORE API·NavigationManager·native readback·claim 해제를 연결한다. odometry와 localization 관측, actuator 및 transport quiescence는 합성이다. CORE의 readiness 검사를 우회하지 않고 simulator용 odometry 증거를 제공한다. 완료와 취소 모두 원래 boot/run/attempt 결과를 상위까지 보존한다. 이 종단의 관제 peer는 통제된 직접 호출이며, 관제 HTTP 직렬화·인증 왕복은 앞의 HTTP 종단이 별도로 검증한다.
- 승인자와 Task binding은 기존 Task 생성 transaction 안에서 함께 커밋·롤백한다. null actor를 승인으로 해석하지 않으며 stale revision, 다른 승인자·본문·owner·DB identity를 거절한다. 위임 Task에는 native receipt가 필수다.
- 부모부터 조상까지 연결·같은 배정·취소 여부를 승인 직전에 재확인한다. 미완료 결과 투영은 5초 뒤 stale이며 재대조로 복원한다. 확정 종단 결과는 불변이다. 단절·낮은 owner revision·잘못된 scope가 재배정·재무장을 만들지 않는다.
- 취소 409/timeout을 한 위임에 격리해 뒤 요청을 계속 복구한다. DB 장애는 빈 성공 목록 대신 503으로 보존한다. terminal 이력 뒤에 오래된 미완료가 묻히지 않으며 활성 후보는 256개로 제한한다.
- UI는 목표 좌표·방향·위임 ID·직접 위임 담당을 보여 준다. 승인 시 현재 revision을 보내고 stale·권한 거절을 표시한다. 미확인 제출은 사용자와 unit별 같은 body/ID로 복원하며 복원 자체가 POST를 만들지 않는다. 확정된 접수 전 거절만 새 요청 작성을 허용한다. 폴링 뒤 키보드 포커스를 복원한다.

## 독립 검토와 한계

계약 검토에서 찾은 새 run/trip lease 취소 경쟁, 복구를 끊는 transport 예외, journal 장애의 500, 승인 목표 누락·미확인 identity 유실·포커스 유실·접수 전 거절 잠금을 각각 회귀로 재현하고 수정했다. 구현·표시·물리 정지를 구분해 검토했다. 공유 SSH 모델 책임 분리는 기존 정의와 AST 동등성을 확인하고 canonical export와 크기 기준을 같은 커밋에 유지했다.

활성 복구는 직렬이며 256개 슬롯 전체의 처리율을 보장한 시험은 아니다. 느린 이웃에서 5초를 넘기면 stale로 보존한다. 기존 순서를 바꾸는 동시 실행 최적화는 이 검증의 범위에 없다. 실제 네트워크·서비스 배포·actuator 동작·물리 정지·ARM64 이미지·현장 화면 수용은 실행하지 않았다. 정책·모델 dispatch의 권한이나 활성 상태를 열지 않았다.

CE: 해당 없음 — 수정 판단은 코드·실제 실패 회귀·이 검증 기록으로 확인할 수 있어 별도 교훈을 중복 작성하지 않았다.
