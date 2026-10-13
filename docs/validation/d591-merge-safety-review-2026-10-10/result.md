# D-591 병합 커밋 D-430 독립 검토 — 2026-10-10

**판정:** `4c2b14ec8ec8`의 `Safety-Review:` trailer 누락을 사후 예외로 기록한다. 이 판단은 병합 커밋의 안전 태그 변경에만 적용하며, D-591의 장치·현장 안전 수용은 아니다.

- 첫 부모 `962247cff1fa`와의 `body_stop.py` diff는 주석의 로봇 이름만 바꾼다. 정지 간격 계산, E-Stop, 재무장, 명령 권한의 실행 코드는 동일하다.
- 둘째 부모 `21b2870221f6`에는 없는 `obstacle_blind_floor` 분기는 앞선 `94a6aa65ae31`에서 들어왔다. 그 커밋은 독립 `Safety-Review:` trailer를 가진다. 병합 자체는 새 정지 로직을 만들지 않았다.
- 후속 통합본 `af2933291f46`의 원격 AI·모델 PC 시험은 6,028 + 3,678 + 3,213 passed, `known_failures.py` 비교는 각 호출에서 0 new였다. 실행 기록은 `X:\DevTemp\lf-wall-gap\land2.log`(SHA-256 `592af281b4814b12573a30a1b5862972bfbaee91850827c4b8320555d90cfbf2`)와 `X:\DevTemp\land\fix-line-follow-wall-stop-gap\run-1-{1,2,3}.txt`에 있다.

D-591은 Pinky Pro에서 LiDAR 사각 바닥을 끄고 지연항을 0으로 낮춘다. 이 검토는 그 동작의 실물 정지 거리나 두 로봇 병렬 차선추종을 검증하지 않았다.
