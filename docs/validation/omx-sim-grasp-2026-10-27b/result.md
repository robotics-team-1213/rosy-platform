# D-877 파지 반복 시험 2차: Isaac 5/5 (2026-10-27)

**위치:** 모델 PC, Isaac Sim 5.1 · **이전 기록:** [1차](../omx-sim-grasp-2026-10-27/result.md)(MuJoCo 5/5, Isaac 0/5) · **관련:** D-866 §2 Isaac 전환 조건

## 주장과 한계

- 같은 `tools/sim/omx_grasp_probe.py`(sim aid 없음, 교사와 같은 파지 기하)로 **Isaac 5/5, MuJoCo 5/5**.
  - Isaac: 블록 50.6–50.7mm 상승(그리퍼 50mm), 내려놓은 뒤 0.7–0.8mm. 들었을 때 `gripper_joint_1` 0.385–0.388rad.
  - MuJoCo: 51.2mm, 0.9mm, 0.406rad(1차와 같음, 공용 패드 정의로 옮긴 뒤 회귀 확인).
- 같은 커밋으로 적합성 시험 두 백엔드 통과: Isaac 실시간 배율 0.961, MuJoCo 0.999, 정지·물체 흔들림 0mm.
- Isaac 전환 조건 중 "그리퍼 파지 반복"은 이 시험 범위(블록 하나, 자세 하나, 5회)에서 충족된다. 카메라 640×480 10Hz와 렌더링 분포 비교는 여전히 미충족·미측정이다([전환 조건 기록](../isaac-switch-conditions-2026-10-26/result.md)).
- **교사 판정과의 차이:** Isaac 손가락은 힘 상한(0.2N·m) 구동이라 보정 접촉각 0.407보다 더 닫힌 0.385 근처에서 멈춘다. 교사의 쥐고 있음 판정(`contact_held`: 닫기 목표와 접촉각의 중간 0.3935 이상)은 이 값을 거절한다. Isaac에서 교사를 돌리기 전에 손가락 구동이나 판정을 맞춰야 한다.

## Isaac에서 고친 것 (`learning/envs/isaac/run_omx_backend.py`)

1. **관절 구동.** importer는 팔과 `gripper_joint_1`을 acceleration, `gripper_joint_2`를 구동 없이 두었다. 모든 회전 관절을 force 구동과 2026-10-25 화물 집기 fixture의 이득·힘 상한(`conveyor_fixture.FIXTURE`)으로 둔다. 팔 TCP 흔들림 ±2cm → 약 2mm.
2. **두 번째 손가락.** importer가 만든 `PhysxMimicJointAPI`는 `gripper_joint_1`의 rotX(실제 축 Z)를 참조했고 감쇠비 0.005였다. 축과 감쇠비를 고쳐도 손가락이 묶이지 않았다(g1 0.38일 때 g2 −0.24). mimic을 지우고 `gripper_joint_2` 목표를 매 프레임 측정한 `gripper_joint_1`의 반대 각으로 준다. 이후 두 손가락이 0.380/−0.380으로 대칭.
3. **손가락 충돌.** 대칭이 된 뒤에도 손가락이 30mm 블록에 닿지 않고 0.380까지 닫혔다. MuJoCo와 같이 손가락마다 보정 접촉점 캡슐 하나로 충돌하고 가져온 손가락 충돌은 끈다. 패드 정의(반지름, 길이, 접촉점 읽기)는 `tools/sim/omx_cell_world.py` 한 곳에 두고 두 백엔드가 쓴다.
4. 마찰 1.0 물리 재질(손가락 패드·상자), articulation 자기 충돌 끔.

## 환경 주의

모델 PC의 `~/rosy-isaac-ready/sdk-path.txt`가 2026-10-27 19:47에 Isaac Lab 3.0 환경(`isaaclab-3.0.0-sim62`)을 가리키도록 바뀌었다. 그 환경에는 이 어댑터가 쓰는 Jazzy 브리지 라이브러리가 없어 실행이 `librcutils.so` 오류로 끝났다. 이 기록의 실행은 모두 `ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv`(Isaac Sim 5.1.0)로 지정했다.

## 명령

```
remote_sim.py --host model --sha <commit> cmd -- 'ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv GRASP_TRIALS=5 tools/sim/run_omx_backend_conformance.sh isaac 240x320 5 grasp'
remote_sim.py --host model --sha <commit> cmd -- 'ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv tools/sim/run_omx_backend_conformance.sh isaac 240x320 5'
```

측정 커밋은 이 기록과 같은 변경의 임시 커밋 `f04cee857f`(main 위 `git commit-tree`)이다.
