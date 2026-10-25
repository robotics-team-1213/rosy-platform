# 공급암 S 셀 Isaac 재생 (2026-10-25)

- **범위:** 실물 셀의 청크 프레임을 Isaac 5.1.0.0에서 받침·벨트·Pinky 프레임 장면에 재생하고, 상자·손가락·관절 오차 측정값만으로 판정했다. 학습 정책·실물 수용·카메라 정합이 아니다. 좌표는 실물 집기의 순기구학(`ARM_FK_FROM_REAL_GRASPS_NOT_CAMERA_REGISTERED`)이다.
- **실행:** 모델 PC Isaac 실행 관리자. `tools/remote/remote_isaac.py check --scenario arm-s-cell-<s>` → `start` → `status` → `fetch`. 프레임은 `deploy/robot/omx/isaac_cell_frames.py --scenario <s>`(시나리오당 약 3,778프레임, 30 fps), 장면은 `learning/envs/isaac/arm_s_cell_task.py --steps-per-frame 1`.
- **시험:** `learning/envs/isaac/test/test_arm_s_cell_fixture.py`, `test/test_omx_isaac_cell_frames.py` 원격 통과(9 passed).

## 결과

| 회차 | 장면 커밋 | 바꾼 것 | nominal | overhang | wrong-yaw |
|---|---|---|---|---|---|
| 1 | 초기 | 상자 0° | 대각선 집기, 들다가 모서리가 프레임에 닿아 빠짐 | — | — |
| 2 | 166c0c42bb | 상자를 집게 각도 −67.8°로 | GPU 사용 중이라 실행 안 됨 | frame_contact (기대 일치) | frame_contact: 들 때마다 프레임에 스침 |
| 3 | 89c87aac3d | 프레임을 받침 중심에서 45 mm로 | held_not_placed: 벨트에 놓았으나 목표에서 15.6 mm(허용 15) | frame_contact (일치) | held_not_placed: nominal과 같은 방향으로 어긋남 |
| 4 | a42a8c114d | 손가락 2가 손가락 1 측정 각도를 제어기로 따라감 | not_held | not_held | not_held |
| 5 | fa68128f3c | PhysX mimic, gearing −1 | not_held(손가락 2가 같은 방향으로 돎) | not_held | not_held |
| 6 | 3fbece2449 | PhysX mimic, gearing +1 | not_held | not_held(손가락 접촉 18 N에도 빠짐) | not_held |

착지한 장면은 3회차 설정(손가락 독립 구동)에 wrong-yaw 기대 `not_held`다. nominal은 기대 `placed`를 0.6 mm 차이로 통과하지 못한다. 허용치를 늘리지 않았다.

3회차 nominal에서 옮기는 동안 두 손가락이 같은 방향으로 약 0.45 rad씩 움직였다([0.42, −0.42] → [−0.03, −0.77]). 상자는 (0.1456, −0.015, 0.059) m에 놓였다(목표 (0.150, 0.000)). 손가락 접촉은 약 3~4 N, 관절 오차 최대 0.0116 rad.

## 한계와 미해결

- **집게 결합:** 두 손가락이 따로 힘 한도(0.2 N·m)에 걸려 같은 힘으로 누르면 상자가 집게 안에서 옆으로 흐른다(가설). 실물은 모터 하나와 링크다. 제어기 거울과 PhysX mimic은 상자를 밀어냈다. 다음: mimic 강성·감쇠, 실물 전류 한도에서 구한 손가락 힘, 손가락 충돌 모양(convexHull).
- **관측 카메라:** 단계 사진(`grasp/transfer/release.png`)에 셀이 보이지 않는다. 화면 위 가장자리에 띠만 보인다. 카메라 자세(`camera_axes='usd'`와 look-at 행렬)를 고쳐야 사진이 증거가 된다. 그래서 사진은 이 기록에 넣지 않았다.
- **실행 관리자 UNKNOWN:** 모든 실행이 UNKNOWN으로 기록됐다. SDK가 끝난 뒤 GPU에 다른 계산 프로세스(ollama llama-server, 약 8 GB)가 있어 정리 확인을 통과하지 못했다. 결과는 각 실행 폴더의 `arm-s-cell-report.json`을 직접 읽었다.
- **엔진 차이:** Gazebo에서는 집게 각도로 돌아간 상자(yaw-site)를 집지 못했다. Isaac 3회차는 집어서 옮겼지만, 집게가 흘리는 문제와 섞여 있어 근거로 쓰지 않는다.
