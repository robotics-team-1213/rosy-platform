## 2026-11-21 · uncommitted · feat(omx-bench): 벤치 녹화 바로 시작·리더 정렬·전축 추종·녹화 중 미리보기·자동 복구

- 변경: 벤치 녹화 화면을 재배치(큰 카메라, 우상단 목표, 사이드바, 알림 한 곳)하고 확인 체크박스를 없앴다. 리더를 팔로워 실제 자세에 모터로 맞춘다(mount 반 바퀴·방아쇠 끝값·follower_floor 선언). 전축 리더 텔레옵은 1도/s 정렬 뒤 최대 25도/s 로 추종하고, 명령이 실측보다 목표 방향으로 3도 넘게 앞서지 않으며 3초 정체하면 토크 ON 으로 멈춘다. 녹화 중 미리보기는 녹화기의 프레임을 쓴다. 러너를 시작하지 못한 홈 실패, 죽은 러너의 hold 임대, 기준값이 아닌 caps 는 증거가 있을 때 벤치가 복구한다.
- 증거: 셀 PC pytest(test_omx_bench_record*, test_omx_*native*, motor_health, leader, chunk_runner_interrupt) 통과. arm_s 실물: 세션 23·25 추종과 에피소드 1개 저장, 19:54 세션에서 정렬 뒤 추종 전환 확인. 선행 제한·정체 hold·시작 대기 단축·자동 복구는 실물 미검증.
- gate 변화: 없음
- 결정: 2026-11-21 사용자: 시작 확인 체크박스 없음, 전축 추종 30도/s 선택(서보 profile 27.5도/s 때문에 25), 토크는 최대한 끄지 않음
- 교훈: docs/solutions/runtime-errors/omx-arm-s-leader-half-turn-and-trigger-ends-2026-11-21.md
