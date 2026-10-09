# Model PC Decision 평가

## Pinky Pilot 녹화 자동 수신 (D-534)

`rosy-pilot-fetch@.timer`는 모델 PC 사용자 세션에서 종료된 Pilot 녹화를 10분마다 확인한다. 수신은 기존 `fetch_http.py`가 CORE의 정지 판정, 장치 TLS, Operator 권한, 원본 SHA-256, MP4 변환과 조작 짝 검사를 수행한다. 이 작업은 원본·영상까지이며 픽셀 초안, 사람 승인, 학습은 별도 단계다.

설치 전 모델 PC의 `~/rosy-ml/bin/fetch_http.py`와 checkout의 `learning/training/perception/dataset/bag_to_video.py`를 확인하고, 이 버전의 수신기를 모델 PC에 배치한다. 각 로봇 인스턴스의 장치 CA를 `~/rosy-ml/<id>-ca.pem`, 읽기 전용 Operator 토큰을 `~/.config/rosy/pilot-<id>.operator-token`에 배치한다. `~/.config/rosy/pilot-<id>.env`에는 `SINCE_ID=<첫 자동 수집 세션 ID>`를 넣는다. 기존 세션에 조작 짝이 없어 실패가 반복되는 것을 막는 경계다. 파일 내용과 로봇 주소를 Git에 넣지 않는다. 한 로봇의 예:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/model_pc/rosy-pilot-fetch@.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start rosy-pilot-fetch@9dfk.service
systemctl --user status rosy-pilot-fetch@9dfk.service --no-pager
systemctl --user enable --now rosy-pilot-fetch@9dfk.timer
journalctl --user -u rosy-pilot-fetch@9dfk.service -n 80 --no-pager
```

`9dfk`는 설치 예시의 mDNS ID이며 현장 로봇 ID를 사용한다. `start`에서 정지·토큰·TLS·해시·변환 결과를 확인한 뒤 타이머를 켠다. 변환이 실패하면 검증된 raw 폴더를 남기고 다음 주기에 로컬 변환을 재시도한다. 성공 영수증은 사이드카 해시·영상 존재·조작 짝을 확인한 뒤에만 만든다. 로봇의 원본과 승인 상태는 이 타이머가 변경하지 않는다.
물리 로그인 코드로 받은 Operator 토큰은 만료된다(D-193 기본 7일). 만료 전에 새 코드로 재페어링하고 타이머의 마지막 성공 시각을 확인한다.

[D-527](../../docs/adr/D-527-decision-test-host-boundaries.md)의 L0 실행 위치다. 개발 로컬 PC는 `test/test_decision_replay.py`와 lint·푸시 검사를 수행한다. 모델 PC는 사람 정답이 있는 독립 세트로 텍스트 Laya/Kev/규칙 기준선을 비교하고, VLM은 별도의 영상·LiDAR 정답 세트로 평가한다. AI PC의 역할은 승인된 고정 버전의 적재·추론 스모크와 watchdog 확인이다.

1. 사건을 비식별화하고 수집 세션 단위로 개발/독립 세트를 분리한다. 텍스트 JSONL은 `id`, `state`, `instructions`, `criteria`, `expected` 계약을 따른다. VLM 프레임·정답은 텍스트 세트에 섞지 않는다.
2. 모델 PC에서 고정 모델·토크나이저·서버 revision을 기록하고 로컬 서버를 `127.0.0.1`에만 연다. 같은 독립 세트와 질문/선택지를 각 후보에 사용한다. `python3 tools/decision_replay.py <independent-set.jsonl> --model <model-id> > <receipt.json>`으로 텍스트 후보를 재생한다. 도구의 기본 endpoint는 loopback이다.
3. receipt의 세트 SHA-256, 정답·예측·오류·기권·p95를 보존하고 모델 revision, 서버 버전, GPU 사용량, 질문 버전과 함께 평가 기록을 만든다. 사람 정답이 없으면 연결 시험으로만 표기한다. VLM에는 D-492의 별도 V0/V1 평가 관문을 적용한다.
4. 평가 통과 뒤 고정 ModelProfile **후보**와 digest, 최소 비식별 스모크 입력만 AI PC로 전달한다. 실제 전달 방식·인증·승인 스키마가 정해지기 전에는 자동 배포하지 않는다. AI PC는 자체 평가로 후보를 바꾸거나 승격하지 않는다.

실제 장치 주소·계정·비밀, 원본 사건, 모델 가중치와 실행 로그는 이 공개 저장소에 넣지 않는다. 현재 Model PC의 GPU 인식은 확인했으나 Decision 전용 평가 환경과 사람 정답 세트는 아직 확인되지 않아 L0은 HOLD다.

## v13 검수 앱 코드 릴리스

검수 앱은 모델 PC의 `~/rosy-ml/review-v13-code/releases/<release>/`에 완전한 실행 소스를 보존하고, 사용자 서비스 `rosy-review-v13.service`는 `~/rosy-ml/review-v13-code/current` 링크를 실행한다. 검수 기록인 `~/rosy-ml/review-v13-drivable/state`는 릴리스 밖에 둔다. 기존 런타임 폴더를 다시 풀거나 교체해도 `current`가 가리키는 화면은 바뀌지 않는다. 배포 결정은 [D-545](../../docs/adr/D-545-model-pc-review-versioned-release.md)을 따른다.

첫 전환에서는 **현재 모델 PC에서 실제 실행 중인, 검수 스튜디오가 적용된 코드 폴더**에서 코드 전용 입력을 만든다. 그 폴더에는 과거 `state/`가 들어 있을 수 있으므로 반드시 제외한다. 이후에는 검증한 정확한 Git 커밋의 전체 검수 앱 소스를 모델 PC의 별도 준비 폴더에 전송한 후 같은 명령을 사용한다. `review_app.py`, `review_app_web/`, `shared/web/` 및 해당 모듈의 Python import 경로를 포함해야 한다. 소스 폴더에는 DB, 영상, 모델 가중치나 비밀을 넣지 않는다. 릴리스 이름은 출처를 식별할 수 있게 고정하며 재사용하지 않는다. 전송 자체는 자동 갱신되지 않으며, 이 명령을 실행해야 화면이 전환된다.

```bash
# 첫 전환: 모델 PC에서 기존 실행 코드만 별도 입력으로 준비한다.
mkdir -p /tmp/rosy-review-code-<release-id>
rsync -a --exclude=/state/ <current-code-directory>/ /tmp/rosy-review-code-<release-id>/

