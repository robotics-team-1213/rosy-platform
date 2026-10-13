# Pinky 반복 영상·픽셀 검수 구현 (D-462)

기존 GUI owner의 feat/pinky-review-cycle에서 기존 영속 앱을 확장한다.
루트는 learning_cycle/review_bridge, 정책 peer는 learning/registry/policy, 영상 peer는 근거 점검을 소유한다.

1. 검증된 355 표현을 353 영상/frame identity로 pending 등록하고 네 기존 객체 결정을 보존한다.
2. 독립 마스크 revision과 원본 좌표 브러시·취소·되돌리기·명시 전체/배경 검수·CAS를 제공한다.
3. CAD 파일/graph SHA를 확인하되 실제 camera/map/pose projection은 unverified로 표시한다.
4. 모든 latest decision·class/image/mask approval binding을 한 SQLite snapshot으로 읽는다.
5. 동일 snapshot으로 immutable export를 seal하고 최신 live authority와 필수 파일/내용을 검증한다.
6. 다중 store 동시 수정·오래된 승인 철회·변조·중복/누락 파일 회귀와 Chromium PC/mobile를 실행한다.
7. 실제 state에는 pending만 추가하고 루트에 source SHA·API/export fixture·브라우저 증거를 전달한다.

객체 1/2 approved v1,3 excluded v1,4 pending v2는 변경하지 않는다. 실제 승인 mask0을 유지한다.
기존 stop_line/crosswalk train/val pixels0은 과거 catalog 사실이다. indexed→RGB builder adapter와
현재 결정 수신·원격 전달 및 독립 integration 수용은 루트의 잔여 항목이다. push·배포·주행·HOLD 해제는 없다.
