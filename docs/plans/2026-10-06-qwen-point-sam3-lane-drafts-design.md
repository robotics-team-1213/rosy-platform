# Qwen 점 → SAM 3 전파로 차선·도로 픽셀 초안 만들기 (설계)

**날짜:** 2026-10-06
**상태:** 설계 승인(사용자, 2026-10-06). 구현·설치·착지 승인 아님.
**관련:** D-379(기하 자동 라벨), D-462/D-464(픽셀 검수·학습 자격), D-465(모델 PC 픽셀 초안), D-475(평가 정답·drivable 정의)

## 목적

D-379 자동 라벨은 벽·바닥은 LiDAR로 믿을 만하지만 drivable은 주행 궤적 0.10 m 띠뿐이다. D-475 §8의 drivable(흰 경계선 안쪽 보이는 도로 전체)과 다르다. 차선도 기존 모델 초안은 과노출·카펫 무늬에서 틀린다(2026-10-06 spin 세션). 이 설계는 lane_line과 drivable 초안을 사람이 덜 고치게 만드는 것이 목표다.

## 범위

- 대상 클래스: `lane_line`(1), `drivable`(3). `wall`(2)·`floor`(0)는 D-379 결과 그대로. `stop_line`·`crosswalk`는 이번 범위 밖.
- 산출물은 **학습용 초안**뿐이다. 자동 승인 없음. 평가 정답 경로는 아래 「평가셋」 절.
- 실행 위치: 모델 PC(D-434). 소스: `learning/training/perception/dataset/`.

## 흐름

```
세션 frames/ + D-379 masks/
  ① point_draft.py   Qwen3-VL(Ollama) → 키프레임 클래스별 점
  ② gate_points()    D-379 마스크로 점 검사 → 통과한 점만
  ③ sam3_mask_draft.py  SAM 3.1 비디오 예측기: 키프레임 seed → 전파 → 재시드
  ④ compose_class_map() lane/drivable + D-379 wall/floor → indexed PNG(255 = 미확신)
  ⑤ verified-inputs.jsonl → review_ingest (기존) → 사람 승인 → review_dataset → build → 학습
```

### ① 점 찍기 — `point_draft.py`

- 모델: `qwen3-vl:8b-instruct`(Ollama, 모델 PC 로컬). `reasoning_effort: none`, `OLLAMA_CONTEXT_LENGTH=8192`(2026-10-06 파일럿 교훈).
- 요청: 흰 경계선마다 3~6점(선마다 `track_id` 구분), 선 안쪽 도로 2~3점, 도로 밖·벽 음성점 2개.
- Qwen3-VL 좌표는 0–1000 상대값 → 원본 픽셀로 변환. (`vision_draft.py`의 픽셀 가정은 이 경로에 쓰지 않는다.)
- 출력 `points.jsonl` 행: `{index, image_sha256, class, track_id, points: [[x, y, +1|-1], ...], model, prompt_id}`.
- 키프레임에서만 호출(③의 재시드 프레임 포함).

### ② 점 검사 — `gate_points()` (numpy, GPU 없음)

D-379 마스크와 프레임 밝기로 각 점을 확인한다.

| 점 | 남기는 조건 |
|----|------------|
| lane_line + | D-379가 floor 또는 lane_line으로 본 픽셀 **그리고** 밝은 픽셀(임계값은 프레임 floor 밝기 기준 상대값) |
| drivable + | D-379 floor/drivable **그리고** 밝지 않음 |
| 음성 − | D-379 wall, 또는 floor이면서 lane 바깥 |
| D-379가 255 | 판단 불가 → 버림 |

선 하나(`track_id`)에서 통과한 양성점이 2개 미만이면 그 선은 버린다. 목적: Qwen 오검출(삼각대 다리, 벽 균열 — 2026-10-06 파일럿)이 SAM seed가 되지 않게 한다. VLM은 후보를 내고, 채택은 센서가 정한다.

### ③ SAM 3 전파 — `sam3_mask_draft.py`

- SAM 3.1 비디오 예측기(`facebook/sam3.1`, `sam3.1_multiplex.pt`). 선마다 object id 하나, drivable 영역 object id 하나.
- 키프레임에 ②의 점을 넣고 이후 프레임으로 전파한다.
- 재시드(그 프레임에서 ①②부터 다시) 조건, 하나라도 맞으면:
  - 마지막 seed 후 15프레임
  - lane 마스크 픽셀 중 「밝음 ∧ LiDAR floor」 비율 < 0.6
  - object 마스크 면적이 직전 프레임 대비 ×2 초과 또는 ×0.5 미만
