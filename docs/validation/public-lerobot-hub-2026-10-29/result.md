# 공개 LeRobot 시연의 학습·게시·재로딩 검증

2026-10-29. 실제 자체 녹화가 없다는 사용자 응답에 따라 라이선스가 확인된 공개 SO100
시연으로 제한된 오프라인 과제를 완주했다. 운영 배포·실물 성공·LeRobot 전체 기능 대체의
수용 기록은 아니다. 계정·원격 주소·비공개 저장소 이름은 이 공개 기록에 넣지 않는다.

## 구현과 실행 소스

- 새 `public_train` 경로의 기본 구현: `cc4712f8a1`, 성공한 출처 조회 캐시: `663ccdfc89`.
- 공통 UI·CSP 준수: `730bac48cb`; 완료 단계 문구와 회귀: `f3a32e7e5f`.
- 실제 실행 서비스와 worker 소스: `663ccdfc89`. 완료 모델 다운로드 브라우저 소스: `63ecbc2ff6`.
- 실행 ID: `6b690e08-64f9-4049-95ca-298850f4ba23`.
- source·train·eval 및 웹 권한/소유 프로세스 경로의 독립 읽기 전용 검토에서 중요 발견 없음.
  별도 게시 스크립트 검토도 수행했다. 읽기 검토를 실행 증거로 계산하지 않는다.

공개 자료는 고정 revision·Apache-2.0·실제 metadata·허용 파일 경로·총 크기·파일 해시를
익명으로 검사한다. 공개 SO100 자료를 OMX 시연으로 이름 바꾸거나 native 보정·검수 검증을
우회하지 않는다. 실행은 기존 Center의 단일 소유 프로세스·중지·재시도·재시작을 공유한다.
웹 POST는 기존 manage·CSRF 검사를 유지하며 CLI의 HF 자격을 암묵적으로 사용하지 않는다.

## 실제 자료와 학습

