# OMX 구간 검수 공개 기준 UI 검증

2026-10-21. 장치 구동과 실제 학습 성능은 이번 원격 게시 범위 밖이다.

- 선행 기반 PR #139, commit 0274c4ce3db4: 원본 계보를 보존하는 child Episode 내보내기. [고정 LeRobot 원본 읽기 근거](foundation.md).
- 저장소 분리 PR #140, commit d9620015a202: 기존 클래스와 나머지 서버 AST 동일성, 기존 import·오류 처리·접근 범위 상수 보존. 기본 계약 519 passed, 관련 검사 2214 passed / 272 skipped, NEW 0. 최신 head의 개별 CI 5개 모두 성공 후 병합했다.
- UI PR #141, 검사 commit ed283f5e3fe6: 공식 원격 명시 Chromium과 API 총18 passed / skip0. 손상 자료 격리, manager 권한·검수자 위조 거절, 버전 충돌, 실제 이미지 디코딩, 모바일·키보드·저장 중 입력·다운로드·늦은 새로고침을 검사했다.
- 같은 UI commit의 pre-push 기본 계약519 passed, 관련2336 passed / 273 skipped. 각각 NEW0 / known0 / flaky0. 기본 skip은 위 명시 실행과 구분한다.

## 실제 화면

별도 합성 LeRobot 파일을 원격의 고정0.4.4 환경에서 읽고, 격리된 loopback 서버에 headed Edge로 접속했다. 서비스 코드는 commit904889ac8ebc, 비교한 로컬 UI 코드는 commitb5bc090cadc0이다. 두 코드와 검사 commit ed283f5e3fe6의 learning/shared 파일은 동일하다. 실제 사람 검수 자료나 운영 DB는 사용하지 않았다.

- 어두움/밝음 각각1440×1000,390×844,320×568에서 원본 사진을 디코딩했다. 페이지 가로 넘침은 없고 주요 버튼 높이는48px였다. 작은 화면의 탐색 rail은 자체 가로 스크롤을 사용한다.
- Enter 프레임 확인, Space 구간 추가, 저장 응답 대기 중 추가한 입력 보존, 저장본과 다운로드 JSON 일치, 새로고침 취소, native beforeunload 취소 후 입력 보존, 재조회된 선택을 확인했다. pageerror는0이다.
- 원본 사진에 SYNTHETIC 표시가 있으며 이 검수는 agent가 생성한 시험 자료다. 학습용 사람 정답이나 실제 파지 성공률을 만들지 않는다.
- 고정 증거: 작업 공간 밖 `Rosy/artifacts/receipts/omx-grasp-publication-20261021/`의 화면 캡처·walk-ux.json·선택 JSON. 시험 명령과 최종 병합 상태는 해당 PR에도 남긴다.

## 탐색 연결

메뉴 자산 commit d3fc0f70de5d를 격리 서버에 추가했다. headed Edge의1440/390px에서 기존 목록·객체·픽셀·자료 화면 각각 모방학습으로 이동하는 총8개 여정과 현재 메뉴 표시를 확인했고 pageerror는0이었다. 원격의 명시 OMX 진입 회귀와 다섯 화면의 공통 메뉴 계약은 총11 passed / skip0이다. nav-walk.json과 두 화면 크기 캡처를 같은 증거 폴더에 보존한다.
