# 폴더 정리 배포의 역사 안전 리뷰 증거

2026-10-14. 검토한 후보는 `dbf2f51e4`이며, 실패한 CI는 `38429304979`다. 독립 검토자는 `Codex /root/delivery_review`와 `Codex /root/authority_review`다. 과거 커밋의 trailer 누락을 기존 D-430 `EXEMPT` 규칙으로 기록한다. 검사 범위·태그·baseline·trailer 요구를 바꾸지 않는다. 이 문서는 SOURCE provenance만 기록하며 장치 활성화나 주행 승인이 아니다.

| 커밋 | 독립 SOURCE 검토와 조건 |
|---|---|
| `a1d29a9f9` | delivery_review PASS: 문서 parent 연결만 변경, CORE 최종 권한·보정 경계 유지. |
| `58d1295eb` | delivery_review PASS: 선택 run identity·quiescence·live context, TLS identity await 뒤 dispatch guard와 CORE epoch fence 유지. |
| `568cb207f` | delivery_review PASS: 같은 floor 정책을 새 caller clock으로 최대 두 번 확인. 재거부·예외·몸 여유 거부는 fail-closed. |
| `b6590448c` | authority_review 역사 SOURCE PASS: forward evidence producer→snapshot→후보 연결, CORE writer 유지. rev1·coverage 후속과 함께 읽으며 단독 실행 승인 아님. |
| `d385f2395` | authority_review provenance PASS, DEVICE HOLD: arc sweep과 초음파·unknown 차단 유지. 후보 속도를 previous bound로 사용한 가정은 실제 직전 명령을 상계하지 못함. |
| `685f6e04a` | authority_review SOURCE PASS: obstacle이 참일 때 unknown 전방 차단 적용. rev1 한계 해소 아님. |
| `a4b118164` | authority_review provenance PASS, DEVICE HOLD: pivot verdict와 beam coverage 분리. 몸 내부 반사 제거 후 coverage 의미는 후속 확인 필요. |
| `d3883044f` | authority_review SOURCE PASS: snapshot 교체 한 번만 재평가, 두 번 교체 시 거부. caller clock·window·최종 identity 유지. |
| `ce427feea` | authority_review SOURCE PASS: holder 이동 전 첫 부모의 safety 5파일과 바이트 동일. 추가 motion logic 없음. |
| `600186c84` | authority_review SOURCE PASS: 두 파일에서 docstring 제거 AST가 부모와 동일. |
| `7822df785` | authority_review SOURCE PASS: adapter 주석 축약, docstring 제거 AST가 부모와 동일. |
| `b775a01d7` | 단독 상태 REJECT: observed_at으로 caller clock을 대체함. 역사 예외는 정확한 revert `806d82f8c`가 함께 존재하는 조건에서만 적용. |
| `806d82f8c` | authority_review SOURCE PASS: production·test 파일 모두 b775의 직전 부모와 바이트 동일하게 복원. 최종 후보에 REQUEST_LEAD_S·정책 내부 observed_at clock 대체 없음. |

SOURCE에서 확인한 최종 경계는 snapshot future/expired 거부, 제한된 교체 재평가와 최종 identity, 타입·finite·body/profile·신선도 검사, CORE 단일 최종 명령 writer다. `_sensor_only`는 실제 CORE producer도 포함하므로 D-740 rev1을 SIM 전용 구현이라고 해석하지 않는다.

DEVICE HOLD: 실제 직전 명령의 속도 상한 전달, self-reflection 제거 이후 coverage 의미, 실제 sweep 계산 시간과 0.01초 budget, ROS producer 실행 결과. D-740 상태를 Accepted/device-ready로 바꾸지 않는다. 로봇 두 대는 등록 주소로 접속되지 않으며 ABI·calibration·canary 검증과 활성화도 수행하지 않았다. 현장 서버 후보는 Fleet·Vision·Proxy이며 로봇 motion payload와 별도다.

검토자는 pytest·배포·실물 시험을 실행하지 않았다. 부모 실행기는 각 원격 시험 종료 결과, 정확한 SHA의 CI, 서명, 서버 전환·등록 readback을 X: 배포 세션에 따로 기록한다. 과거 후보 원격 pre-push 6개 invocation은 terminal 0/NEW 0였지만 위 CI는 scope에서 실패하여 test matrix를 실행하지 않았고 서명·배포 근거가 될 수 없다.
