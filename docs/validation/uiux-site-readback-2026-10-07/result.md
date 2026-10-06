# ROSY UI/UX 현장 PC 읽기 전용 재확인 — 2026-10-07

[UI/UX 회차 평가](../uiux-surfaces-2026-10-06/README.md)의 실제 사이트 mDNS 기록을 현재 시점에 재확인했다. **2026-10-07 06:53 KST**, 기존 사이트 PC에 읽기 전용 SSH로 접속했다. 로컬 후보는 `main` `7b423c372`였다.

| 관찰 | 결과 |
|---|---|
| 현장 Fleet·Vision·proxy 이미지 | 세 컨테이너 모두 `e64815c5137e91aee261cee9569cd592e74afed0` 태그. 로컬 후보와 다르다. |
| 사이트 mDNS | Avahi 활성, 사용자 발견 브리지 timer 활성. LAN에서 두 로봇의 `_rosy._tcp` 광고가 보였다. 광고의 `CORE_READY`는 광고된 값이며 로봇 런타임 검증은 아니다. |
| Fleet 컨테이너 내부 | 실제 서비스 UID `10001`에서 두 로봇의 `.local` 이름과 `fleet`·`vision`·`proxy` 서비스 이름이 풀렸다. |
| 개발 PC | 다른 네트워크에서 사이트 `.local` 이름이 풀리지 않았다. 사이트 LAN의 발견 실패로 해석하지 않는다. |

원본: `X:/DevTemp/projects/rosy-platform/2026-10-07--site-uiux-readonly/site-readback.txt` (SHA-256 `91ee4a6214db9421276f1bed145d4a4f142b5ce4a1bbd732d3914992be1896a1`). 원본에는 사설 주소와 장치 이름이 있으므로 저장소에는 넣지 않는다. 점검은 `docker ps`, `systemctl`, `avahi-browse`, Fleet 컨테이너 UID의 `getent`만 사용했으며 설정이나 장치 상태를 바꾸지 않았다.

**판정: UI/UX HOLD.** 이 결과는 이름 발견과 설치 이미지 식별만 증명한다. 현재 `main` UI의 현장 설치·인증된 로봇 목록/지도·카메라와 실제 로봇 상태 readback·[사용자 G3 독회](../uiux-surfaces-2026-10-06/operator-walkthrough.md)는 확인하지 않았다. 따라서 구형 사이트 화면을 현재 후보의 G2/G3로 승격하지 않는다.