# 모델 PC의 검수 서비스 사용자 세션에서 실행. 스크립트는 저장소에서 모델 PC로 복사해 둔다.
python3 ~/rosy-ml/bin/install_review_release.py <release-id> \
  --source /tmp/rosy-review-code-<release-id> \
  --state ~/rosy-ml/review-v13-drivable/state \
  --python ~/rosy-ml/.venv/bin/python \
  --host <model-pc-private-ip> --port 8774

# 이전 릴리스로 명시적으로 되돌릴 때 (재복사·DB 변경 없음)
python3 ~/rosy-ml/bin/install_review_release.py <previous-release-id> \
  --host <model-pc-private-ip> --port 8774
```

설치기는 소스의 필수 파일, DB 분리, 복사본 해시, Python import를 확인한 뒤 링크와 서비스 유닛을 전환한다. `/api/workspace`와 `/pixels`가 응답하지 않으면 이전 링크와 서비스 유닛으로 되돌리고 오류를 반환한다. 첫 전환 전의 서비스 유닛은 `~/rosy-ml/review-v13-code/rosy-review-v13.service.before-managed`에 남긴다. `REVIEW_RELEASE.json`의 해시는 릴리스 입력 파일 묶음의 내용 해시이며 Git 커밋이나 학습 모델의 승인을 뜻하지 않는다. 릴리스와 검수 DB를 함께 지우거나, 이 절차 밖에서 `current` 링크를 덮어쓰지 않는다.
