## D-499 관제는 사이트 경로와 로봇 링크를 이미 있는 조회의 결과로만 보여 준다

**Status:** Proposed (2026-10-07, 사용자 개념 확인. 구현 전. 로컬 미리보기는 제품이 아니다)

## 배경

- Rosy Console(`shared/web/surfaces.yaml`의 `console`)이 `site-monitoring`을 이미 소유한다. 역할은 사이트 로스터와 여러 로봇 모니터링이다(D-370). 새 앱·새 로그인·새 서버는 만들지 않는다(D-377).
- 화면 자리는 D-493이 정한 지도 3 : 오른쪽 열 2 안에 있다. 오른쪽 열은 예외 큐, 등록 로봇, 카메라 썸네일, 대형이다. 이 결정은 그 분할을 바꾸지 않고, 등록 로봇 칸 안에서 목록 위에 경로 한 블록을 더한다.
- 로봇이 오프라인이면 카드는 지금 `online: false`와 `error`만 보여 준다. `GET /api/fleet/state`의 로봇 행은 gather 성공이면 `online: true`이고, 예외면 `online: false`와 `error`다(`operations/fleet/fleet/server/console.py` `snapshot`). `error`는 로봇이 HTTP로 답하면 `reachable: true`와 코드, 그 외에는 `reachable: false`와 예외 클래스 이름이다(`console_view.py` `_error_of`). 4xx/5xx는 `RobotApiError`다(`transport.py`).
- 그 한 비트는 서로 다른 고장을 같은 "오프라인"으로 붙인다. 고정 주소가 다른 곳에서 보이면 `address-drift.js`가 이미 한 줄을 붙인다(`seen_at_other_address`, `outside_scanned_subnets`). 평문 `http`로 등록된 베이스 URL이 TLS만 받는 CORE에 닿지 못하는 경우는 수송 예외라 `reachable: false`가 되고, 주소가 죽은 것과 구분되지 않는다.
- 사이트 프로세스의 `/healthz`는 `{"status":"ok"}`만 돌려주는 생존 확인이다(`static_routes.py`). 프록시·Fleet·Vision의 바이트나 컨테이너 상태는 관제 API가 아니다.
- 로봇 Wi-Fi의 모드·SSID·주소 변경은 로봇 화면의 네트워크 카드다(D-124). 콘솔은 `nmcli`를 부르지 않고 AP를 켜지 않는다(D-176, D-26).

## 결정

1. **보여주는 곳은 지금 관제 하나다.** 등록 로봇 패널의 목록 위에 사이트 경로 블록을 두고, 각 로봇 카드에는 문제가 있을 때만 링크 한 단어를 더한다. 비상 정지·목표·임무·주소 옮기기의 자리는 그대로다.
2. **사이트 경로는 콘솔이 이미 부르는 조회 셋이다.** 새 경로는 없다.
   - 프록시: 기존 `GET /healthz`가 200이고 본문이 `{"status":"ok"}`이면 정상. 문서가 한 번 열렸다는 사실만으로 정상이라 하지 않는다.
   - Fleet: 기존 `GET /api/fleet/state`가 HTTP 상태와 함께 끝나면 정상이다. 200과 401 모두 Fleet이 답한 것이다. 401은 지금처럼 관제 토큰 안내로 남고, Fleet 끊김이 아니다. 연결이 끝나지 않으면 끊김이다.
   - Vision: 기존 `GET /api/fleet/vision/sources`가 끝나면 응답이다. 200이고 소스가 있으면 그 이름을 적는다. 200이고 비어 있으면 없음이다. 연결이 끝나지 않으면 끊김이다.
   - 바이트 그래프, Docker 상태, 공유기 통계는 이 블록에 넣지 않는다.
3. **로봇 링크는 gather와 주소 판정으로만 고른다.** 로봇마다 새로 PROBE하지 않는다. `GET /api/fleet/state` 로봇 행에 `link` 하나를 더한다. 값은 닫힌 집합 `up`, `unreachable`, `moved`, `tls-refused`, `protocol`뿐이다. 구현 커밋이 이 행을 적는 Fleet API 문서를 같이 고친다(D-18). CORE 경로는 늘리지 않는다.
4. **고르는 순서는 고정이다.**
   - gather가 성공하면 `up`이다. 주소 배너가 따로 떠 있어도 링크 단어는 붙이지 않는다. 릴레이 증거가 정상일 때 태그를 생략하는 규칙과 같다.
   - gather가 실패하고 주소 상태가 `seen_at_other_address`이면 `moved`다. 문장과 "새 주소로 옮기기…"는 `addressReason`이 그대로 말한다.
   - `RobotApiError`이고 HTTP 상태가 401이면 `tls-refused`다. 다음은 지금 있는 관제 토큰이다. 망 수리로 적지 않는다.
   - 등록된 `base_url`의 스킴으로 로봇의 HTTP를 끝내지 못한 수송 실패는 `protocol`이다. 평문 `http`로 TLS만 받는 CORE에 물은 경우가 여기다. 다음은 등록된 base URL이지, 콘솔이 스킴을 스스로 바꾸지는 않는다.
   - 그 밖의 수송 실패는 `unreachable`이다. `outside_scanned_subnets`이면 지금 주소 문장을 유지한다.
   - 401이 아닌 `RobotApiError`에는 `link`를 넣지 않는다. 카드는 지금처럼 `error.code`를 보여 준다. 여섯 번째 단어를 만들지 않는다.
5. **브라우저가 예외 클래스 이름을 맞추지 않는다.** `protocol`에 해당하는 수송 예외의 집합은 Fleet 시험이 고정한다. 화면은 `link`만 읽는다.
6. **로봇 네트워크 카드는 로봇에 남긴다.** 콘솔은 `POST /api/v1/host/network/mode`와 `POST /api/v1/host/network/connect`를 얻지 않는다(D-124).

## 범위 밖

- 패킷 목록, 요청 폭포, 컨테이너 CPU·메모리·바이트.
- base URL을 http에서 https로 자동 수정하는 일. 등록과 재페어링은 D-361이 소유한다.
- `/healthz` 본문을 세 서비스 상태로 늘리는 일.
- 구현, 화면 코드, API reference 수정. 이 기록은 분류와 자리만 정한다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| 콘솔이 로봇 주소로 다시 접속해 링크를 재본다 | gather가 이미 한 결과와 어긋나고, 관제 PC에 두 번째 프로브가 생긴다. |
| 브라우저가 `error.code`의 예외 클래스 이름을 읽어 분류한다 | 라이브러리 이름이 화면 계약이 된다. 분류는 Fleet에 둔다. |
| Docker 건강과 바이트를 관제에 올린다 | 그 값은 사이트 호스트의 운영 통계이고 관제 API가 아니다. |
| 모니터링용 새 앱을 만든다 | `site-monitoring`의 주인이 이미 콘솔이다. |

## 결과

- 운용자는 "오프라인" 대신 주소가 이동했는지, 토큰이 거절됐는지, 스킴이 어긋났는지, 주소가 닿지 않는지를 한 단어로 본다.
- `up`인 로봇 카드의 모드·배터리·안전 줄은 그대로다.
- 이 결정은 구현 GO가 아니다. 장치·현장 수용을 대신하지 않는다.

**Validation / Transition:** 구현 커밋이 `link`의 다섯 값과 401이 아닌 `RobotApiError`에 `link`가 없음을 Fleet 시험으로 고정하고, 그 커밋에서 Fleet API 문서를 같이 고친다. 호스트 시험 통과는 장치 수용이 아니다.
