---
module: account
owner: ACCOUNT
last_verified: {commit: dd9d55404f, date: 2026-11-02}
gates:
  SOURCE:
    state: GO
    evidence: 원격 패키지 소유·크기·중복 구조와 독립 import 58건 통과. D-962의 전용 원장·프로세스·수신 경계 구현.
    cmd: python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/account/test test/architecture/test_wheel_structure.py -q
  LOCAL:
    state: GO
    evidence: 동일 인증 소스의 da5aab6c09 원격 Account·Fleet·실제 TLS Chromium 279건 및 공유 클라이언트·receiver 66건 통과, skip 0/NEW 0. 최종 게시 SHA 검증은 착지 기록을 따른다.
    cmd: python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_account_service_separation.py operations/fleet/test/test_standalone_account_browser.py operations/fleet/test/test_account_receiver.py -q
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: 독립 Account 서비스를 포함한 서명 사이트 후보의 게시·검증·설치 대기.
  DEVICE:
    state: N/A
  FIELD:
    state: HOLD
    blocker: 운영 단일 writer 이관·실제 로그인 진입·Fleet 중단 중 독립성 수용 전.
adrs: [D-962]
---

실행·키·계정 원장은 Account가, 사이트 업무와 장치 admission은 Fleet이 소유한다.
설치와 이관은 `deploy/site/README.md`, 프로토콜은 `docs/reference/rosy-account-protocol.md`를 따른다.
