# D-877 파지 반복 시험 2차: Isaac 5/5, 보정 각도에 맞춤 (2026-10-27~28)

**위치:** 모델 PC, Isaac Sim 5.1 · **이전 기록:** [1차](../omx-sim-grasp-2026-10-27/result.md)(MuJoCo 5/5, Isaac 0/5) · **관련:** D-866 §2 Isaac 전환 조건

## 주장과 한계

- 같은 `tools/sim/omx_grasp_probe.py`(sim aid 없음, 교사와 같은 파지 기하)로 **Isaac 5/5, MuJoCo 5/5**.
  - Isaac: 블록 50.7mm 상승(그리퍼 50mm), 내려놓은 뒤 0.3–0.4mm. 들었을 때 `gripper_joint_1` 0.405–0.408rad(두 손가락 대칭, 0.4071/−0.4075).
  - MuJoCo: 51.2mm, 0.9mm, 0.406rad(1차와 같음, 공용 패드 정의로 옮긴 뒤 회귀 확인).
  - 두 값이 Gazebo 보정 접촉각 0.407과 맞아, 교사의 쥐고 있음 판정(`contact_held`, 0.3935–0.422)을 그대로 통과한다.
- 적합성 시험: Isaac 최종 커밋에서 통과(실시간 배율 0.972, 정지·물체 흔들림 0mm). MuJoCo는 패드 공용화 커밋에서 통과(0.999).
- Isaac 전환 조건 중 "그리퍼 파지 반복"은 이 시험 범위(블록 하나, 자세 하나, 5회)에서 충족된다. 카메라 640×480 10Hz와 렌더링 분포 비교는 여전히 미충족·미측정이다([전환 조건 기록](../isaac-switch-conditions-2026-10-26/result.md)).

## Isaac에서 고친 것 (`learning/envs/isaac/run_omx_backend.py`)

1. **관절 구동.** importer는 팔과 `gripper_joint_1`을 acceleration, `gripper_joint_2`를 구동 없이 두었다. 모든 회전 관절을 force 구동과 2026-10-25 화물 집기 fixture의 이득·힘 상한(`conveyor_fixture.FIXTURE`)으로 둔다. 팔 TCP 흔들림 ±2cm → 약 2mm.
2. **두 번째 손가락.** importer가 만든 `PhysxMimicJointAPI`는 `gripper_joint_1`의 rotX(실제 축 Z)를 참조했고 감쇠비 0.005였다. 축과 감쇠비를 고쳐도 손가락이 묶이지 않았다(g1 0.38일 때 g2 −0.24). mimic을 지우고 `gripper_joint_2` 목표를 매 프레임 측정한 `gripper_joint_1`의 반대 각으로 준다.
3. **손가락 충돌.** 대칭이 된 뒤에도 손가락이 30mm 블록에 닿지 않고 0.380까지 닫혔다. MuJoCo와 같이 손가락마다 보정 접촉점 캡슐 하나로 충돌하고 가져온 손가락 충돌은 끈다. 패드 정의(반지름, 길이, 접촉점 읽기)는 `tools/sim/omx_cell_world.py` 한 곳에 두고 두 백엔드가 쓴다.
4. 마찰 1.0 물리 재질(손가락 패드·상자), articulation 자기 충돌 끔.
5. **보정 각도에 맞추기 (2026-10-28).** 4까지 고친 뒤 Isaac은 5/5였지만 0.385–0.388rad에서 쥐어 교사 판정 하한(0.3935)에 못 미쳤다. 임시 진단(손가락 몸체 위치로 패드 간격 계산)으로 보니 패드 기하는 맞았고(완전히 열었을 때 89.9mm, MuJoCo와 같음) 쥐는 동안 패드가 블록에 한쪽 약 1mm씩 박혔다(패드 간격 27.9–28.5mm). articulation 위치 반복 횟수를 32로 올려도 그대로였다.
   - 패드 rest offset 1mm(contact offset 3mm): 쥐는 동안 패드 간격 30.3mm, 평균 각 0.412. 다만 앞 손가락 0.397, 뒤 손가락 −0.428로 블록이 한쪽으로 밀렸다.
   - 뒤 손가락을 단단한 추종자로(강성 300, 감쇠 5, 힘 상한 2N·m). 실제 그리퍼는 모터 하나가 두 손가락을 움직이고 Gazebo mimic도 강체다. 결과 0.4071/−0.4075, 패드 간격 29.8mm.

rest offset과 추종자 이득은 이 블록(30mm, 20g)에서 보정 각도에 맞춘 값이다. 다른 폭(20/40mm)에서의 각도는 재지 않았다.

## 환경 주의

모델 PC의 `~/rosy-isaac-ready/sdk-path.txt`가 2026-10-27 19:47에 Isaac Lab 3.0 환경(`isaaclab-3.0.0-sim62`)을 가리키도록 바뀌었다. 그 환경에는 이 어댑터가 쓰는 Jazzy 브리지 라이브러리가 없어 실행이 `librcutils.so` 오류로 끝났다. 이 기록의 실행은 모두 `ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv`(Isaac Sim 5.1.0)로 지정했다.

## 명령

```
remote_sim.py --host model --sha <commit> cmd -- 'ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv GRASP_TRIALS=5 tools/sim/run_omx_backend_conformance.sh isaac 240x320 5 grasp'
remote_sim.py --host model --sha <commit> cmd -- 'ISAAC_SDK_VENV=$HOME/rosy-isaac-ready/sdk-venv tools/sim/run_omx_backend_conformance.sh isaac 240x320 5'
```

측정 커밋은 이 기록과 같은 변경의 임시 커밋이다(main 위 `git commit-tree`): 1–4는 `f04cee857f`, 5와 최종 파지·적합성은 `25207499fb`.
