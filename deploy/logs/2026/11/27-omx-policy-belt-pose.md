## 2026-11-27 · uncommitted · OMX 정책 실행기 벨트 컨테이너 자세 입력(Panel L 13칸 environment_state)

- 변경: 체크포인트의 `ENV_STATE.json`이 `belt_dx_cm`·`belt_dy_cm`·`belt_yaw_x5`를 끝 3칸으로 선언할 때만 `cell_lerobot_shadow`가 13칸(목표 one-hot 10 + 자세 3)을 만든다. 선언이 없거나 다르면 기존 동작이다. `cell_belt_pose.py`가 동작 전 top 프레임 한 장에서 컨테이너를 찾아(`omx_real2sim` `blobs`·`lane_blobs`), 번들의 top 카메라 모델로 fixture 좌표에 역투영하고 `Layout(preset).sites["belt"]`와의 차이를 낸다. 인식 실패·0개·2개 이상·크기 불일치·기준 없음은 `BELT_POSE_UNKNOWN`, 학습 범위+여유 밖은 `BELT_POSE_OUT_OF_RANGE`로 팔을 움직이지 않고 거절한다. 값을 자르지 않는다. `cell_policy_drive`가 세 숫자와 근거(중심·오프셋 mm, yaw, 크기 점수, 프레임 sha256)를 `policy-drive.jsonl`과 결과에 남긴다. 목표 인자 검사를 `cell_policy_goals.cli_goal`로 옮겨 drive를 400줄 아래로 유지했다(동작 동일).
- 증거: `test/test_omx_policy_belt_pose.py`(합성 프레임 오프셋·yaw 접기, 범위 밖·인식 실패 거절, 10칸 불변, dry run 기록, 실물 run 4·6 top 프레임), 원격 `test/test_omx_lerobot_shadow.py`·`test/test_omx_policy_drive.py` 외
- gate 변화: 없음. 가드 한계·기존 게이트 그대로, 새 거절만 더함
- 결정: 팔 좌표·셀 보정 지도 대신 시뮬 top 카메라 모델로 fixture 좌표를 직접 얻는다(시뮬 팔 받침은 사진 추정값, arm_a 17 mm 차이 기록)
- 교훈: 없음. 미해결: 11-27 실물 프레임의 벨트 컨테이너는 시뮬 벨트 사이트에서 dy 약 −34 mm(1~5회차)·−49 mm(6회차)라 Panel L 범위(±8 mm) 밖이다
