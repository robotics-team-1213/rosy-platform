<!-- Parent: ../AGENTS.md -->

# Calibration

**Parent context:** `../AGENTS.md`

보정 앱의 경계·순서는 [README.md](README.md)가 정본이다. 결정은 [D-951](../../docs/adr/D-951-rosy-calibration-application.md).

- `calibration_web.py`와 `web/`: 실측 요청 화면(D-1004). 관제 PC loopback 서버, Account 로그인, 답은 `cell_requests.answer`만 호출한다. 파일을 직접 쓰지 않고, `by`는 세션에서만 온다. 시험 `test/test_calibration_web.py`.
- 측정과 판정 코드는 `deploy/robot/omx/cell_*`(엔진)에 둔다. 이 폴더에는 화면과 앱 실행 조합만 둔다.
- 팔이 움직이는 보정은 D-911 감독 시험으로만 요청한다. 화면에서도 동작마다 스위치 확인을 받는다.
- 가드 한계(작업 공간 바닥, 전류·PWM 상한)를 넓히는 일반 설정을 만들지 않는다. 바닥을 낮추는 것은 사람이 승인한 `low_zones` 사각형뿐이다.
- 에이전트 절차는 `rosy-calibration` 스킬 카드를 따른다.
