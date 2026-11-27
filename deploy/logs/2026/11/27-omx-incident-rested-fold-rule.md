## 2026-11-27 · uncommitted · OMX 사건 보고의 folded 사실이 쉬는 접힌 팔을 펴진 팔로 오판하지 않게

- 변경: omx_incident.facts가 HOME_TOL 판정에 더해, 시작 라이브러리의 접힘 자세로 cell_job_peer_health.live_folded(calibrated 기준만, coarse 폴백 없음)가 접힘이라 하고 몸 관절이 모두 core_common REST_TOL(8) 안이면 folded로 둔다(느슨한 관절별 범위만으로는 넓히지 않음, 기존 시험이 pan 20 차이를 잡음). 토크를 끈 arm_s는 팔꿈치가 50.4에서 54.7로 풀려 HOME_TOL(3.0)을 넘고 "torque off with arm extended" 사건이 열렸다. Fleet은 같은 facts를 받으므로 두 쪽이 어긋나지 않는다. HOME_TOL·REST_TOL·가드 한계는 그대로다.
- 증거: 2026-11-27 arm_s 세션 끝 자세 [0.22, -58.53, 54.68, 49.84, -4.66]가 세 번 사건을 열었고 같은 자세를 준비 상태 규칙은 접힘으로 읽음. 시험 test_omx_incident.py 3개(쉬는 자세 무사건, 펴진 자세 사건 유지, 라이브러리 자세 없음 그대로)
- gate 변화: 없음(펴진 팔 탐지는 약해지지 않음: lift -50 이하·elbow 45 이상과 라이브러리 자세 범위 안일 때만)
- 결정: 없음
- 교훈: 없음(셀 수용 전)
