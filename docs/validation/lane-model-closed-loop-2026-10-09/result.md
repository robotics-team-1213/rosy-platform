# 링 맵 차선 모델 폐루프 SIM — 2026-10-09

**판정: 폐루프 연결·비교 실행 완료, 모델 주행 승격 HOLD.** Gazebo `map_v2_fleet_real.world`의 카메라 프레임이 `line_observer`의 도색 입력으로 들어가고, LaneKeeper 관측 → CORE 판단·최종 `cmd_vel` → Gazebo 이동 → 새 카메라 프레임으로 돌아오는 경로를 실제 실행했다. Fleet에는 동일한 한 바퀴 요청을 보냈다. `threshold`와 v11은 `arrived`, PIDNet·U-Net·v13-drivable은 링 진입 전 `stopped / stall`이었다. **도착한 두 조건도 차체 경계 수용 기준은 통과하지 못했다.**

## 고정 조건과 모델 식별

- 모델 PC의 격리된 `~/rosy_d567_ws`, ROS domain 95, Gazebo partition `rosy_lane_loop`, CORE 8594, Fleet 8595를 썼다. 주행 소스는 [D-567 기준 실행](../lane-parallel-correction-baseline-2026-10-09/result.md)의 고정 소스 `4d16150dcd807c7044d44ff2fc122c04e2787876`이며, 이 시험의 [전용 launch](evidence/closed_loop.launch.py)·[실행 스크립트](evidence/run_closed_loop.sh)·[batch](evidence/closed_loop_batch.sh)만 더했다. `line_observer_node.py` SHA-256은 `a37afe3bbfaba1ddcad58f8c8743bb0fe3e6cbbdef028010e15510da59ac0f14`다.
- 다섯 실행 모두 같은 시작 자세 `(-1.26955, 0.24255, -1.5708)`, 한 바퀴 route, Gazebo 월드 SHA-256 `14c8de02f683435a103728a30a24a83237ff9bc03ba1dc6f87a08feb99f31ebb`, CORE overlay SHA-256 `0477d87bd790ceda4a92fb8304a158ecd1a778f65cfcd24e7e08a27efcd2ea69`를 썼다. 실행마다 Gazebo/CORE/Fleet을 다시 시작했고, 각 조건은 **1회**다. 난수 시드의 동일성은 따로 고정·증명하지 않았다.
- PIDNet과 U-Net은 AI PC의 각 고정 체크포인트를 ONNX opset 17로 내보냈다([export.py](evidence/export.py)). 모델 PC ONNX Runtime에서 기록 영상 5장, 384,000화소의 argmax 불일치가 각각 0이었고 최대 절댓값 차이는 PIDNet `8.39e-5`, U-Net `5.25e-5`였다([parity.py](evidence/parity.py)). ONNX SHA-256은 PIDNet `4d4cd27ee374a52ae099c26e7066604e53dcd7bf3d37fed7e60054c9510afe4d`, U-Net `5159bea1cf2a140a93f863cd97ed4fc62bf9e3a953d315e0949989f3f62a978e`다. v11과 v13-drivable ONNX SHA-256은 각각 `5f5ddcd984b3e36b263b24ee1859fea04d10c5d789f231b696517ff9c3c7a9a1`, `982b09a9fc1d0fe83b294329db07e5c9feba21b2bae1d3cdd0aa4ff90b09e711`이다.
- PIDNet·U-Net의 GPU 학습·내보내기는 AI PC에서 했지만, **폐루프 추론은 모델 PC의 CPU ONNX Runtime**에서 실행했다. AI PC에서 Gazebo/Isaac의 카메라·CORE/Fleet 폐루프는 아직 구성·측정하지 않았다. 따라서 여기의 지연과 성공 여부를 AI PC 현장 추론 성능으로 옮기지 않는다.

## 결과

| 도색 입력 | Fleet 결과 | 실제 `learned` 프레임 / 전체 keep | 주요 정지 신호 | 링 호 최대 \|Δr\| | 링 호 최소 원형 대리 여유 |
| --- | --- | ---: | --- | ---: | ---: |
| threshold | arrived | 0 / 520 | 도착 `junction_stop` | 26.8 mm | −21.4 mm |
| PIDNet | stopped / stall | 371 / 371 | `camera_line_not_visible` 77, `stuck_back_off` 56 | 진입 전 정지 | 측정 구간 없음 |
| U-Net | stopped / stall | 362 / 388 | `camera_reselection_required` 91, `camera_line_not_visible` 54 | 진입 전 정지 | 측정 구간 없음 |
| v11 | arrived | 495 / 557 | 도착 `junction_stop`; 62 프레임 fallback | 46.7 mm | −41.3 mm |
| v13-drivable | stopped / stall | 396 / 429 | `obstacle_ahead` 75, `camera_reselection_required` 65 | 진입 전 정지 | 측정 구간 없음 |

