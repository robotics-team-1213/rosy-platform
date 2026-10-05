# 등록된 로봇의 HTTPS 연결 설정

이 설정은 이미 암호화 등록부에 있는 로봇의 전송만 바꾼다. 로봇을 등록하거나
승인을 발급하지 않는다. `robots.yaml`에 같은 로봇을 추가하지 않는다. 기존 SQLite
등록 행, 암호화 자격, credential key, named principal, 토큰·발급자 만료를 유지한다.
만료된 로그인은 이 설정으로 갱신되지 않는다. D456의 Fleet 장기 승인 관계·키 증명
세션 발급을 완료한 것으로 표시하지 않는다.

## 관리자가 준비할 공개 파일

실제 등록된 `robot_id`와 등록부 `hostname`을 확인한다. 로봇의 관리된 TLS CA를
승인된 전달 경로로 받아 공개 설정 디렉터리에 둔다. 광고에서 CA를 내려받아 승인하지
않는다. CA 지문은 **DER 인증서의 SHA256**이며 PEM 파일 바이트의 SHA256이 아니다.
호스트 이름은 해당 등록 로봇의 `.local` 이름 및 실제 인증서 SAN과 같아야 한다.
다음 형식의 공개 JSON을 `enrolled-tls-bindings.json`으로 만든다.

```json
{
  "version": "rosy.enrolled-tls/1",
  "robots": [{
    "robot_id": "rosy_01",
    "hostname": "robot-example.local",
    "port": 8080,
    "tls_ca_file": "/run/rosy-config/robot-01-ca.pem",
    "tls_ca_sha256": "관리자가 확인한 64자리 소문자 DER SHA256"
  }]
}
```

예시의 ID·이름·지문을 그대로 활성화하지 않는다. 비밀 token·발급 코드·개인 키는 넣지
않는다. 파일은 root 또는 실행 UID 소유이며 그룹·다른 사용자 쓰기가 없어야 한다
(예: root:root 0644, 공개 디렉터리 0755). CA도 같은 조건이다. 심볼릭 링크·하드링크·
여러 CA 묶음·누락·만료·지문 불일치·등록되지 않은 ID는 거절한다. 기존 secrets 및
DB 경로·권한을 바꾸지 않는다.

## 기존 사이트 스택에 적용

관리자가 기존 `site.env`에 한 줄을 설정한다.

```text
ROSY_SITE_ENROLLED_TLS_BINDINGS_FILE=/run/rosy-config/enrolled-tls-bindings.json
```

공개 설정 디렉터리는 이미 `/run/rosy-config:ro`로 마운트된다. 기본 Compose와 기존
pairing Compose 모두 해당 값만 Fleet의 `ROSY_ENROLLED_TLS_BINDINGS_FILE`로 전달한다.
CLI의 명시적 `--enrolled-tls-bindings-file` 값이 환경 기본값보다 우선한다. 빈 값은
기존 **TLS로 지정되지 않은** HTTP 등록에만 기존 동작을 유지한다. 서명된 후보의
명령·파일을 직접 고치거나 새 overlay·unit를 만들지 않는다. 기존 승인된 스택 배포
절차로 반영해야 하며, 현재 SSH 계정에 root 설정 쓰기 권한이 없으면 관리자의 적용을
기다린다. 권한 우회를 하지 않는다.

## 확인과 실패 처리

광고는 위치 후보일 뿐이다. 각 전송에서 `.local` 호스트명과 저장 CA를 검증하고,
기존 공개 HTTPS identity의 `receiver_id`를 등록 ID와 대조한 뒤에만 자격이나 코드를
보낸다. HTTP와 WSS는 같은 신원·CA·새 발견 경로를 쓴다. DHCP 변경은 암호화 등록
주소나 자격을 다시 쓰지 않는다. 코드 기반 기존 주소 이동은 TLS-bound 로봇에는
적용하지 않는다. DNS-SD에 저장한 이름의 광고가 없으면 그 HTTPS 이름의 호스트
Avahi 주소 하나를 쓰고, 저장한 포트와 CA 검증은 유지한다. 광고가 있는데
받아들이지 못하거나, 사설 LAN 주소가 하나가 아니거나, 인증에 실패하면 연결은
실패로 남고 HTTP로 내려가지 않는다.
기존 expiry/needs_new_code/address_changed 안전 HOLD를 자동 해제하지 않는다.

등록부와 동일한 ID 수, 자격 지문·만료·principal 보존, HTTPS 상태 GET 및 WSS 상태
읽기 성공을 각각 확인한다. 연결 복구 자체가 목표 재생·모드 변경·정지 해제를 뜻하지
않는다. 테스트나 소스 통과는 실제 사이트의 통신·운용 수용을 대신하지 않는다.

로봇을 정상 해제한 뒤에는 관리자가 그 ID의 공개 binding도 제거해야 한다. 등록되지
않은 binding이 남으면 다음 시작이 거절된다. 실행 중 binding/CA를 삭제·바꾸면
기존 HTTP로 돌아가지 않고 실패한다. 처음 지정한 origin·CA DER 지문은 기존 등록부에
공개 downgrade 방지 기록으로 함께 보존된다. 오프라인·만료·주소 변경·로그아웃 대기는
이 기록을 지우지 않으며, 로봇에서 로그아웃이 확인된 정상 등록 해제만 등록 행과 함께
원자적으로 지운다. 환경 설정을 비워 재시작해도 HTTPS로 지정된 등록은 HTTP로 돌아가지
않는다. 기존 기록과 다른 CA·origin을 설정하고 재시작해도 거절된다. 별도 키·호스트·CA
교체 작업은 구현하지 않았으며 이 변경의 범위가 아니다. 문제 해결을 위해 DB·marker·
credential key를 지우거나 TLS 검증을 끄지 않는다.
