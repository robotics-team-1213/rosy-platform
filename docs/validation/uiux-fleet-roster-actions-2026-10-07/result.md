# Fleet 로봇 목록 행동 폭 — 2026-10-07

D-493 지도 우선 관제 화면의 현재 LOCAL 후보에서 320px 「전체 주행 취소」가 좁은 네 줄 버튼이었고, 390px에서도 「전체 로봇 보기」와 너비가 65px 달랐다. 취소 응답 뒤 320px에서는 결과와 「전체 로봇 보기」가 겹쳤다. 좁은 화면의 목록 머리를 동등한 두 칸으로 놓고, 취소 결과가 나타나면 결과·취소 버튼을 전폭으로 보인 다음 목록 버튼을 다음 전폭 줄에 둔다. 1920px 배치는 바꾸지 않았다.

기존 모바일 브라우저 검사에 폭·겹침 단언을 더하자 수정 전 **2 failed**와 취소 응답 **1 failed**였다. 수정 뒤 모바일·취소 확인/결과·빈/오류 목록 **9 passed**, 취소 실패 **1 passed**, D-493 큐·배치 계약 **6 passed**, 반응형·팔레트·토큰·Fleet 문법 **83 passed**, 각 `known_failures.py` **0 NEW**다. 320×568과 390×844 현재 캡처에서 두 행동 폭 차이 ≤1px, 결과와 목록 버튼의 겹침 없음, 가로 넘침 0을 확인했다. 원본은 `X:/DevTemp/projects/rosy-platform/2026-10-07--fleet-roster-actions/`의 `red.txt`, `result-red.txt`, `final-browser.txt`, `failure.txt`, `contracts-final.txt`, `d493-contract.txt`, `fleet_console_mobile_default_{320,390}.png`, `fleet_cancel_all_result_{320,390}.png`, `fleet_cancel_all_failure_320.png`다.

2026-10-07 13:46 KST의 읽기 전용 사이트 PC `docker ps`에서는 Fleet·Vision·proxy가 모두 이미지 태그 `76a5861219a10653ca3505966d36a421d2fa594b`였다(`site-tags.txt`). 이 태그는 D-493 지도 우선 배치와 이 수정보다 앞서므로 위 캡처는 **LOCAL** 후보 근거이고 현재 사이트 UI 수용 근거가 아니다. 이미지 태그만으로 설치된 파일 내용도 증명하지 않는다. 나머지 G2 상태, 사이트 화면·장치 readback, 요청자의 G3 작업 검토는 **HOLD**다.
