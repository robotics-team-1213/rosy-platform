# 8kcn 개발 연결 모드 전환과 기기 이미지 cryptography 결함 (2026-10-06)

## 무엇을 했나

rosy-pinky-8kcn(192.168.1.202)을 D-432 개발 연결 모드로 전환했다(사용자 지시, D-471 방향).

변경 세 곳(모두 백업 있음: `runtime.env.bak-d471`, `rosy.yaml.bak-d471`):

1. `/etc/rosy/runtime.env`: `ROSY_DEPLOYMENT=device` → `development`
2. `/var/lib/rosy/core/.rosy/rosy.yaml` `network.connection_mode: development` 추가
3. 같은 파일 `network.tls.ca_file` 줄 삭제(아래 결함 때문 — 앵커는 피어 페어링용이고 개발 세션엔 불필요)

결과: `GET /api/v1/auth/connection` → `{"mode":"development","robot_id":"rosy_60","transport":"https"}`.
`POST /api/v1/auth/development-session` → 1시간 운영자 토큰(pair-development) 정상 발급·whoami 확인(검증용 토큰은 만료 방치).

## 발견한 결함 (release 2026.10.05-042)

`network.tls.ca_file` 이 있는 상태에서 개발 모드로 시작하면 CORE가 시작부터 죽는다:

```
core_api_web/api/peer_pairing/tls_anchor.py:38 ValueError: cryptography>=42 chain verification is required
→ api_tls.py:46 ValueError: configured bootstrap CA does not validate the TLS leaf
```

- 기기 이미지의 python3 에 `cryptography>=42` 가 없다(`x509.verification` import 실패 — tls_anchor.py 주석도 "current device image" 라고 적어 둔 상태).
- paired 모드에서는 같은 ca_file 로 시작이 잘 되므로, 이 결함은 **개발 모드 시작 경로에서만** 앵커 검증이 걸리는 것으로 재현됐다(원인 정확한 분기는 이미지 수정 때 다시 본다).
- 우회: ca_file 을 지우면 개발 모드가 HTTPS 로 정상 기동한다(위 3번). 대가 — 이 로봇의 피어 페어링 앵커(`GET /peer-pairing/identity`)가 사라진다. 태블릿의 저장 승인·세션 재사용은 영향 없고, 개발 모드에서는 앱이 개발 세션으로 접속하므로 실사용 문제는 없다.
- 근본 수선: 장치 이미지에 `cryptography>=42` 싣기 + paired/dev 양쪽 시작 경로의 앵커 검증 조건 통일(별도 작업, 이 기록이 증거).

## 남은 것

- "개발 모드에서 콘솔/SSH 자격을 화면에 보여준다"(사용자 요청 2026-10-06)는 미구현 — 대시보드 개발 세션 원클릭·임시 SSH 비밀번호 표시 등 설계 필요.
- rosy-pinky-9dfk 는 전환하지 않았다(paired 유지).
- 전환 복구: 두 백업 파일을 원위치에 복사하고 `sudo systemctl restart rosy-core`.
