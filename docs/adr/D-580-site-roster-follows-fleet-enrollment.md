## D-580 사이트 로봇 목록은 Fleet 등록부를 따른다 — 번호를 바꾼 TLS 로봇은 증명한 binding으로 다시 등록하고, 카메라·갱신 검사는 등록부에서 로봇과 마커를 읽는다

**Status:** Proposed (2026-10-09, 사용자 결정 "바로 개선해"). SOURCE 변경과 호스트 테스트만이다. TLS 신뢰 경로를 바꾸는 변경이라 **독립 보안 검토 대상**이다(아래 보안 절). 현장 설정을 한 번 바꾸는 일과 현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(화면 코드 등록, 등록부가 자격의 주인) · [D-565](D-565-fleet-tls-re-enroll-after-renumber.md)(대기 binding으로 다시 등록) · [D-562](D-562-ceiling-marker-id-equals-robot-number.md)(천장 마커 id = 로봇 번호 40–49) · [D-569](D-569-site-update-inventory-drift.md)(갱신 기능 검사는 회귀를 본다) · [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(천장 추적). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

2026-10-09 현장에서 8kcn을 rosy_60 → rosy_40, 9dfk를 rosy_41로 다시 매겼다(D-562). 코드와 이미지는 자동 갱신되지만 사이트 PC의 root 소유 파일 셋이 로봇마다 상태를 들고 있어, 사람이 sudo 스크립트(`site-fix-2.sh`)를 돌려야 했다.

1. `/etc/rosy/site/enrolled-tls-bindings.json` — `robot_id` → 호스트 이름·포트·CA 파일·CA 지문. D-565 절차 3단계가 이 파일의 `robot_id`를 손으로 바꾸게 한다.
2. `site-cameras.yaml` — `robot_ids`와 `robot_markers`. Fleet(`--sightings-config`)과 Vision이 같은 파일을 읽는다. 시작할 때 고정되어, 나중에 등록한 로봇은 카메라 대상이 아니고 마커도 배정되지 않는다.
3. `autoupdate.conf` — `functional_checks` `/api/fleet/state`의 `required_ids`. D-569 뒤로는 막지 않고 `inventory-drift` 경고만 남기지만, 번호를 바꿀 때마다 경고가 남는다.

### Decision

1. **번호를 바꾼 TLS 로봇은 증명한 binding으로 다시 등록한다.** TLS로 묶인 등록을 콘솔에서 해제하면 Fleet 등록 DB의 `robot_tls_renumber(hostname, ca_sha256, file_robot_id, robot_id)`에 그 binding의 호스트 이름·CA 지문·파일 행 `robot_id`·등록 ID를 적는다(그 장치가 이 binding으로 여기 등록되었다는 기록). 대기 binding(D-565)이 이 기록과 맞으면(호스트 이름·CA·파일 행 ID가 그대로, 다른 파일 행과 CA·호스트 이름을 나누지 않음) 그 binding으로 들어온 로봇이 다른 `robot_id`를 알려도 받는다.
   - 연결·인증은 D-565와 같다. TCP 목적지는 binding 호스트 이름의 발견 결과이고, 인증서는 binding의 CA와 호스트 이름으로 검증한다. 코드 전 identity의 `tls_hostname`·`tls_ca_sha256`이 binding과 같아야 한다. `receiver_id`만 대조하지 않는다.
   - 코드 교환 뒤 `system/info`의 `robot_id`(같은 TLS)가 새 ID다. 그 ID가 다른 binding의 ID(배운 ID 또는 파일 행 ID)이면 `code_consumed`(reason `robot_id_conflict`)이고 토큰을 로그아웃한다. 등록부·명단의 ID와 겹치면 기존 `robot_id_conflict`다.
   - 저장: 같은 표에 새 ID를 쓰고, 명단 추가까지 성공하면 감사에 `tls_renumber`/`renumbered`, 대상 `옛ID->새ID`, 운영자 이름을 남긴다. 그 사이에 실패하면 행을 지우고 배운 ID를 옛 ID로 되돌린 뒤 같은 TLS로 토큰을 로그아웃한다. 그 뒤는 D-565와 같다(downgrade 방지 기록, 명단 추가).
   - 기록이 없는 대기 binding(처음 들어오는 로봇, 이 변경 전에 해제된 로봇)은 지금처럼 `robot_id`가 같아야 한다(`409 tls_binding_mismatch`, 코드는 나가지 않는다). 잘못 적은 binding을 잡는 D-565의 일관성 검사를 남긴다.
2. **binding의 우선순위.** binding 파일이 호스트 이름·포트·CA를 승인한다. Fleet이 배운 `robot_id`는 그 파일 행의 호스트 이름·CA 지문·`robot_id`가 기록 때와 같을 때만 그 행의 `robot_id`를 대신한다. 관리자가 파일 행의 CA나 `robot_id`를 바꾸면 파일이 이긴다(다시 승인한 것이다). 배운 ID가 파일의 다른 행 ID와 겹쳐도 파일이 이기고 Fleet은 뜬다. 번호를 바꾼 binding은 파일 행의 옛 ID도 계속 차지한다. 그 ID는 HTTP로 등록되지 않는다. 실행 중 파일이 바뀌면 거절하는 규칙은 그대로다.
3. **카메라는 명단을 따를 수 있다.** `site-cameras.yaml`의 source에 `robot_ids: enrolled`를 쓰면 그 source의 대상은 Fleet의 살아 있는 명단(`robots.yaml` + 등록부)이다. 등록·해제 때 `SiteRoster.sync`가 sighting과 추적 source를 함께 바꾼다. 마커는 YAML `robot_markers`에 적은 로봇은 그 값, 아니면 `rosy_NN`의 NN(40–49, D-562)이다. 모서리·장소 마커·YAML 값과 겹치는 번호는 배정하지 않는다. 목록을 적은 source는 이전과 같다.
4. **Vision은 Fleet이 준 마커를 쓴다.** Fleet은 기존 source 토큰 인증 `GET /api/fleet/detections/config`에 `robot_markers`를 더한다(API v1.174). Vision은 그 값으로 sighting과 설치 안내를 만들고, 읽지 못했거나 값이 틀리면(모서리와 겹침 등) YAML 값을 쓴다. `heading_edge`(스티커 위 = 로봇 앞)는 YAML 그대로다.
5. **갱신 기능 검사는 명단을 따른다.** `autoupdate.conf`의 `/api/fleet/state` 검사에 `"required_ids": "enrolled"`를 쓸 수 있다. 고정 목록이 없으니 번호를 바꿔도 `inventory-drift`가 생기지 않고, D-569의 전환 전후 기준선 비교(잃은 로봇은 롤백)는 그대로다. 카메라 source 검사는 목록만 받는다. `site_functional_setup.py`는 로봇 검사를 `"enrolled"`로 쓴다.

### 보안

- **신뢰의 닻은 그대로 로봇의 CA 키와 root 소유 binding 파일이다.** 새 CA를 승인하는 경로는 없다. Fleet DB는 이미 승인된 (호스트 이름, CA) 쌍의 `robot_id`만 바꾼다. 그 쌍을 TLS로 증명한 장치만, 운영자가 화면 코드로 승인한 등록에서만 바꾼다.
- **`robot_id`는 인증이 아니다.** D-565 보안 절과 같다. `receiver_id`·`system/info`는 로봇이 알리는 값이다. binding CA 키를 가진 장치는 어떤 ID든 알릴 수 있고, 이 결정은 그 ID를 받는 범위를 "이 Fleet에 등록되었던 binding"으로 넓힌다. 겹침 거절(등록부·명단·다른 binding)이 남는다. 로봇마다 자기 CA를 써야 한다는 조건도 남는다.
- **보안 검토(2026-10-09, 독립 리뷰).** CRITICAL·HIGH 없음. MEDIUM 2건을 고쳤다: 자격을 등록 해제 감사의 ID만으로 판단하던 것(→ 호스트 이름·CA·파일 행 기록), 저장 실패 때 바뀐 binding이 남고 토큰 로그아웃이 실패하던 것(→ 되돌린 뒤 로그아웃). LOW 중 충돌 때 시작 거절(→ 파일 우선), 파일 재승인을 덮던 것, CA를 나누는 행, 옛 ID의 HTTP 재사용을 고쳤다. 남은 LOW: 등록된 HTTP 로봇이 스스로 고른 ID로 `enrolled` source의 마커 번호를 받는다(표시·지도 자세 입력, 명령 경로 아님).
- **남는 위험.** (a) Fleet DB에 쓸 수 있으면 `robot_tls_renumber` 행으로 승인된 binding의 ID를 바꿀 수 있다. 같은 DB가 이미 봉인된 토큰과 downgrade 방지 기록을 들고 있고, CA·호스트 이름은 바꾸지 못하므로 새 장치를 들이지는 못한다. (b) 등록 해제된 로봇은 운영자가 그 화면 코드를 입력하면 다른 번호로 돌아올 수 있다. 영구히 내보낼 로봇은 관리자가 binding 행을 지운다.
- **카메라 마커는 표시와 지도 자세 입력이다.** 명령 경로가 아니다. Fleet이 주는 값은 source 토큰으로 인증된 요청에만 가고, Vision은 모양이 틀린 값을 버린다.

### 관계

| 결정 | 이 기록과의 관계 |
|---|---|
| D-565 | 운영 절차 3·4단계(파일 수정, Fleet 재시작)를 등록되었던 binding에 한해 없앤다. 대기 binding 선택·TLS 확인·HTTP 거절은 그대로 |
| D-562 | 마커 id = 로봇 번호를 Fleet이 기본값으로 적용한다 |
| D-569 | 회귀 기준선은 그대로이고, 로봇 ID 고정 목록을 없앨 수 있게 한다 |
| D-361 | 등록부가 명단의 주인이라는 원칙을 카메라와 갱신 검사까지 넓힌다 |

### Alternatives

| 대안 | 판단 |
|---|---|
| binding 전체(CA PEM 포함)를 Fleet DB로 옮기고 파일은 처음 한 번만 가져온다 | 보류: 번호 바꾸기에는 ID만 필요하다. CA가 DB에 들어오면 DB 쓰기만으로 새 장치를 승인할 수 있고, 은퇴·CA 교체용 삭제 경로가 새로 필요하다 |
| 광고된 CA를 화면 코드로 승인(TOFU) | 기각(D-565와 같은 이유). 새 로봇의 CA 승인은 여전히 관리자 파일이다 |
| 모든 source가 자동으로 명단 전체를 따른다 | 기각: 카메라가 여럿인 사이트의 기존 의미가 바뀐다. `enrolled`를 적은 source만 따른다 |
| Vision에 새 Fleet 엔드포인트 | 기각: 이미 주기적으로 읽는 추적 설정에 필드 하나를 더하는 편이 짧다 |

### Consequences

- 번호 바꾸기 자격은 이 변경이 배포된 뒤의 등록 해제부터 기록된다. 그 전에 해제된 로봇은 D-565 sudo 절차를 쓴다.
- 사이트에서 한 번만 바꾼다: `site-cameras.yaml`의 `robot_ids`를 `enrolled`로(마커 예외만 `robot_markers`에), `autoupdate.conf`의 로봇 `required_ids`를 `"enrolled"`로. 그 뒤 번호 바꾸기는 콘솔 등록 해제 → 로봇 번호 변경 → 콘솔 화면 코드 등록이다.
- 새 TLS 로봇(처음 보는 CA)은 여전히 관리자가 binding 파일에 행과 CA를 넣는다.
- Vision 추적이 꺼진 source는 Fleet 설정을 읽지 않으므로 YAML 마커만 쓴다.
- 새 감사 동작 `tls_renumber`, `detections/config`의 `robot_markers`(v1.174 additive), `autoupdate.conf` 값 `"enrolled"`.
