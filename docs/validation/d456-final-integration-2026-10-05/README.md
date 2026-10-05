# D-456 최종 소스 통합과 실기 검증의 남은 경계

후보 코드 기준 commit: `d855997ce5858e05fc7e814cd170b78890a25e14`.
연결 전송·CLI 구조 검토는 이전
[기록](../d456-enrolled-tls-integration-2026-10-05/README.md)을 유지한다.

정상 pre-push가 발견한 순수 정책 시험의 소유 위치와 공개 digest 표기를 수정했다.
정책 시험10개는 services, 실제 CORE 제출·STOP·readiness·odometry·MUX 시험10개는
gateway로 구분했다. 기존20개 함수 본문·assertion·decorator AST를 보존한다.
정책 import 위치만 숨겨 통과시킨 것이 아니며 frozen 예외와 검사 범위는 유지한다.
독립 Safety 리뷰 영수증 SHA256: `131d75c23aac70293eda0f2ea691c7bf3cd075a925f08705ff7b6bee494e5231`.
원본 관련 부모 통합 검사는44PASS(1.79초)다.

동시 OMX 실행 기록은 초기104PASS에도 기록 저장 중 권한 철회 뒤 제출이 가능했다.
실제 SQLite prepare 뒤의 모의 제출로 SOURCE HOLD를 재현하고 기존 최종 fence 안에서
기존 guard를 다시 호출했다. 권한·설치 bytes·소유자·카메라 결속과 이어지는 STOP·시각·
lease·source freshness를 유지한다. 세 철회 상황 모두 제출 전 거절하며 자동 재개하지
않는다. 기본 disabled 상태와 기존 journal 없는 경로는 유지한다.
독립 Safety 리뷰 영수증 SHA256: `0bd1e3f9e2b502b8593eb12047c84a5c7bcc471ccb4efdf5eeac14cb7c47b592`.
부모 통합의 원본 local execution 전체107PASS(6.74초)다. 이는 모의 전송을 사용한
SOURCE/HOST 검사이며 실제 OMX 활성화·ROS·장비·주행 수용은 아니다.

정상 푸시 첫 실행은 두 새 실패를 발견했고 원격에 반영하지 않았다. 수정 후 기본
gate476PASS/2SKIP를 확인했으나 추가 영향 검사는 약64%에서 실패·오류와 함께 중단됐다.
당시 X 임시 드라이브가 고갈되어 최종 traceback·실패 목록을 완성하지 못했다.
모든 실패를 디스크 원인으로 단정하거나 알려진 실패·NEW0으로 분류하지 않는다.
공간 확보 후 원본 검사를 다시 실행해야 한다. 다음 실행은 첫 실패에서 멈춰 상세
로그를 보존하며 검증 항목과 성공 조건은 줄이지 않는다. 정상 pre-push를 우회하지 않는다.
원본 부분 로그는 `X:/DevTemp/rosy-ui-ship/native039-normal-push-final.log`에 보존한다.
검사 중 생긴 소스 폴더의1바이트 lock은 X에 이동해 보존했으며 소스 변경은 없었다.

확인한 실기 증거는 기존 서명038의 두 HTTPS identity와 TLS calibration 읽기,
설치된 Pilot 화면·다시 찾기 표시, 기존 승인 Cam의 송출2.5fps 및 UI 종료0fps다.
현재 로봇 광고의 누락된 TLS hostname은 수정 코드에 있으나 새 서명 릴리스로 실기에
반영하지 않았다. 실제 Pilot 승인·CA 확인·승인 보존 재연결은 미완료다. Cam의 기존
송출은 새 peer 승인이나 독립 Vision frame sequence·marker·발열 자동 종료 증거가 아니다.

관제의 공개 TLS 파일은 준비했으나 현재 SSH 계정은 root 설정 쓰기 권한이 없다.
새 Camera Peer receiver 설정과 유효한 named operator 인증도 확인하지 못했다.
관제 container health와 encrypted enrollment 두 행만으로 실제 HTTPS/WSS 연동을
수용하지 않는다. 원격 push·정확한 SHA CI·서명039·관제 설정·실제 앱과 로봇 승인/
재연결을 완료한 것으로 표시하지 않는다. issuer·키·CA·기존 승인·E-Stop은 보존한다.
