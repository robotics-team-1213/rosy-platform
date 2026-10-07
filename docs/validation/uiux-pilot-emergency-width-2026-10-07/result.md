# Pilot emergency gate and read-only camera width — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** 기준 브랜치 `uiux/pilot-emergency-width`, 시작 커밋 `2238ab3f9`. 로컬 개발 서버의 합성 `EMERGENCY` 상태를 Chromium에서 확인했다. 실제 로봇의 `SAFE_STOP` readback은 아니다.

| 화면 | 2000×1200 | 1200×2000 | 390×844 | 320×568 |
|---|---|---|---|---|
| 진입 게이트 | 확인 | 확인 | 확인 | 확인 |
| 읽기 전용 카메라 | 확인 | 확인 | 확인 | 확인 |

수정 전 전화 폭에서는 카메라 상단의 안내·홈·비상 정지가 서로 좁혀져 글자가 세로로 깨지고 겹쳤다. 현재 화면은 안내를 한 줄에 두고 홈·비상 정지를 그 아래 같은 너비로 배치한다. 네 폭에서 비상 정지 가시성과 가로 넘침 없음, 전화 두 폭에서 안내와 행동의 비겹침·행동 폭 차이 ≤1px를 검사했다. 카메라를 열어도 구동 모드 변경 요청은 0건이고 `EMERGENCY` 상태가 유지됐다.

수정 전 전화 폭 재현 **2 failed / 2 passed** (`X:/DevTemp/pilot-emergency-width/red.txt`). 수정 후 관련 Pilot 브라우저 **12 passed**, D-153 G1 **90 passed**, 각각 `test/known_failures.py` **0 NEW**. 실행 기록은 `X:/DevTemp/pilot-emergency-width/{related,g1}.txt`; SHA256은 각각 `a6e18d451be24df4d92fdae5ed199f5abbcb10b299187689d7f7d0c7bf51154bb`, `533a283de78d7e8a5b8097b6ff30fe672f6a32d647d8703fa41d276b36942c01`이다.

원본 8장: `X:/DevTemp/pilot-emergency-width/shots/pilot-emergency-{gate,camera}-{2000x1200,1200x2000,390x844,320x568}.png`. 320×568 카메라 PNG SHA256 `1defe24c79b05a54b68e37a708b57d46254cbd817b3c63e4d9667cac4ffb67f0`. 이 캡처는 fixture 기반 LOCAL 배치 근거다. Pilot의 다른 선언 상태·폭, 설치본과 실물 정지 readback, 사용자 G3 여덟 항목은 남아 있다.