- 세 값은 CLI 인자로 둔다(실영상에서 조정).
- 모델 적재: Qwen과 SAM을 동시에 VRAM에 두지 않는다. 세션 단위로 ① 전체 키프레임 → Qwen 내림 → ③ 실행, 재시드가 필요한 프레임은 모아서 다음 패스에서 처리한다(최대 3패스, 남은 프레임은 v2 초안 유지).

### ④ 클래스 맵 합성 — `compose_class_map()`

- `lane = SAM lane ∩ (밝음 ∧ dilate(LiDAR floor))` — 얇은 선에서 SAM이 번지는 것을 자른다.
- `drivable = SAM drivable − lane − D-379 wall`
- wall/floor는 D-379 그대로. 어느 출처도 확신하지 않는 픽셀은 255.
- 클래스 id는 기존 `classes.yaml`(floor 0, lane_line 1, wall 2, drivable 3, stop_line 4, crosswalk 5) 그대로.

### ⑤ 리뷰 앱 연결

- 기존 `review_ingest.py` 입력(`verified-inputs.jsonl`, `mask: {indexed_png, sha256, classes_sha256}`)을 그대로 쓴다. 리뷰 앱은 바꾸지 않는다.
- 출처 receipt(D-465 §6): Qwen 모델·프롬프트 id, SAM 체크포인트 sha256, 재시드 횟수, gate 통과/거절 수, source commit → 실행 폴더의 `receipt.json`.
- 리뷰 순서: 기존 v2 초안과 픽셀 불일치가 큰 프레임 먼저.
- `process_session.sh`의 v2 초안 단계를 이 단계로 바꾼다(실패 프레임은 v2 초안으로 남음).

## 실패 처리

- Qwen 응답 없음·JSON 깨짐·gate 통과 0 → 그 프레임은 v2 초안. receipt에 사유.
- SAM OOM·예외 → 그 세션 중단, 이미 쓴 프레임은 유지, 재개 가능. 빈 background로 바꾸지 않는다(D-465 §6).
- 어떤 경우에도 `review_status`는 `pending_human`.

## 평가셋

D-475 §7: 평가 정답 초안에 모델 출력을 쓰지 않고, SAM은 사람이 찍은 점만 다듬는다. 평가 프레임은 ①을 건너뛰고, 리뷰 앱에서 사람이 찍은 점을 ②③④에 넣는다. 같은 도구, 점의 출처만 다르다. 점 입력 UI는 이 설계의 범위 밖(후속).

## 검증

- 단위 테스트(합성 numpy 이미지, GPU 없음): 0–1000 → 픽셀 변환, `gate_points()` 표 4행, `compose_class_map()` 우선순위·255 처리.
- 파일럿(모델 PC): 20프레임 세트 + spin 세션 2개(frames 20–62). 사람이 승인한 마스크와 초안의 IoU(lane_line, drivable)를 v2 초안과 비교한다. 장당 수정 시간·처리 시간·peak VRAM·재시드 횟수·gate 거절률도 기록. 합격 수치는 실행 전에 정해 기록한다(D-465 §8).

## 문서

D-465 추가 조항: §2의 SAM 2 계열에 SAM 3/3.1(점 프롬프트, 비디오 전파)을 더하고, VLM 점은 D-379 기하 검사를 통과한 것만 seed로 쓰며 학습 초안 전용임을 적는다. 새 ADR 번호는 쓰지 않는다.

## 선행 조건

- 모델 PC 이더넷 연결(현재 Wi-Fi만, 20–40 KB/s)
- Hugging Face `facebook/sam3`, `facebook/sam3.1` gated 승인 + 토큰
- Ollama 설치 + `qwen3-vl:8b-instruct` 받기
- 공식 `facebookresearch/sam3` 설치(기존 `~/rosy-ml/.venv`의 torch 유지)

## 하지 않는 것

- stop_line·crosswalk·객체 박스 마스크
- 리뷰 앱 UI 변경(평가용 점 입력 포함)
- 자동 승인, 평가 정답 자동 생성
- Qwen fine-tune, SAM fine-tune