수치는 [분석 스크립트](evidence/analyze.py)와 [집계 JSON](evidence/metrics.json)으로 재현한다. `paint_model_revision`이 모델별 ONNX 리비전과 일치하는 프레임만 `learned`로 집계했다. U-Net 26장, v11 62장, v13-drivable 33장은 `denoise_fallback`이다. v11의 완주는 순수 모델만의 완주 증거가 아니다. PIDNet·U-Net·v13의 마지막 Gazebo 참값은 각각 대략 `(-1.271,-0.367)`, `(-1.253,-0.392)`, `(-1.265,-0.378)` m이며 세 실행 모두 링 호의 `lane_arc` 표본이 0이다. 모든 실행의 종료 후 CORE 명령은 `[0,0]`이었다.

원형 대리 여유는 두 도색선 중심 반지름 0.155/0.345 m에서 SIM 충돌 상자 외접 반경 0.08826 m를 뺀 **보수적 진단값**이다(D-567). threshold는 링 호 126틱 중 98틱, v11은 128틱 중 118틱에서 이 대리 여유가 음수였다. 이는 실제 차체 또는 페인트 허용 침범 판정이 아니다. 실제 sweep·차선 폭·정지 중 추가 이동을 검증하기 전까지 둘 다 안전 합격이 아니다. `v13-drivable` 실행에서 소비한 것은 그 모델의 **차선 도색 클래스**뿐이다. drivable 출력으로 경로를 생성하거나 CORE를 조향하지 않았다. 별도 [실물 그림자 결과](../v13-drivable-d554-shadow-drive-2026-10-09.md)의 카펫 오검출 문제는 남아 있다.

## 원시 증거와 다음 가설

- [원시 로그 묶음](evidence/loop_evidence_no_frames.tgz)은 다섯 실행의 `summary.json`, `log.jsonl`, `events.jsonl`, `rec/keep.jsonl`을 담는다. SHA-256 `7270bb7edc152e34edf89f917290f0c791e13c71657f13d9f6a007c6c2676d6c`다. 카메라 원본 `frames.npz`는 모델 PC의 각 `~/rosy_d567_ws/loop_<조건>/lap_d567_baseline/rec/`에 남겼다. 그 SHA-256은 threshold `30440007af22925e74accd199de472a836bdfb8b93d02e4de8489fa6c1fc44ce`, PIDNet `b6290fe1d267cef388ff5c4cc8d56790a51124d948cabca100085ce1c3e11884`, U-Net `39a409a6bcb595029ebc7674416af202fdef9c0695c5410a73965fb7429422b6`, v11 `dd8cf3b8532bac57e8cc1b3499f42ff8ae9b523fd03388517127443052daeec7`, v13 `a49f7491ed43c83b6876c32470a2efa4e156d45e097823218c5816c7f95e9678`이다.
- 첫 가설은 서쪽 직선에서 모델 도색의 좌·우 경계 연속성 또는 재선택이 깨져 CORE의 기존 정지·복구 문턱에 걸렸다는 것이다. 이벤트 수와 정지 위치가 이 가설을 지지하지만, 벽·spoke 오인과 실제 테이프 소실 중 무엇인지는 아직 구분하지 못했다. 실패 직전 영상·마스크·`keep_debug`를 겹쳐 **사람 승인 경계 ID**와 대조한다(D-475). 모델 출력 자체를 정답으로 쓰지 않는다.
- 다음 비교는 동일 시작의 반복, 한쪽 선 가림·역광·벽/교차로 사건, 진짜 차체 sweep과 정지 거리로 한다. PIDNet·U-Net·v13은 현재 구간을 완주하지 못했으므로 승격하지 않는다. v11도 원형 대리 여유 악화와 fallback을 해결하기 전까지 조향 승격 근거가 없다. AI PC 실시간 폐루프가 필요하면 그 호스트의 카메라·시뮬레이터·ROS 경로와 왕복 지연을 별도 구축·측정한다.
