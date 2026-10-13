# Discord 연결과 Fleet 파이프라인 점검 증거

2026-10-12. 설계 source `b4abc933f4`, 점검 시작 `c41dfcb0a`.

## 실제 Discord 연결

Playwright의 사용자 로그인 계정에서 기존 지정 팀/채널을 확인했다. `ROSY Fleet` incoming webhook을 만들고 저장 후 reload하여 이름/대상 채널을 readback했다. URL은 비공개 X 파일에 저장하고 현재 사용자/SYSTEM으로 파일 접근을 제한했으며 공개 문서·git·출력에 넣지 않았다.

사용자가 승인한 연결 확인 문장 1건을 `wait=true`, mentions 없음으로 전송했다. HTTP 200의 메시지 ID·대상 채널·내용을 확인하고 로그인된 채널 화면에서 같은 내용을 직접 readback했다. 원시 receipt와 화면은 비공개 `discord-channel-setup` X 세션에 있다. 이 전송은 Fleet outbox·기명 인수·장치 실행 경로가 아니다.

사용자 요청 범위의 Rosy Fleet Bot application을 생성했다. Discord의 사람 확인은 사용자가 직접 수행했다. application UI와 Bot 페이지를 읽고 Presence/Server Members/Message Content intent가 모두 OFF인 것을 확인했다. 서버 설치·token 발급·Gateway·Fleet principal 연결은 수행하지 않았다.

## 소스 점검·독립 검토·원격 계약

`site_auth`, Mission create/resolve/admit, 구조화 intent do, work read, incident handoff/notifications, Console 사건 표시와 execution goal/progress를 대조했다. 일반 Mission 동일 owner와 Cell Job 별도 기명 approver를 확인했으며, JSON intent를 자연어 parser로 표시하지 않는다. 없는 Bot intake·권한 연결·대화 결과 원장은 D-669 Proposed와 계획에서 공백으로 기록했다.

독립 reviewer `safety_structure_review`는 권한 충돌 없음과 두 보완을 확인했다. Fleet이 authenticated transport identity에서 principal을 결정하고 공용 operator/site-console/development fallback을 거절하며, 다른 owner 승인 거절을 일반 Mission에만 적용하도록 문서를 보완했다. 장치 Safety source는 변경하지 않았다.

`b4abc933f4` AI PC 원격 문서 계약 terminal exit 0, known failures NEW0/known0:

```powershell
python tools/remote/remote_pytest.py --log-dir <X-session>/logs/contracts -- test/test_harness_contracts.py test/test_network_topology_contracts.py -q
python test/known_failures.py <X-session>/logs/contracts/run-1.txt
```

로컬 harness lint는 오류 0이며 오래된 last_verified 경고는 남는다. D-668은 동료가 선점했고 이 브랜치에는 없으므로 임시 gap으로 기록했다. D-669 ADR과 Log는 같은 커밋이다. 원격 pytest만 실행했으며 노트북 pytest는 실행하지 않았다. 최신 main 착지·결과 문서 재검증은 별도 land receipt로 확인한다.

## 남은 조건

Fleet 기명 운영자 ID/계정 연결, 실제 HTTPS Console와 실행 source·비공개 설정, Bot 수신·원장·후보·승인·대화 reply 구현, 실제 outbox→인수→목표 근거는 아직 없다. 실제 launcher/provider/FIELD와 로봇 motion은 HOLD다. source 설계·문서가 새로운 Discord 실행 권한을 활성화하지 않는다.
