# VLM 닫힌 질문 벤치 v2와 T1 정답 묶음 — 2026-10-23 (b)

**앞 회차:** [vlm-question-bench-2026-10-23](../vlm-question-bench-2026-10-23/result.md). **도구 리비전:** 이 기록과 같은 커밋(`feat/vlm-question-set-v2`).
**범위:** 질문 세트 v2의 front 답 분포·지연, 그리고 사람 정답(T1)용 화면 준비. 사람 정답이 아직 없으므로 정확도 수치가 아니다.

## 바꾼 것

- `front.thing`(wall/object/robot/person/none 다지선다)을 `front.wall_ahead`·`front.robot_ahead`·`front.person_ahead` yes/no/unclear 세 질문으로 나눴다(`QUESTION_SET = "v2"`). v1은 40장 모두 거의 `wall`이었다.
- 같은 사진 종류의 `--frames`를 여러 번 주면 합쳐서 표본을 뽑는다(v1 도구는 마지막 것만 남겼다).
- `tools/vlm_label_sheet.py`: 벤치 `rows.jsonl`의 사진을 정적 HTML 한 장으로 묶는다. 사람이 질문마다 답을 고르고 `labels.jsonl`(사진 sha256, 질문 세트, 답, 라벨러)을 내려받는다. 모델 답은 보여주지 않는다.

## v2 front (60장: 8kcn 2026-10-09 431장 + 9dfk d592 dry1–3 317장에서 고정 시드)

| 모델 | p50 | p95 | prefix p50 | 질문 1개 p50 | 캐시 검사 최대 차이 / 답 바뀜 |
| --- | --- | --- | --- | --- | --- |
| Qwen3-VL-8B nf4 | 0.452 | 1.400 | 0.125 | 0.049 | 0.040 / 0 |
| Qwen3-VL-4B bf16 | 0.251 | 0.729 | 0.063 | 0.030 | 0.098 / 0 |
| Ollama `qwen3-vl:8b-instruct` 질문 6개 | 0.253 | 0.273 | — | — | transformers 8B와 답 일치 0.828 |
| Ollama 현행 관찰 호출 1회 | 1.714 | 1.831 | — | — | — |

| 질문 | 8B yes / no (또는 분포) | 4B |
| --- | --- | --- |
| `front.lane_obstruction` | 28 / 32 | 3 / 57 |
| `front.wall_ahead` | 4 / 56 | 1 / 59 |
| `front.robot_ahead` | 0 / 60 | 0 / 60 |
| `front.person_ahead` | 0 / 60 | 0 / 60 |
| `front.lane_tape` | left 25, right 35 | left 60 |
| `front.shape` | bend 52, straight 8 | bend 51, straight 9 |

- `wall` 쏠림은 풀렸다.
- `lane_obstruction`은 두 모델이 크게 갈려 정답 없이는 판단할 수 없다.
- 4B의 `lane_tape`는 한쪽으로 쏠렸다.
- 표본에 로봇·사람이 앞에 있는 장면이 없어 `robot_ahead`·`person_ahead`의 yes 쪽은 이번 표본으로 평가할 수 없다. T1에서는 그런 장면을 따로 골라 넣어야 한다.

## T1 정답 묶음

모델 PC `~/rosy-test/vlm-bench/labels-T1-20261023/{front,top,wrist}/index.html`. 그 폴더를 브라우저로 연다.

| 묶음 | 화면 | 사진 파일 | 원본 rows | index.html |
| --- | --- | --- | --- | --- |
| front (v2 질문 6개) | 60 | 60 | 이 회차 8B front | sha256 `b0c117eb8f53863469d1ab6be4deeeda6970707e8e1c378f3e2a21019477ee8b` |
| top (2개) | 40 | 40 | 앞 회차 8B top | sha256 `20ba2eed6b35ad946de0525d935ea57b12930297b7e779bc83da89ec621c9973` |
| wrist (2개) | 40 | 35 (내용 같은 사진 5쌍) | 앞 회차 8B wrist | sha256 `d73bca675089f37dbb0b8ad7546e24c2a01383b363d085524ec7c9e858e6945c` |

화면 점검: 모델 PC headless Chromium 390×844에서 선택 → 진행 표시 2/6, 이름 없이 내려받기 → 경고, 이름 입력 후 `labels.jsonl` 3줄, 가로 스크롤 없음(`scrollWidth` 390).

## 원본

모델 PC `~/rosy-test/vlm-bench/out-v2/<모델>-front/`, 실행 스크립트 `v2.sh`·`v2b.sh`. 첫 4B 실행은 앞서 멈추지 못한 프로세스와 GPU를 같이 써서 메모리 부족으로 실패했고, 그 프로세스를 멈춘 뒤 다시 돌렸다.

| 파일 | 해시 |
| --- | --- |
| Qwen3-VL-8B-Instruct-front/rows.jsonl | sha256 `a05e97e047f96d5210c71ac51ad2d88a0e630c5c4fe99553737ca9a1b306c8ee` |
| Qwen3-VL-4B-Instruct-front/rows.jsonl | sha256 `5c108d4baabe350456e1e8cc6f08b5907240a5050b7cdac80862cb74086fe872` |
