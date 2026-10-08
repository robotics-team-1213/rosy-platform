# Console 내비게이션 현재 후보 화면 재검증 — 2026-10-09

- 기준: `uiux/nav-current-g2-5f6a`, 분기 기준 `eb0d06b4b`.
- 발견: 이전 G2 fixture는 점유 지도·비용 지도를 반환하면서 `runtime.maps`에는 두 지도가 없다고 보고했다. 10초 갱신 뒤 Console이 지도를 비우는 정상 동작 때문에 지연·단절 캡처가 검은 빈 지도로 바뀌고, 안전 정지 행에서 시험이 실패했다.
- 수정: fixture의 지도 응답과 기능 플래그를 일치시키고 상태별 촬영 전 지도가 준비 상태인지 검사한다. 320px에서는 선택 전 좌표 행이 지도 아래 공간을 차지해 조작 안내를 밀었다. 좌표 행은 사용자가 지도를 선택한 동안만 보인다. Esc로 선택을 지울 때 공용 지도 콜백도 선택 없음으로 알린다.
- 화면 확인: 실제 FastAPI 정적 자산과 합성 CORE 응답으로 1366×768, 390×844, 320×568을 촬영했다. 정상·지연·연결 끊김·정보 없음·안전 정지 15행에서 브라우저 오류 0, 가로 넘침 0, 비상 정지 가시 상태를 확인했다. 추가로 지도/경로 ID 불일치·위치 불확실·SLAM 세션 대기/조회 실패 캡처도 남겼다. 320px 정상 화면에서 레이어 버튼 시작은 779px에서 719px로 올라갔고 지도 시작 위치 241px는 유지됐다.
- 검증: 10월 9일 최종 소스에서 내비게이션 매트릭스·키보드 좌표 선택·Esc 해제·지도 읽기 **4 passed**, 패키지·웹 예산·문서 배치 **35 passed/1 skipped**. 두 로그 모두 `known_failures.py` 0 NEW. 변경 JS `node --check` 통과, Impeccable detector `[]`, 하네스 lint 0 error/기존 갱신 경고 23건, `git diff --check` 통과.
- 원시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-08--nav-current-g2-5f6a/`의 `run-verified.txt`, `run-structure.txt`와 `evidence/verified/`. 변경 전후 비교는 `evidence/after/`(좌표 행 변경 전)와 `evidence/verified/`(변경 후)다. 최초 모순 fixture 실패와 빈 지도 캡처는 `run.txt`, `evidence/navigation-stage/`에 보존했다. 중간 실행 `run-final.txt`에서 Esc 해제 결함이 발견됐고, 공용 지도 수정 뒤 최종 묶음으로 재검증했다.
  - 최종 `operator-console-navigation-320x568.png` SHA-256 `452914EAF978BAAB0144E74CF0B5D2FC6223A9B5688F435A049B592C20A68109`
  - 최종 `operator-console-navigation-390x844.png` SHA-256 `02BFF338C1315CBB08B040532F9CA8A6195CF5BDFFFECBDB8A5D55A95B78F6F7`
  - 최종 `operator-console-navigation-1366x768.png` SHA-256 `6AEA2B42CE971FF720B123EB1873A8B59688E8DA7E0BB82B768F1BCE2B984C89`
  - 최종 `navigation-stage-matrix.json` SHA-256 `60EFAA511FB9974B4A9CEABCB11CDF7629124E2D6C300A27C84F0488F57D5307`
- 판정: Console 내비게이션의 위 15개 합성 LOCAL 행은 통과. 전체 D-153 G2/G3, 설치 이미지, 실제 지도·경로 추종·SLAM readback, DEVICE/FIELD는 계속 HOLD.
