# Discord Gateway 후속 검증

2026-10-12. D-671 기록 당시 미완료였던 토큰·identity·수신 source에 대한 후속이다.

## 실제 계정·연결

사용자가 Developer Portal MFA를 완료한 뒤 Bot 토큰을 비공개 파일에 저장했다. Bot REST `/users/@me`, 지정 채널 metadata와 기존 사용자 메시지 조회에서 Bot ID `1558876462734385213`, guild `1558864656037056655`, channel `1558865220242378752`, `livsbittt`의 immutable user ID `1558838587133263894`를 확인했다. 연결 대상은 기존 Fleet principal `operator-livsbittt`다. 실제 runtime mapping은 아직 적용하지 않았다.

별도의 짧은 실제 Gateway 연결에서 READY와 서버 ID를 확인했고 즉시 종료했다. intents513, 새 메시지 전송0건이다. 이는 지속 Fleet worker/접수/작업 실행 증거가 아니다. private 토큰과 session ID는 공개 증거에 기록하지 않는다. Portal 토큰을 숨기고 임시 변경한 사용자 Developer Mode를 원래 OFF로 복원했다.

Tailscale이 다른 계정으로 바뀌어 첫 통합 시험의 SSH가 끊겼다. 사용자 복귀 선택 후 원래 tailnet과 세 ROSY PC 연결을 재확인했고 시험을 재개했다. 현재 현장 image는 다른 세션이 갱신한 `d0c4240d5f85`다. 기존 HTTPS Console에서 기명 operator cookie session HTTP200을 다시 확인했다. 이후 적용 시 현재 image/config/계정을 재확인해야 한다.

## Source·원격 시험

- RED `a258e67bbb`: 실제 Fleet bootstrap을 사용하고 missing `rosy_discord.gateway` collection NEW1 확인. 모델 PC22cores/8.3GB 배치 기준 통과.
- `38941ff24b`: 기본43 PASS/NEW0. 당시 runner는 D-568 fallback을 선택했으므로 자원 floor 통과 증거로 사용하지 않는다.
- `4b509b3a33`: session close4000/Resume old sequence, API pin, secret와 구조86 PASS+크기1NEW. 모델 PC22cores/8.1GB 배치 기준 통과. 크기 증가를 기존 실패로 등록하지 않았다.
- `2241b7b6bc`: 초기 Reconnect/지역 resume URL, handshake transient retry, token isolation, 실제 wheel/sdist/source-layout 설치와 secret/API/manifest68 PASS/NEW0. runner fallback 경고를 보존한다.
- 독립 `safety_structure_review`는 `2241b7b6b` source/Safety를 승인했다. 실측 Fleet53606(Discord191 포함), app906으로 기존 +150/모든 파일 상한/기존 추출 의무를 유지하는 제한 재판정에 동의했다. threshold 변경 이후 최종 구조·통합 재검증은 아직 남았다.

## 남은 gate

최신 main 착지, 실제 source image 빌드와 설치, private config/token mount 및 지속 Fleet READY, 사용자 mention 요청→기명 원장→실제 Console 읽기 수용이 남았다. D-669 후보/승인/결과 reply와 위험 사건 조치, provider/로봇 FIELD도 별도다. 로봇 명령/rearm/provider/push는 실행하지 않았다.

Protocol: [Discord Gateway](https://docs.discord.com/developers/events/gateway).

후속27fc0de96: 최종 수신/자격/구조/wheel+sdist 설치83 PASS/NEW0. threshold 재판정 회귀 통과. 배치 runner fallback을 기록하며 resource floor 수용 증거로 쓰지 않는다. main 착지/이미지/현장 수용은 아직 남았다.

후속b78edf399: optional private config/CLI/정식 Compose 연결 RED3NEW 후138 PASS/NEW0. 독립 검토가 source/Safety를 승인했고 Fleet53617(기존53606+150 내), CLI890/app906을 확인했다. Vision에는 Discord 파일을 mount하지 않는다. 운영은 D-301/D-437/D-441 CI와 서명 gate를 유지하며 source만으로 unsigned image를 교체하지 않는다.
