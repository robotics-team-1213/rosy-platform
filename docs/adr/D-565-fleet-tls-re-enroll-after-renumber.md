## D-565 TLS 로봇은 번호를 바꾼 뒤 대기 binding으로 다시 등록한다 — root 소유 binding 파일이 승인이고, CA·호스트 이름·robot_id 셋이 모두 맞아야 등록된다

**Status:** Proposed (2026-10-09, 현장 문제에서 나온 최소 수정. 등록 경로를 넓히는 변경이라 **독립 보안 검토 대상**이다). SOURCE 변경과 호스트 테스트만이다. 현장 Fleet 재시작과 rosy_41·rosy_40 재등록은 이 기록이 하지 않는다.

잇는 결정: [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(화면 코드로 등록, 자격은 Fleet 등록부) · [D-456](D-456-lan-receiver-approval-and-persistent-pairing.md)(같은 LAN 승인, TLS 조건) · [D-555](D-555-enrolled-robot-hub-pairing.md)(TLS로 묶인 등록만 허브 자격을 받는다) · [D-562](D-562-ceiling-marker-id-equals-robot-number.md)(로봇 번호 40–49로 다시 매김)

### Context

2026-10-09 현장에서 확인했다.

- D-562에 따라 로봇 번호를 바꿨다. 9dfk는 rosy_26 → rosy_41, 8kcn은 rosy_60 → rosy_40이다. `robot_id = rosy_NN`은 `ROSY_ROBOT_NUMBER`에서 나오고 로봇이 등록 때 `system/info`로 알린다.
- 순서: 콘솔에서 rosy_26 등록 해제(`removed`) → 로봇 번호 변경·재부팅(CORE `robot_id=rosy_41`, TLS 필수 그대로, 호스트 이름 `rosy-pinky-9dfk.local`과 CA 그대로) → `POST /api/fleet/enrollment/robots {code, address:"192.168.1.201:8080"}` → `409 tls_binding_required`.
- 코드(`operations/fleet/fleet/server/enrollment.py` `_candidate`)는 HTTPS 대상에 대해 그 주소에 이미 등록된 행 하나와 그 행의 binding을 요구했다. 새 번호의 로봇은 행이 없으니 통과할 길이 없다.
- 문서 절차(`deploy/site/enrolled-tls-runbook.md`)는 "HTTP로 먼저 등록하고 binding을 붙인다"다. TLS 필수 로봇은 HTTP로 등록할 수 없다. CORE `network.tls`를 끄면 `wait-core-ready`가 재시작을 되풀이한다.
- `EnrolledTlsBindings.validate`는 등록되지 않은 `robot_id`의 binding이 하나라도 있으면 Fleet 기동을 거절했다. 현장 binding 파일에는 아직 rosy_26이 있어 다음 기동이 거절된다.

### Decision

1. **대기 binding.** 관리자가 승인한 binding(root 소유 공개 파일의 행)은 아직 등록되지 않은 `robot_id`를 가리킬 수 있다. Fleet 기동은 이를 거절하지 않고 경고 로그에 그 ID 목록을 남긴다(`TLS bindings pending enrollment (D-565)`). 대기 binding에는 downgrade 방지 기록(`robot_enrollment_tls`)을 만들지 않는다.
2. **호스트 이름 충돌은 계속 거절한다.** binding의 호스트 이름이 **다른** `robot_id`로 등록된 행(`pending_logout` 포함)의 호스트 이름과 같으면 기동을 거절한다. 그 행이 사라지면(로그아웃 확인된 등록 해제) 받아들인다. 등록된 binding은 지금처럼 자기 행의 호스트 이름과 같아야 한다.
3. **행이 없는 HTTPS 대상은 대기 binding으로만 등록한다.**
   - 고르기: 목록 등록은 스캔 행의 `hostname`·`port`, 주소 직접 입력은 그 주소의 HTTPS 스캔 행들의 호스트 이름(하나여야 한다)·포트로, 아직 등록되지 않은 binding 중 `hostname`·`port`가 같은 것 **하나**를 고른다. 없거나 여럿이면 `409 tls_binding_required`. 광고는 고르는 데만 쓴다.
   - 연결: 그 binding의 `robot_id`로 기존 TLS 등록 클라이언트(`DiscoveryTransport` + `EnrollmentIdentityTransport`)를 만든다. TCP 목적지는 binding 호스트 이름의 발견 결과이고, 인증서는 binding CA와 호스트 이름으로 검증한다. 코드를 보내기 전에 공개 identity의 `receiver_id`(그리고 알리면 `tls_hostname`·`tls_ca_sha256`)가 binding과 같아야 한다. 다르면 코드는 나가지 않고 `409 tls_binding_mismatch`, TLS 이름을 찾지 못하면 `502 unreachable`이다.
   - 받아들이기: 코드 교환 뒤 `whoami`·`system/info`를 같은 TLS로 읽는다. 보고된 `robot_id`가 binding의 `robot_id`와 같을 때만 저장한다. 다르면 `409 code_consumed`(reason `tls_binding_mismatch`, D-361 소모 모양)이고 받은 토큰을 같은 TLS로 로그아웃한다.
   - 저장: 행을 넣을 때 binding의 origin(`https://<hostname>:<port>`)과 CA DER SHA256을 downgrade 방지 기록으로 같이 남긴다. 기동 때 묶인 행이 받는 것과 같다. 실패하면 행과 기록을 함께 지운다.
   - HTTP로 내려가는 경로는 없다. 자동 재시도도 없다.
4. **기존 가드는 그대로다.** `robot_id_conflict`, `pending_logout`, 코드 소모·소각 규칙, 관리자 코드 거절, 실행 중 binding 파일이 바뀌면 거절(`TLS bindings changed; explicit reviewed restart required`), 기록된 origin·CA와 다른 설정 거절.

### 보안

- **승인.** binding 파일은 root(또는 실행 UID) 소유, 그룹·다른 사용자 쓰기 없음, 심볼릭·하드링크 거절이다(`enrollment_tls.py` `_public_file`). 이 파일을 쓸 수 있는 사람은 사이트 관리자뿐이므로 행 하나가 "이 CA로 이 이름을 증명하는 장치를 이 `robot_id`로 받는다"는 운영자 승인이다. 이 결정은 승인 주체를 바꾸지 않는다. 바뀐 것은 승인이 등록보다 먼저 올 수 있다는 것뿐이다.
- **신뢰의 닻은 로봇의 CA 키다.** 확인은 셋이다. (a) TLS: binding CA가 서명하고 binding 호스트 이름을 SAN에 가진 인증서, (b) 코드 전 identity의 `receiver_id`, (c) 코드 교환 뒤 `system/info`의 `robot_id`. (b)·(c)는 로봇이 스스로 알리는 값이라 인증이 아니다. TLS 안에서 읽으므로 경로 위에서 바꿀 수는 없지만, binding CA 키를 가진 장치는 아무 ID나 알릴 수 있다. (b)·(c)는 잘못 고친 binding(ID와 로봇 번호가 다름)을 잡는 일관성 검사다. 그래서 **로봇마다 자기 CA를 가져야 한다.** 두 로봇이 CA 하나를 나누면 한 로봇의 키로 다른 로봇의 binding을 통과할 수 있다. 관리자는 binding의 CA 지문이 다른 행과 겹치지 않는지 확인한다.
- **광고를 믿지 않는다.** 스캔 행은 binding을 고르는 데만 쓴다. 광고가 다른 binding의 이름을 대도 연결은 그 binding의 CA·이름으로 검증되고 (b)·(c)가 맞아야 한다. 광고된 주소가 무엇이든 코드는 TLS 검증 전에 나가지 않는다.
- **HTTP로 새지 않는다.** 승인 binding(대기·등록 모두)이 가진 호스트 이름이나 주소는 HTTP 경로에서 요청 전에 `409 tls_binding_required`로 거절한다. 스캔 행이 없어 이름을 모르는 주소 입력이면 HTTP로 읽은 `robot_id`·호스트 이름을 binding이 가지는지 보고, 가지면 소모 거절(`code_consumed`, reason `tls_binding_required`)과 토큰 로그아웃을 한다. 이 경우 코드는 이미 평문으로 나갔으니 운영자는 로봇을 재시작해 새 코드를 받는다.
- **화면 코드는 그대로 필요하다.** 대기 binding은 코드 없이 아무것도 하지 않는다. 운영자가 로봇 화면의 코드를 읽어 입력하는 D-361의 결속은 남는다.
- **남는 위험.** binding 파일을 쓸 수 있는 관리자 계정이 뚫리면 대기 binding으로 낯선 장치를 승인할 수 있다. 이는 기존 binding 파일과 같은 위험이며 새로 생기지 않는다. 오래 남은 대기 binding은 기동 경고로 보인다.
- **기존 문제(이 결정 밖).** 거절 뒤 토큰 로그아웃이 실패하면(로봇이 응답 없음) 그 토큰은 등록부에 기록되지 않은 채 로봇에 남아 만료까지 유효하다. D-361 등록 경로에 원래 있던 동작이며 D-565가 새로 만들지 않았다. 따로 다룬다.

### 관계

| 결정 | 이 기록과의 관계 |
|---|---|
| D-361 | 화면 코드 교환·`whoami`/`system/info` 확인·등록부 저장 흐름을 그대로 쓴다. 바뀐 것은 HTTPS 대상의 연결 경로뿐이다 |
| D-456 | TLS 조건(로봇 키로 인증)을 등록 첫 단계부터 적용한다. 장기 승인 관계·키 증명 세션은 여기서 하지 않는다 |
| D-555 | 대기 binding으로 등록한 행은 처음부터 TLS로 묶인 등록이므로 허브 연결 대상이다 |
| D-562 | 번호를 바꾼 TLS 로봇을 다시 받는 운영 절차가 이 기록이다 |

### 운영 절차 — TLS 로봇 번호 바꾸기

> 2026-10-09 [D-580](D-580-site-roster-follows-fleet-enrollment.md): 옛 ID가 이 Fleet에 등록되었던 binding이면 3·4단계(파일 수정, Fleet 재시작)는 필요 없다. 콘솔 등록 해제 → 번호 변경 → 콘솔 등록이다. 아래 절차는 처음 들어오는 로봇과 sudo 대체 경로로 남는다.

1. 콘솔에서 옛 ID(예: rosy_26)를 등록 해제한다. 결과가 `removed`여야 한다. `pending_logout`이면 로봇이 보일 때 로그아웃이 끝날 때까지 기다린다(그 행이 남아 있으면 같은 호스트 이름의 새 binding은 기동에서 거절된다).
2. 로봇 번호를 바꾸고 재부팅한다(D-562). 로봇의 호스트 이름과 CA는 그대로다.
3. 관리자가 binding 파일의 그 행에서 `robot_id`만 새 ID(예: rosy_41)로 바꾼다. `hostname`·`port`·`tls_ca_file`·`tls_ca_sha256`은 그대로 둔다. 소유자·권한은 그대로다.
4. 승인된 배포 절차로 Fleet을 재시작한다. 로그에 `TLS bindings pending enrollment (D-565): rosy_41`이 보인다.
5. 콘솔에서 로봇 화면의 코드로 등록한다(목록 또는 주소). 성공하면 그 행은 TLS로 묶인 등록이다. `tls_binding_mismatch`(오류 코드 또는 `code_consumed`의 reason)이면 binding의 ID와 로봇의 `ROSY_ROBOT_NUMBER`가 다르다. 토큰은 이미 로그아웃되었으니 binding이나 로봇 번호를 고친 뒤 새 코드로 다시 한다.

### Alternatives

- **TLS를 잠깐 끄고 HTTP로 등록한 뒤 binding을 붙인다.** 기각: CORE가 TLS 필수 설정을 끄면 재시작을 되풀이하고, 평문 HTTP로 코드와 토큰을 보내게 된다.
- **binding 없이 광고된 CA를 받아들인다(TOFU).** 기각: 광고는 위치 후보일 뿐이고 CA 승인은 관리자 몫이다(runbook).
- **옛 행의 `robot_id`를 등록부에서 바로 바꾼다.** 기각: 봉인된 자격은 `robot_id`에 묶여 있고(`seal(... robot_id=...)`), 로봇이 옛 토큰을 다른 ID로 알린다. 새 코드로 새 토큰을 받는 편이 짧고 안전하다.

### Consequences

- 등록되지 않은 binding이 남아도 Fleet은 뜬다. 대신 경고가 남는다. runbook의 "등록되지 않은 binding이 남으면 다음 시작이 거절된다"는 문장은 바뀐다.
- 새 오류 코드 `tls_binding_mismatch`(409)가 `POST /api/fleet/enrollment/robots`에 생긴다(API Reference v1.168).
- 실제 현장 수용(rosy_41·rosy_40 재등록, 허브 연결)은 별도다.
