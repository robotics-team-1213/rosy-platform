# D-578 차선 인식 실패 분석 루프 첫 실행 (2026-10-09)

[D-578](../adr/D-578-lane-failure-analysis-loop.md)의 첫 끝-끝 실행 기록이다. 모델 PC에서 `lane_failure_loop.py`의 `collect → vlm → sheets → (Claude 검토) → import-verdicts → fuse`를 돌렸다. 분류는 오프라인이며 주행 수용이나 학습 승인이 아니다.

## 입력과 실행 조건

- 도구 커밋 `4b079efe6`(git archive 스냅숏), 실행 이름 `20261009-b`.
- 녹화 6개(9dfk; `rosy_26`은 9dfk의 옛 장치 이름): `20261009T130633Z_rosy_41`(첫 사례), `20261009T120055Z_rosy_41`, `20261008T163945Z_rosy_26`, `20261008T164108Z_rosy_26`, `20261006T130504Z_rosy_26`, `20261005T150437Z_rosy_26`. 녹화당 가장 긴 사건 2개, 사건당 3프레임. 8kcn(`rosy_60`)의 10-07·10-09 녹화 17개도 받았지만 keep_debug가 없어(line-follow 아님) 사건이 없다.
- 모델: 9dfk shadow `lane-seg-20261006-28e8454d`. 학습 paint를 쓴 녹화는 keep_debug의 revision, threshold·denoise_fallback 녹화는 `--model-for rosy_26=…`(로봇이 그 모델을 쓰지 않았다는 출처와 함께).
- VLM: 모델 PC에 이미 설치된 `qwen3-vl:8b-instruct`(Ollama, loopback), 프롬프트 `lane-failure-identity/1`, 42프레임 프레임당 약 2–4 s(한 번 34 s). AI PC에는 Ollama·VLM이 없어 쓰지 않았다(아래).
- 검토자: Claude Code 하위 에이전트(Opus 5.5)가 시트 폴더만 받아 판정했다. 숨긴 카나리아 4개(손 판정 9dfk 벽 창 `pose_off_lane`, keep만 잃게 바꾼 `keeper_logic`, 차선 마스크 지운 `model_miss`, 어둡게 만든 `camera_exposure`)를 **4/4** 맞혀 묶음이 받아들여졌다.

## 사건별 결과

| 사건 | 녹화 | 구간 s | LiDAR 정면 m | 모델 근거리 차선 / 방향 | keep | VLM 방향 / 선 수 | Claude | 최종 | 경로 |
|---|---|---|---|---|---|---|---|---|---|
| T006 | 130633Z_rosy_41 | 0.0–9.0 | 0.21 | 0.165 / across | no_boundary, learned, transverse 1 | along / 1 | pose_off_lane 0.9 | **pose_off_lane** | stuck 인계 |
| T001 | 130504Z_rosy_26 | 439.6–450.4 | 0.18 | 0.121 / along | no_boundary, threshold, transverse 1 | along / 2 | pose_off_lane 0.7 | pose_off_lane | stuck 인계 |
| T007 | 120055Z_rosy_41 | 11.2–11.9 | 0.21 | 0.167 / across | no_boundary, denoise_fallback, transverse 1 | along / 1 | pose_off_lane 0.85 | pose_off_lane | stuck 인계 |
| T008 | 164108Z_rosy_26 | 160.7–177.8 | 0.24 | 0.272 / across | no_boundary, denoise_fallback | along / 2 | pose_off_lane 0.7 | pose_off_lane | stuck 인계 |
| T009 | 163945Z_rosy_26 | 13.9–18.2 | 0.15 | 0.142 / across | no_boundary, denoise_fallback, transverse 1 | along / 1 | pose_off_lane 0.9 | pose_off_lane | stuck 인계 |
| T010 | 150437Z_rosy_26 | 68.2–79.5 | 0.11 | 0.032 / across | no_boundary, threshold | along / 0 | pose_off_lane 0.75 (앞 로봇이 시야를 막음) | pose_off_lane | stuck 인계 |
| T011 | 163945Z_rosy_26 | 30.2–31.6 | 0.35 | 0.029 / across | no_boundary, denoise_fallback | both / 2 | keeper_logic 0.45 | — | 사람 대기 (확신도 미달) |
| T012 | 150437Z_rosy_26 | 228.2–236.5 | 0.28 | 0.028 / across | no_boundary, threshold | both / 2 | pose_off_lane 0.5 | — | 사람 대기 (확신도 미달) |
| T013 | 164108Z_rosy_26 | 121.6–133.6 | 0.15 | 0.125 / along | no_boundary, denoise_fallback | along / 2 | pose_off_lane 0.7 | — | 사람 대기 (사실 불일치: 가로선 없음, VLM along) |
| T014 | 130504Z_rosy_26 | 578.9–585.8 | 0.34 | 0.062 / across | no_boundary, threshold, transverse 1 | along / 1 | keeper_logic 0.4 | — | 사람 대기 (확신도 미달) |

요약: 사건 10개 중 `pose_off_lane` 6, 사람 대기 4, `model_miss` 0이라 라벨 후보는 0프레임이다. 첫 사례 9dfk 벽(T006)은 `pose_off_lane`으로 끝나 학습 자료가 되지 않는다.

## 관찰

- VLM은 9dfk 벽 사례 3프레임 모두에서 선이 화면을 "along"으로 간다고 답했고, 어둡게 만든 카나리아에서 선 4개를 봤다고 답했다. VLM 사실은 규칙의 한 항일 뿐이고 이 사건들의 결론은 LiDAR·keep transverse·모델 방향으로 정해졌다. D-492·D-554의 교훈과 같다.
- 9dfk의 lane 손실은 이번 표본에서 대부분 벽 앞·코너 회전 뒤 자세 문제였다. 모델 놓침 후보를 모으려면 직선·곡선 주행 중 손실(`denoise_fallback`이 아닌 `learned` paint)이 있는 녹화가 더 필요하다.
- 8kcn의 최근 녹화에는 keep_debug가 없다. 실패 분석에 넣으려면 line-follow 주행으로 녹화해야 한다.

## 다시 돌리는 법

모델 PC에서 커밋 스냅숏을 풀고(`git archive <commit> learning/training/perception middleware/perception/control middleware/apps/device/pinky contracts/foundation`), `lane_failure_loop.py collect … --canary-bank <bank.json>` → `vlm` → `sheets` 순으로 돌린다. 검토자에게는 `RUN/sheets/`만 준다(`RUN/key.json`은 주지 않는다). 판정 JSONL을 `import-verdicts`로 들이고 `fuse`를 돌린다. 실행 산출물은 모델 PC `~/rosy-ml/lane-failure-loop/runs/20261009-b/`와 운영 PC `X:\DevTemp\lane-fail-loop\20261009-b\`에 있다(저장소에 넣지 않는다).

## 열린 항목

- AI PC: Ollama·VLM이 설치돼 있지 않다. 2026-10-09 GPU에는 다른 사람의 SAM 2.1 검토 워커(약 2 GB)가 있었다. 설치·포트·GPU 사용은 소유자 동의 뒤에만 한다.
- 사람 대기 4건(T011–T014)은 검수 앱 원인 판정 화면이 없어 파일(`human-queue.jsonl`)로만 남았다.
- 천장 카메라 자세는 과거 녹화와 시각이 맞는 기록이 없어 붙이지 않았다.
- 실시간 stuck 처리는 Fleet 세션(D-577 예약) 몫이고, `stuck-handoff.jsonl`이 그쪽 입력 후보다.
