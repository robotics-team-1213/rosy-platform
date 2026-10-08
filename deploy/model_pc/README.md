# Model PC Decision 평가

[D-527](../../docs/adr/D-527-decision-test-host-boundaries.md)의 L0 실행 위치다. 개발 로컬 PC는 `test/test_decision_replay.py`와 lint·푸시 검사를 수행한다. 모델 PC는 사람 정답이 있는 독립 세트로 텍스트 Laya/Kev/규칙 기준선을 비교하고, VLM은 별도의 영상·LiDAR 정답 세트로 평가한다. AI PC의 역할은 승인된 고정 버전의 적재·추론 스모크와 watchdog 확인이다.

1. 사건을 비식별화하고 수집 세션 단위로 개발/독립 세트를 분리한다. 텍스트 JSONL은 `id`, `state`, `instructions`, `criteria`, `expected` 계약을 따른다. VLM 프레임·정답은 텍스트 세트에 섞지 않는다.
2. 모델 PC에서 고정 모델·토크나이저·서버 revision을 기록하고 로컬 서버를 `127.0.0.1`에만 연다. 같은 독립 세트와 질문/선택지를 각 후보에 사용한다. `python3 tools/decision_replay.py <independent-set.jsonl> --model <model-id> > <receipt.json>`으로 텍스트 후보를 재생한다. 도구의 기본 endpoint는 loopback이다.
3. receipt의 세트 SHA-256, 정답·예측·오류·기권·p95를 보존하고 모델 revision, 서버 버전, GPU 사용량, 질문 버전과 함께 평가 기록을 만든다. 사람 정답이 없으면 연결 시험으로만 표기한다. VLM에는 D-492의 별도 V0/V1 평가 관문을 적용한다.
4. 평가 통과 뒤 고정 ModelProfile **후보**와 digest, 최소 비식별 스모크 입력만 AI PC로 전달한다. 실제 전달 방식·인증·승인 스키마가 정해지기 전에는 자동 배포하지 않는다. AI PC는 자체 평가로 후보를 바꾸거나 승격하지 않는다.

실제 장치 주소·계정·비밀, 원본 사건, 모델 가중치와 실행 로그는 이 공개 저장소에 넣지 않는다. 현재 Model PC의 GPU 인식은 확인했으나 Decision 전용 평가 환경과 사람 정답 세트는 아직 확인되지 않아 L0은 HOLD다.