출처는 [lerobot/svla_so100_pickplace의 고정 revision](https://huggingface.co/datasets/lerobot/svla_so100_pickplace/tree/728583b5eaf9e739a7f119e2def466fa1d552402)이다.
카드의 오래된 v2.1 문구 대신 고정 파일의 실제 LeRobot v3.0 metadata를 기준으로 읽었다.
원본은 SO100, 50에피소드·19,631프레임·30fps다. 처음 10개 완전한 에피소드의 3,977프레임을
선택하고 원래 6관절 이름·state/action 값을 보존했다. 두 RGB 카메라만 bilinear 128×128 PNG로
변환했다. 파생본 전체를 공식 reader로 다시 읽고 관절 배열 일치와 이미지 크기를 확인했다.

학습 0..7, 검증 8, 평가 9로 분리했다. 정규화는 별도 학습 8에피소드 파생본에서만 맞췄다.
고정 LeRobot 0.4.4 CPU 환경에서 ACT를 처음부터 1,000단계, batch 4, seed 42750으로 학습했다.
설정은 기존 작은 ACT CPU recipe(ResNet18, pretrained backbone 없음, VAE 없음, chunk 4)를 쓴다.
의존성 설치나 pinned 환경 변경은 하지 않았다.

별도 프로세스에서 공식 ACT와 전후처리기를 다시 읽어 각 보류 에피소드의 앞 128개 연속
프레임을 비교했다. 아래 값은 6관절 MAE의 단순 평균이며 단위는 `dataset-native/unverified`다.

| 자료 | 프레임 수 | 모델 MAE | 학습 평균 행동 기준 MAE |
|---|---:|---:|---:|
| 검증 에피소드 8 | 128 | 3.01099316 | 13.64868244 |
| 평가 에피소드 9 | 128 | 2.74128029 | 14.78824981 |

평가 wrist-roll 관절은 모델 MAE 3.28179264 / 기준 0.94028205로 기준보다 나빴다.
평균 개선을 모든 관절의 개선이나 과제 성공률로 해석하지 않는다. episode만 분리했으며 수집 세션
독립성·물리 단위·실물 성능은 미확인이다. 평가값으로 학습 recipe를 재선택하지 않았다.

## 실제 화면과 게시본

공식 원격 Chromium이 API mocking 없이 출처 확인을 체크하고 시작 버튼으로 실제 학습을 접수했다.
완료 뒤 같은 화면의 모델 링크를 눌러 ZIP을 내려받고 `result.json`의 모든 모델 SHA-256을 대조했다.
`artifact_verified=true`, 재로딩 true, `physical_learning_verified=false`를 확인했다.

사용자가 요청한 HF 반영은 기존 로그인으로 운영자가 실행했다. 새 dataset/model 저장소 각각을
`private=True`, `exist_ok=False`로 만들었으며 기존 자료를 덮어쓰지 않았다. 게시 사본에서는
절대 host 경로를 담은 선택형 `train_config.json`과 임시 images 파일을 제외했다. PNG는 Parquet에
내장되어 있고 원래 data/meta와 가중치·전후처리 상태의 해시는 그대로다. 경로를 placeholder로 바꾼
별도 recipe, 출처·분할·평가·게시 파일 manifest와 라이선스를 포함했다.

- 전송 사본 SHA-256: `c9551e26374c9d3338c47f94c1c441a13965ae0a60fb46d2b7c2cae0a57ab019`.
- 게시 dataset commit: `fc0d2f0bb5debc7142f4e2bad3356b945ca995ca`.
- 게시 model commit: `3b0730bf29226f058afac07ee47934afd758203d`.

각 고정 commit을 다시 내려받아 게시 파일 해시를 모두 비교했다. 그 snapshot에서 공식 reader로
10에피소드·3,977프레임을 읽고 ACT와 전후처리기를 같은 모델 snapshot에서 재로딩했다.
검증·평가 각 128프레임의 MAE와 예측 표본이 원래 결과와 rtol/atol 1e-5 이내로 일치했다.
모델 게시 API 성공만으로 완료 판정하지 않았다.

## 원격 회귀와 한계

| 범위 | 커밋 | 결과 |
|---|---|---|
| public/native 학습·HTTP 4파일 | `cc4712f8a1` | 종료0 / 1 numerical opt-in skip / NEW0 |
| 공개 화면·공통 UI 계약 6파일 | `730bac48cb` | 107 passed / skip0 / NEW0 |
| 영향 선택의 mapped suites + guards | `730bac48cb` | 3,515 passed / 376 skipped / NEW0 |
| 실제 브라우저 시작 | `2de47ca44f` | 1 passed / skip0 / NEW0 |
| 실제 완료 모델 다운로드 | `63ecbc2ff6` | 1 passed / skip0 / NEW0 |
| 완료 문구 포함 공개 화면 Chromium 전체 | `f3a32e7e5f` | 9 passed / skip0 / NEW0 |

각 원격 로그를 `test/known_failures.py`로 분류했다. 초기 UI 4실패+teardown 오류는 공통 checkbox/button
표기, disabled 설명이 붙은 버튼 locator, CSP에 막힌 문자열 평가 대기를 고친 뒤 재실행했다.
체크나 허용 목록을 약화하지 않았다. 잘못된 screenshot 경로의 이전 호출은 자신의 job만 취소했다.

영향 선택은 `test/browser_scope.py`와 새 평가 모듈의 매핑 때문에 FULL로 상승했다. 위 3,515건은
공식 runner의 mapped 선택이며 GitHub FULL CI를 대신하지 않는다. 착지·push를 요청하지 않아
FULL CI나 운영 배포는 실행하지 않았다. 376 skip은 통과로 계산하지 않는다.

한 번 `affected --run`이 로컬 pytest를 시작한 명령 선택 실수는 즉시 자신의 프로세스만 중단했다.
그 결과는 폐기했고 selection JSON을 공식 원격 실행기에 넘긴 결과만 위 표에 썼다.
새 미리보기 SSH 터널 생성은 자동 승인 검토가 사유 없이 `blocked by policy`로 거절해 우회하지 않았다.
원격 브라우저와 실제 화면 캡처로 검증했다. 실물 녹화·로봇 동작·승격·정책 적용은 수행하지 않았다.

CE: 해당 없음. 기존 pinned learner venv 교훈을 적용했고 새 출처·권한·재로딩 경계는 코드·회귀·이 기록에
보존했다. 비공개 대상·원본 영수증·운영자 스크립트 위치는 Git 밖 작업 기록에 남겼다.
