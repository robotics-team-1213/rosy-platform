## D-124 대시보드는 AP on/off와 Wi-Fi 연결을 Host Agent로 확인하고 적용한다

**Status:** Accepted (2026-09-18). 운영 네트워크 카드. nmcli 는 CORE 가 아니다. "업링크 손실로 AP 를 여는 것도 금지" 한 문장은 D-176·D-919의 fallback AP(업링크 없음 120 s 뒤 자동)가 대체했다(2026-11-01 표기).

**Context:** D-26 은 `SITE_STA`(AP 꺼짐)와 `RELAY_AP_STA`(AP 켜짐)를 장비 모드로
둔다. 대시보드 네트워크 카드는 그 모드·SSID·주소를 보여야 하고, 관리자가 AP를
켜거나 끄고 사업장 Wi-Fi에 다시 붙을 수 있어야 한다. 기존 카드는 자유 텍스트
`profile_id` 만 보냈고, Host Agent `network.status` 는 raw `nmcli` 덤프라
모드를 만들지 못했다.

PSK 를 CORE 로그·오버레이·GET 응답에 남기면 D-22 의 인터넷 표면이 비밀을
보관하게 된다. 그렇다고 대시보드에서 연결을 막으면 운영자가 말한 "확인하고
수정·처리"가 빠진다.

**Decision:**

- `network.status` 는 구조화한다: `mode`, `ap_active`, `ssid`, `ipv4`,
  `default_route`, `dns`, `profile_id`. PSK 필드는 없다
- 관리자 `POST /api/v1/host/network/mode` `{mode: SITE_STA|RELAY_AP_STA,
  confirmed: true}` → Host Agent `network.set_mode`. AP 끄기는 site 프로파일
  up + relay down, AP 켜기는 relay up
- 관리자 `POST /api/v1/host/network/connect` `{ssid, psk, confirmed: true}` →
  Host Agent `network.connect`. PSK 는 한 번 통과하고 NM 에만 남는다. CORE 는
  저장하지 않고 응답에서 제거한다. 감사는 키를 적색한다
- `confirmed` 가 아니면 Host Agent 가 거절한다. CORE 는 `nmcli` 를 부르지 않는다
- 대시보드는 AP 켜기/끄기 버튼과 SSID·암호 폼을 쓴다. GET 으로 암호 칸을 채우지
  않는다. 등록 프로파일 적용은 고급 경로로 남긴다
- 첫 부팅 설정 AP(PROVISIONING_AP)와 복구 AP는 이 카드가 열지 않는다. 업링크
  손실로 AP 를 여는 것도 금지(D-26 NETWORK_HOLD)

**Alternatives:** 프로파일 id 만 받기 — 운영자가 AP/SSID 를 다루지 못한다.
CORE 가 nmcli 를 직접 부르는 안은 D-22.

**Consequences:** 연결 적용 중 대시보드 세션이 끊길 수 있다. RELAY 가 켜져 있으면
로봇 AP 로 다시 붙을 수 있다. SITE_STA 에서 SSID 를 잘못 넣으면 현장 접근이
끊긴다. 그래서 확인이 필수다. 실제 라디오 성공은 DEVICE 증거다.

**Validation / Transition:** `test_host_agent.py`, `test_host_cards.py`,
`test_dashboard.py`.

**References:** D-22, D-26.


---
