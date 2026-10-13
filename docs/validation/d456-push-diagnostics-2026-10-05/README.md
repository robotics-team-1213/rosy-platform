# D-456 정상 푸시 실패 재현과 실기 연동 경계

후보 소스 commit: `66d7c65ab740cf23d079d34f188ec5334e54d864`.
앞선 [통합 기록](../d456-final-integration-2026-10-05/README.md)은 당시 관측을 보존한다.

중단된 정상 푸시의 원본 후보4165에서 영향 검사10888개를 다시 수집했다.
첫 C6 실패는 원본 후보와 최신 후보에서 각각 재현했다. 실제 bridge 생성자에
비활성 optional guard를 명시하고 두 reader를 직접 접근으로 변경했다. 누락된
field는 제출 전에 실패하며 선언된 None의 기존 경로와 주입된 guard의 STOP→0을
보존한다. 자동 활성화·C6 예외·검사 범위·P6 예산은 변경하지 않았다.
독립 Safety 리뷰 SHA256: `5244aba29759b23fa376c1dc4e10b83764e6945b5de5789009ea1630efddd26e`.
부모 통합의 원본 관련 검사101PASS/18.88초, 기존 ROS 필수10SKIP다.
ROS SKIP를 실기 수용으로 처리하지 않는다.

원본 영향 검사와 동일한 명령·대상 경로로 후보83d633의10893개를 수집한 뒤
실패했던 영상 저장·다운로드 항목만 선택했다. 원본4165의10888개와 구분한다.
영상 저장2개는 PASS, 다운로드는 실제 여유 공간 보호 검사에서
UPDATE_INSUFFICIENT_SPACE로 실패했다(필요1GiB, 관측0.9GiB). 이는 새 재현의
확정 원인이며 중단된 원본의 모든 실패·후반 오류 원인을 확정하는 근거는 아니다.
공간 보호·시험 범위·정상 pre-push를 우회하지 않는다. 원본 로그를 보존한다.

2026-10-05 00:42 UTC 두 실제 로봇의 HTTPS identity는 SSH로 확인한 공개 CA와
호스트 이름으로 다시 검증했다. `rosy_26`과 `rosy_60`의 기존 키·CA는 유지됐다.
Pilot 태블릿과 Cam의 무선 ADB도 연결돼 있다.
관제의 기존 DPAPI named credential로 읽은 peers는401, 새 pairing pending은404다.
새 receiver 설정은 아직 적용되지 않았으며 root 설정 권한도 확보되지 않았다.
컨테이너 health나 로봇 HTTPS identity만으로 앱 승인·재접속·관제 수신을 수용하지 않는다.

증거 원본은 X:/DevTemp/rosy-ui-ship의 c6-parent66.log,
interrupted-push-collection-pollution.log, site-named-access-0943.json 및
trial-fence/c6-independent-review.json에 보존한다. 원격 push·후보 CI·서명039·
실제 Pilot 승인/재접속·관제 HTTPS/WSS·새 Camera Peer/발열 검증은 미완료다.
