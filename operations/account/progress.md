---
module: account
owner: ACCOUNT
last_verified: {commit: 5f02d723d1, date: 2026-11-02}
gates:
  SOURCE:
    state: GO
    evidence: "원격 패키지 소유·크기·중복 구조와 독립 import 58건 통과. D-962의 전용 원장·프로세스·수신 경계 구현. D-962 independent image and identity backup scope at 5f02d723d1: remote 335 backend/signing/image/backup cases plus 71 opted-in identity TLS/browser cases passed, 0 skipped, 0 NEW. Full Account tables including HTTP audit preserved; stale/corrupt backup refusal, strict signed legacy/new groups, reused image pins, branding, login/profile/admin and first-password flows verified. Prior e81af2d7c3 closure also passed 320 cases including Fleet header browser/Node compatibility. OCI construction and live independent-image/timer acceptance remain pending."
    cmd: python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/account/test test/architecture/test_wheel_structure.py -q
  LOCAL:
    state: GO
    evidence: "동일 인증 소스의 da5aab6c09 원격 Account·Fleet·실제 TLS Chromium 279건 및 공유 클라이언트·receiver 66건 통과, skip 0/NEW 0. 최종 게시 SHA 검증은 착지 기록을 따른다. D-962 independent image and identity backup scope at 5f02d723d1: remote 335 backend/signing/image/backup cases plus 71 opted-in identity TLS/browser cases passed, 0 skipped, 0 NEW. Full Account tables including HTTP audit preserved; stale/corrupt backup refusal, strict signed legacy/new groups, reused image pins, branding, login/profile/admin and first-password flows verified. Prior e81af2d7c3 closure also passed 320 cases including Fleet header browser/Node compatibility. OCI construction and live independent-image/timer acceptance remain pending."
    cmd: python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_account_service_separation.py operations/fleet/test/test_standalone_account_browser.py operations/fleet/test/test_account_receiver.py -q
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "Independent Account OCI build, signed candidate construction/verification and installation are pending."
  DEVICE:
    state: N/A
  FIELD:
    state: HOLD
    blocker: 운영 단일 writer 이관·실제 로그인 진입·Fleet 중단 중 독립성 수용 전.
adrs: [D-962]
---

실행·키·계정 원장은 Account가, 사이트 업무와 장치 admission은 Fleet이 소유한다.
설치와 이관은 `deploy/site/README.md`, 프로토콜은 `docs/reference/rosy-account-protocol.md`를 따른다.
