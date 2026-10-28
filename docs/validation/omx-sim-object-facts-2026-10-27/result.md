# D-877: 물체 위치 평가 사실과 흔들림 검사, 탐침 PASS 순서 (2026-10-27)

## 주장과 한계

MuJoCo와 Isaac 어댑터가 작업 장면의 움직이는 상자(슬립 시트, 투입 블록)의 world 위치를 `/sim/object_tf`(tf2 `TFMessage`)로 낸다. D-866 §2의 평가용 사실이며 정책 입력이 아니다. 적합성 도구는 기록 구간(팔을 움직이기 전) 동안 손대지 않은 상자가 5mm 넘게 움직이면 실패로 보고, 상자별 흔들림을 결과에 남긴다. Gazebo는 아직 이 토픽을 내지 않으며, 토픽이 없으면 검사를 건너뛴다.

두 Gazebo 탐침(`policy_chain_gazebo.py`, `policy_chain_vla_gazebo.py`)은 이제 정리가 끝난 뒤에만 PASS 줄을 찍고, 정리가 실패하면 시나리오의 원래 실패를 원인으로 남긴다. 두 카메라 사슬 시험은 저널의 intent가 두 프레임 해시를 모두 담는지 확인한다.

**한계:** 두 백엔드 모두 흔들림이 정확히 0.0mm였다. MuJoCo는 물리 상태(`data.body().xpos`)를 내므로 실제 값이다. Isaac의 `ROS2PublishTransformTree`가 물리 결과가 아니라 USD에 적은 자세를 읽는다면 늘 0이 나온다. 상자를 실제로 움직이는 실행(파지 시험)으로 확인하기 전에는 Isaac 값의 의미를 주장하지 않는다.

## 결과

커밋 `e31c367875`, 한 번에 시험 PC 한 대.

| 실행 | PC | 판정 | 실시간 배율 | 흔들림(슬립 시트/투입 블록) | 취소 전/뒤 joint1 |
|---|---|---|---|---|---|
| MuJoCo 적합성 240×320·10Hz | AI PC | 통과 | 0.998 | 0.0 / 0.0 mm | 0.051 / 0.00007 rad |
| Isaac 적합성 240×320·10Hz | 모델 PC | 통과 | 0.932 | 0.0 / 0.0 mm | 0.069 / 0.0 rad |
| 단일 카메라 Gazebo 탐침 | AI PC | PASS 뒤 EXIT_OK | | | |
| VLA P0 stale | AI PC | PASS 뒤 EXIT_OK | | | |

- 원격 pytest(`test/test_omx_sim_backends.py`, `test/test_omx_backend_conformance.py`, `test_policy_chain.py`) 통과. 적합성 시험은 흔들린 물체를 실패로, 가만한 물체와 사실 토픽이 없는 백엔드를 통과로 본다.

## 운영 중 발견

10-27 디스크 정리로 AI PC의 벤더 OMX overlay(`~/rosy-test/omx-native-sim-preparation-*/install`)가 지워졌다. 저장소에는 이것을 다시 만드는 도구가 없다. 모델 PC의 사본(30MB)을 옮겨 복구했고, setup 스크립트를 뺀 모든 파일이 모델 PC와 바이트 단위로 같음을 확인했다. 첫 복구 때 경로를 바꾸는 sed가 `.pyc`까지 고쳐 벤더 launch가 "bad marshal data"로 실패했고, `.pyc`를 지워 해결했다. 시험 PC 환경을 저장소에서 다시 만들 수 있게 하는 작업은 따로 제안했다.
