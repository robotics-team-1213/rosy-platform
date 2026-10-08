# Model PC Decision 평가

## Pinky Pilot 녹화 자동 수신 (D-534)

`rosy-pilot-fetch@.timer`는 모델 PC 사용자 세션에서 종료된 Pilot 녹화를 10분마다 확인한다. 수신은 기존 `fetch_http.py`가 CORE의 정지 판정, 장치 TLS, Operator 권한, 원본 SHA-256, MP4 변환과 조작 짝 검사를 수행한다. 이 작업은 원본·영상까지이며 픽셀 초안, 사람 승인, 학습은 별도 단계다.

설치 전 모델 PC의 `~/rosy-ml/bin/fetch_http.py`와 checkout의 `tools/perception/dataset/bag_to_video.py`를 확인하고, 이 버전의 수신기를 모델 PC에 배치한다. 각 로봇 인스턴스의 장치 CA를 `~/rosy-ml/<id>-ca.pem`, 읽기 전용 Operator 토큰을 `~/.config/rosy/pilot-<id>.operator-token`에 배치한다. `~/.config/rosy/pilot-<id>.env`에는 `SINCE_ID=<첫 자동 수집 세션 ID>`를 넣는다. 기존 세션에 조작 짝이 없어 실패가 반복되는 것을 막는 경계다. 파일 내용과 로봇 주소를 Git에 넣지 않는다. 한 로봇의 예:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/model_pc/rosy-pilot-fetch@.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start rosy-pilot-fetch@9dfk.service
systemctl --user status rosy-pilot-fetch@9dfk.service --no-pager
systemctl --user enable --now rosy-pilot-fetch@9dfk.timer
journalctl --user -u rosy-pilot-fetch@9dfk.service -n 80 --no-pager
```

`9dfk`는 설치 예시의 mDNS ID이며 현장 로봇 ID를 사용한다. `start`에서 정지·토큰·TLS·해시·변환 결과를 확인한 뒤 타이머를 켠다. 변환이 실패하면 검증된 raw 폴더는 남고 재수신은 건너뛰므로 `bag_to_video.py`를 해당 세션에 수동 재실행한다. 로봇의 원본과 승인 상태는 이 타이머가 변경하지 않는다.
물리 로그인 코드로 받은 Operator 토큰은 만료된다(D-193 기본 7일). 만료 전에 새 코드로 재페어링하고 타이머의 마지막 성공 시각을 확인한다.

[D-527](../../docs/adr/D-527-decision-test-host-boundaries.md)의 L0 실행 위치다. 개발 로컬 PC는 `test/test_decision_replay.py`와 lint·푸시 검사를 수행한다. 모델 PC는 사람 정답이 있는 독립 세트로 텍스트 Laya/Kev/규칙 기준선을 비교하고, VLM은 별도의 영상·LiDAR 정답 세트로 평가한다. AI PC의 역할은 승인된 고정 버전의 적재·추론 스모크와 watchdog 확인이다.

1. 사건을 비식별화하고 수집 세션 단위로 개발/독립 세트를 분리한다. 텍스트 JSONL은 `id`, `state`, `instructions`, `criteria`, `expected` 계약을 따른다. VLM 프레임·정답은 텍스트 세트에 섞지 않는다.
2. 모델 PC에서 고정 모델·토크나이저·서버 revision을 기록하고 로컬 서버를 `127.0.0.1`에만 연다. 같은 독립 세트와 질문/선택지를 각 후보에 사용한다. `python3 tools/decision_replay.py <independent-set.jsonl> --model <model-id> > <receipt.json>`으로 텍스트 후보를 재생한다. 도구의 기본 endpoint는 loopback이다.
3. receipt의 세트 SHA-256, 정답·예측·오류·기권·p95를 보존하고 모델 revision, 서버 버전, GPU 사용량, 질문 버전과 함께 평가 기록을 만든다. 사람 정답이 없으면 연결 시험으로만 표기한다. VLM에는 D-492의 별도 V0/V1 평가 관문을 적용한다.
4. 평가 통과 뒤 고정 ModelProfile **후보**와 digest, 최소 비식별 스모크 입력만 AI PC로 전달한다. 실제 전달 방식·인증·승인 스키마가 정해지기 전에는 자동 배포하지 않는다. AI PC는 자체 평가로 후보를 바꾸거나 승격하지 않는다.

실제 장치 주소·계정·비밀, 원본 사건, 모델 가중치와 실행 로그는 이 공개 저장소에 넣지 않는다. 현재 Model PC의 GPU 인식은 확인했으나 Decision 전용 평가 환경과 사람 정답 세트는 아직 확인되지 않아 L0은 HOLD다.
