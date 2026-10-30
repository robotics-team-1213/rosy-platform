# Pilot 모델 PC 수집 후속

## 판정과 이전 근거

모델 PC의 검증된 원본·영상·운영 Learning pending 연결은 수용했다.
현재 장치 가용성, 물리 이동, G4 승인·사람 라벨·학습·승격은 별도다.
소스 수정·원격 회귀·서명 sequence 44 적용은
[이전 기록](../pilot-learning-collection-2026-10-29/result.md)에 있다.
이 후속은 fix/pilot-learning-collection에서 작성했으며 로컬 main 착지와 push를
완료했다고 주장하지 않는다.

## 새 장치와 연결

사용자가 현장 연결·감독 가능 상태를 알리고 mDNS 조회를 요청했다.
승인된 현장 PC의 현재 _rosy._tcp 광고에서 rosy-pinky-geg6를 찾았다.
기존 운영자 SSH host-key pin과 장치 이름·namespace rosy_42·설치 릴리스
2026.10.29-001, CORE/I/O active를 확인했다. 이전 두 이름의 조회 실패로
이 새 장치까지 오프라인이라고 판단할 수 없었다.

실제 정지·제어 quiescence·녹화 idle 확인 후 설치된 서명 native TLS helper를
정상 tls-maintenance claim과 중지된 runtime에서 실행했다. 설치 릴리스 검증,
기존 신뢰 보존 검사와 TLS 검증을 거쳐 runtime을 복원하고 claim을 해제했다.
비영 속도 명령이나 G4 승인은 만들지 않았다.

모델 PC에는 먼저 설치된 geg6 수신 env·토큰·CA가 있었다. 설치 시도는 기존
파일을 거절했고 이 파일들을 덮어쓰지 않았다. 실제 구성된 HTTPS 접속점에서
Operator 인증과 녹화 목록 조회 200을 확인했다. 직접 CORE 접속점에 gateway의
CA를 대입한 실패는 구성된 수신 경로의 실패가 아니었다.

생산자 경로는 모델 수신기 → 장치 TLS media gateway 8443 → native CORE
HTTPS 8080이다. 다른 작업자의 동시 운영 기록인
fix/robot-local-video-recovery의 docs/validation/robot-local-video-recovery-2026-10-29/result.md는
native CA와 인증서 이름을 검증하는 HTTPS upstream 복구와 200을 기록한다.
읽기 전용 독립 검토에서 그 근거와 CORE의 archive 전달 전·전달 중 정지 검사를
확인했다. 이후 장치 단절로 설치된 gateway 설정의 현재 byte 대조는 미확인이다.

## 실제 수신·검수 대기 등록

rosy-pilot-fetch@geg6.service의 exit 0, 두 원본 manifest와 paired video receipt를
확인했다. 같은 승인된 signed model-code executor와 collection flock으로
로컬 처리·운영 등록을 실행했다.

| 녹화 | sidecar 프레임 | accepted intent가 있는 프레임 | accepted 비영 cmd_vel 프레임 | pending 추가 |
|---|---:|---:|---:|---:|
| 20261029T133513Z_rosy_42 | 4,809 | 4,002 | 3,233 | 919 |
| 20261029T134518Z_rosy_42 | 52 | 21 | 11 | 6 |

위 수는 프레임 수이며 고유 명령 횟수나 독립적인 물리 이동 관측이 아니다.
첫 반복 요청은 다른 legacy job 때문에 exit 3으로 보류됐다. 다음 두 정상 실행은
각각 두 녹화 모두 added 0, exit 0이었다. 보류를 성공으로 세지 않는다.

독립 DB·파일 검사에서 다음을 확인했다.

- pending 총 6,007장: 원래 53장, 과거 자료 복구 5,029장, 이번 두 녹화 925장.
- 준비 catalog 13건/6,316행, 준비 파일 6,355개의 해시와 원본 manifest 해시 일치.
- 신규 검수 저장소 이미지 5,954개가 DB의 해시와 일치.
- 기존 53장의 review/status/version·masks·events·pixel_events digest 불변.
- 실제 workspace 클래스 결속 유지, 사람 승인과 원본 영상 source verification flag 부여 없음.
- 예전 세션 신원 충돌 한 건 362행은 등록 차단·원본 보존 상태 유지.

새 준비 PNG 한 장을 해시 확인 후 별도 scratch로 복사해 실제 차선 영상을
확인했다. 원본 이미지를 Git에 넣지 않았다. 이 표본 검사를 지속 스트리밍
FPS·레이턴시 수용으로 확대하지 않는다.

영수증은 C:/DevTemp/pilot-collection-deploy 아래의 bulk-frozen-acceptance.json과
geg6-and-bulk-acceptance.json이다. 지문은 reports.sha256에 있다.
이전 3413b02046의 추가 기록 검사는 333 passed/0 skipped/exit 0/NEW 0이었고,
그 로그도 같은 scratch의 final-record-corrected/run-1.txt에 보존했다.
그 회차를 최신 main 착지 검증 결과로 바꾸어 쓰지 않는다.

## 현재 미확인 범위

2026-10-29 14:38Z 무렵부터 새 장치도 mDNS와 직접 SSH에서 보이지 않았고,
이후 구성된 HTTPS 경로도 host-unreachable로 관측됐다. 현장 전원·현재 Pilot
연결 상태를 사용자에게 요청했다. 단절 원인과 복구는 미확인이다.
이 작업에서 로봇 재부팅이나 비영 속도 명령은 보내지 않았다.

CE: 새 교훈 기록 —
[현재 광고와 접속 기록 확인](../../solutions/workflow-issues/robot-inventory-and-live-mdns-discovery-2026-10-30.md).
새 장치 발견·기존 pin 확인·925장 등록·재등록 0이 근거다.
이후 단절과 예전 362행 신원 충돌은 미해결 상태로 유지한다.
