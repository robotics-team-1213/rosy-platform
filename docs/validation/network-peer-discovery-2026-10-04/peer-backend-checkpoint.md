# D-452 역할 catalogue와 호스트 scanner — 소스 검증

2026-10-04, `integrate/ui-ship`. 기존 robot enrollment와 별도 역할 목록을 추가했다.

- 인증된 viewer `GET /api/fleet/peers`, dedicated scanner만 scan 제출 가능.
- 로봇·Fleet·Vision·Dock·Signal·실제 모델 SSH의 6역할. listener 없는 앱은 승인된
  source/session presence이며 광고 endpoint를 만들지 않는다.
- 같은 망은 bounded Avahi scan, 다른 망은 기존 등록 endpoint와 metadata-only 승인
  directory를 사용한다. 기존 토큰·endpoint·등록·명령 경로를 바꾸지 않는다.
- enrollment·directory·등록 endpoint의 hostname 소유가 다르면 mDNS row는
  conflict/unapproved/peer_id=null이다. 마지막 소유자 주장으로 덮어쓰지 않는다.
- directory는 최대 64행·1 MiB, credential/extra·중복 키/소유·허위 live 상태를 거부한다.
  IP-only legacy profile과 현재 미해결 DNS도 승인 신원으로 표현한다.
- 한 scan은 전체 12초·1 MiB·64개 예산이다. 로봇을 두 배열에 중복 넣지 않고, TTL 45초,
  동일 scan commit 순서를 유지한다. 종료 시 소유한 child를 kill/reap한다.
- DiscoveryScanPayload는 작은 protocol owner로 추출하고 schemas import API는 유지한다.

검증: 독립 SPEC·Quality·Safety source PASS. backend/scanner focused 104 PASS,
관련 넓은 범위 182 PASS/기존 POSIX SKIP 3. 추가 실패 한 건은 현행 SDK namespace가
빠진 검증 환경을 보완한 해당 범위에서 20 PASS였다. 최종 충돌 회귀 포함 catalogue/API
24 PASS, schema/metadata 37 PASS. Linux 실제 child 시간·출력 예산/회수 검사는 11 PASS.
첫 Linux drvfs fd-capture 검증 도구 오류는 원본을 보존하고 capture=sys로 해당 범위만
재실행했다. 제품 동작을 약화하지 않았다.

Fleet image는 pinned zeroconf 의존성과 import sanity를 추가했다. Windows/Linux Python
실제 dependency import는 PASS지만 Docker bridge의 실제 UID 10001 LAN 전달 수락은
별도다. 호스트 Avahi 목록을 container 검색 성공으로 대신하지 않는다. 기존 authenticated
host scanner 경로를 활용해 namespace 차이를 처리한다.

이 기록은 새 UI 화면 수락, 최종 원격 CI, signed candidate 배포, operator 로그인,
다른 망의 실제 연결이나 LAN airtime 측정의 증거가 아니다. 원시 로그·source hash receipt는
X 드라이브에 보존했다. Dock·Signal 제어/충전/감독 URL은 변경하지 않았다.
