# D-877 파지 반복 시험: MuJoCo 통과, Isaac 미통과 (2026-10-27)

**위치:** 모델 PC, `remote_sim.py --host model` · **관련:** D-866 §2 Isaac 전환 조건 "그리퍼 파지 반복 시험", D-877

## 주장과 한계

- `tools/sim/omx_grasp_probe.py`가 공통 계층의 궤적 Action만으로 infeed block(40×30×30mm, 20g)을 집어 50mm 들고 제자리에 내려놓기를 반복한다. 교사와 같은 파지 기하(위에서 내려다보는 IK, 작업의 pick yaw, recipe 파지 깊이 15mm, 폭에 맞춘 닫기 0.380rad)를 쓰고 sim aid는 쓰지 않는다. 블록 위치는 `/sim/object_tf`로만 판정한다.
- **MuJoCo: 5/5 통과.** 블록이 51.1–51.2mm 올라갔고(그리퍼 50mm), 그리퍼는 0.406rad에서 멈췄다(Gazebo 보정값 0.407). 내려놓은 뒤 위치 차이는 0.9–1.0mm다.
- **Isaac: 0/5.** 손가락이 블록을 옆으로 12–57mm 밀었다. 이로써 Isaac의 `/sim/object_tf`가 저장된 자세가 아니라 시뮬레이션 자세를 낸다는 것은 확인됐다(2026-10-27 물체 사실 기록의 미확인 항목).
- 이 시험은 Gazebo 교사(sim aid 사용)나 실물 파지를 대신하지 않는다. 블록 하나, 자세 하나다.

## MuJoCo에서 고친 것 (`tools/sim/omx_mujoco_backend.py`)

1. **손가락 충돌.** MuJoCo는 mesh를 볼록 껍질로 충돌시킨다. 손가락 껍질이 축에서 끝까지 덮어 두 손가락이 모든 열림에서 겹쳤고(간격 −1.8mm), 30mm 면을 잡는 자세에서는 손가락이 블록에 닿지 않았다. 손가락마다 반지름 1.5mm 캡슐 하나를 Gazebo 보정 접촉점(`deploy/robot/omx/sim/cell_profile.yaml` `gripper.jaw.contact_point_m`, link7은 대칭)에 두고 mesh는 보이기만 한다. 간격이 보정식과 0.4mm 안에서 맞는다(0.407rad에서 29.8 대 30.0mm). 상자를 썼을 때는 돌아간 모서리 때문에 4mm 좁았다.
2. **마찰.** 기본 피라미드 마찰 원뿔에서는 쥔 블록이 미끄러졌다. 타원 원뿔과 `impratio` 10으로 잡힌다. 손가락·움직이는 물체 접촉을 단단하게(`solref` 0.002) 해 부드러운 접촉의 겹침이 간격에 들어가지 않게 했다.
3. 같은 커밋으로 MuJoCo 적합성 시험이 그대로 통과한다(실시간 배율 1.003).

조사 과정의 함정: 처음 오프라인 확인은 yaw 0으로 블록의 40mm 면을 잡아 성공했고, 실제 작업 yaw(1.571, 30mm 면)에서는 실패했다. 블록은 world 파일에서 90° 돌아가 있다.

## Isaac에서 남은 것

같은 실행의 관절 기록(`sim-joint_states.csv`):
- `gripper_joint_2`가 `gripper_joint_1`을 따르지 않는다(−0.1~−1.3rad로 흔들림). URDF mimic이 Isaac 가져오기에서 구동되지 않는다.
- 팔 추종이 느슨하다. 내려간 TCP가 ±2cm 흔들리고 파지 높이 15mm 아래 1mm까지 내려갔다. 가져온 관절 구동 강성이 낮다.
- 손가락 충돌은 MuJoCo와 같은 볼록 껍질 문제일 가능성이 높다.

Isaac 전환 조건의 파지 반복은 미충족이다. 위 세 가지를 Isaac 어댑터에서 고친 뒤 같은 명령으로 다시 잰다.

## 명령

```
remote_sim.py --host model --sha <commit> cmd -- 'GRASP_TRIALS=5 __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json tools/sim/run_omx_backend_conformance.sh mujoco 240x320 5 grasp'
remote_sim.py --host model --sha <commit> cmd -- 'GRASP_TRIALS=5 tools/sim/run_omx_backend_conformance.sh isaac 240x320 5 grasp'
```

측정 커밋은 이 기록과 같은 변경의 임시 커밋 `64cb0cb5b6`(main 위 `git commit-tree`)이다.
