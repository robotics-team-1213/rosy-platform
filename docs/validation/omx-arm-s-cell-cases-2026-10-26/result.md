# 공급암 S 셀 실물 사례를 Isaac에서 재현 (2026-10-26)

- **범위:** 2026-10-25 실물 셀에서 멈춘 사례(`docs/validation/omx-arm-s-real-cell-pipeline-2026-10-25/result.md`)를 사례 묶음으로 만들어 모델 PC Isaac 5.1.0.0에서 같은 청크 프레임으로 재생했다. 판정은 상자·손가락·관절 오차 측정값만 본다. 학습 정책·실물 수용·카메라 정합이 아니다.
- **실행:** `deploy/robot/omx/cell_cases.py --cases <Fleet PC cases.jsonl> --out suite.json` → `deploy/robot/omx/cell_case_suite.py --suite suite.json --sha <커밋> --out <폴더>`. 각 사례는 실행 관리자의 `arm-s-cell-case` 실행이다. 실물 `cases.jsonl` 4줄에는 아직 장면(`scene`) 기록이 없어 묶음은 실물 정지 6건(`REAL`)으로만 만들었다.
- **시험:** `learning/envs/isaac/test`, `test/test_omx_cell_cases.py`, `test/test_omx_isaac_cell_frames.py`, `test/test_remote_isaac.py`, `test/test_omx_cell_pipeline.py` 원격 통과.

## 결과

| 실물 정지 | 실물 결과 | Isaac 결과 | 실행 | 판정 |
|---|---|---|---|---|
| 3: 시작 기준이 약 3 cm 어긋남 | placed | held_not_placed | FAILED 0257ed5442 | Isaac 알려진 차이(집게가 상자를 흘림) |
| 4: 상자 가장자리가 Pinky 프레임 위 | frame_contact | frame_contact | SUCCEEDED 551e668715 | 일치 |
| 5: 25° 돌아간 상자, 사이트 각도 | not_held | held_not_placed | FAILED 03c847f70a | Isaac 알려진 차이(25° 상자를 잡고 흘림) |
| 5: 카메라 각도 10° 제한(후보) | — | held_not_placed | SUCCEEDED 3a0b7bdbce | 측정값 |
| 1: 건강 표본 지연 | — | 재현 안 함(실물 버스 타이밍) | — | `test/test_omx_chunk_runner.py` |
| 2: 집게 끝을 넘는 닫기 | — | 재현 안 함(실물 집게의 기계적 끝) | — | `test/test_omx_chunk_runner.py`, `test/test_omx_cell_pipeline.py` |

## 한계

- **Isaac 집게:** 두 손가락이 따로 힘 한도에 걸려 상자가 집게 안에서 옆으로 흐른다(`docs/validation/omx-arm-s-isaac-cell-2026-10-25/result.md`). 사례 3·5는 이 때문에 실물과 다르다. 사례에 `isaac_gap`으로 적어 두었고, Isaac 결과가 그 값과 달라지면(좋아지든 나빠지든) 묶음이 다시 실패로 알린다.
- **정정:** 2026-10-25 기록은 실행 관리자 UNKNOWN을 GPU를 같이 쓰는 ollama 때문으로 적었다. 실제로는 worker가 공급암 S 보고서에 없는 `completed_frames`를 읽다 죽은 것이다. 원인과 고침은 `docs/solutions/runtime-errors/isaac-run-unknown-was-a-worker-crash-not-the-gpu-2026-10-26.md`.
- **Gazebo:** 사례 묶음은 아직 Isaac에만 들어간다. Gazebo 시나리오는 이름이 정해진 실험(`pick-place-chunks-*`)만 받는다.
