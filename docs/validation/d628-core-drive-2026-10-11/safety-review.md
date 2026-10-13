# D-628 CORE 주행 경계 독립 검토

검토자: `/root/safety_structure_review`, 2026-10-11. 판정: **APPROVE — 소스 범위**.

모드와 입력 세대, 불변 autonomous 후보의 동일성 검사를 정책 평가 전후에 적용한다. 모드 재진입은 이전 후보를 복원하지 않는다. 차선 후보는 기존 프로필 상한을 적용한 뒤 traffic gate에 들어가며, 이후 동적·정책 상한은 선속도와 각속도에 같은 비율을 적용한다. 보정 출력이 검토한 곡선을 바꾸면 거절한다. Nav2·도킹·수동·Arm의 기존 클리핑 의미는 유지한다.

이동 복구 응답은 현재 센서·보정 상태를 다시 읽지만 복구 단계를 진행하거나 시도 예산을 보충하지 않는다. standalone 복구기는 경과 시간으로 증거를 노화시키고 잘못된 시각·나이를 거절한다. KTURN 후진은 기존 직선 후방 거절 검사 뒤에 차체 회전 후진 궤적을 검사한다.

첫 검토의 두 지적(잘못된 저장 나이, 다중 필드 후보 저장 경합)을 수정한 후 승인했다. 원격 시험 결과는 별도로 기록한다. 같은 NAV 모드 안에서 외부 ROS 후보의 goal identity를 완전히 검증하는 D-442 단계, ROS 실행, ARM64 이미지와 실물 주행 수용은 이 소스 승인의 범위 밖이다.

US-005 조립 추출도 독립 소스 검토에서 승인했다. 추출한 helper를 펼친 `CoreServices` AST는 기존 생성 순서와 동일하다. traffic observer start, live angular provider, data path와 listener 순서를 유지한다. 속도 검사 세 함수는 `safety/velocity.py`로 그대로 옮겼으며 Safety manager는 576줄이다.

전체 CORE 회귀에서 기존 watchdog 갱신 중 출력 재조회 시험이 새 epoch 조회의 비재진입 잠금에서 교착하는 문제를 발견했다. `39ff424b0`은 같은 zero 출력 증거를 유지하면서 2초 이내에 교착을 NEW 실패로 판정한다. 후속 수정은 mode 잠금을 `RLock`으로 바꾸는 한 줄과 이유 주석뿐이다. 독립 첫 커밋 전 검토에서 승인했다. 입력/워치독의 원자적 commit, 다른 스레드의 직렬화, epoch/identity 검사와 일반 listener의 잠금 밖 실행 위치는 유지한다. commit callback의 이벤트·모드 전환 금지 계약도 유지한다. 원격 GREEN과 통합 착지는 별도 확인한다.
