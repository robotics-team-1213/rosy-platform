# OMX Hub 원본 증거와 reader 왕복 검증

- 변경: OMX LeRobot export의 전체 원본·SIM 증거 선택을 요구하고 준비, 전송 직전,
  고정 commit 재다운로드 후에 원본과 모든 프레임을 reader로 다시 비교한다.
  긴 파일 목록은 명시적인 JSON 배열로 전달할 수 있다.
- 증거: source `61304150f8`, 외부 실행 기록
  `C:/DevTemp/learning-execution-20261023/hub-native-green-final/run.txt`.
  모델 PC의 LeRobot 0.4.4에서 **12 passed, 0 skipped**, `pip check` 정상.
  HF 전송만 fixture로 대체하며 실제 reader·SIM 증거·28개 RGB 프레임을 사용한다.
  원본 PNG 누락, Parquet 원본 시각 변경, 관절 이름 순서 변경은 거부한다.
  upstream datasets/torchvision 경고 805개는 통과와 별도로 남아 있다.
- 증거: 같은 source의 원격 일반 환경 `hub-green-final/run-1.txt`는
  **20 passed, 5 skipped**; `test/known_failures.py` **0 NEW**.
  선택적 LeRobot 의존성에 따른 skip은 위 전용 환경 검증으로 별도 확인했다.
- gate 변화: OMX receipt의 `reader_verified`는 실제 전체 reader 비교 후에만 true다.
  일반 dataset/model은 byte 검증만으로 이 필드를 true로 만들지 않는다.
  기존 private 저장소 제한, 명시적 선택, 경로·symlink 거부, commit 고정,
  hash 비교, 중단 후 동일 commit 재검증과 마지막 private 확인을 유지한다.

실제 Hugging Face 인증·저장소 생성·업로드는 이 검사에서 실행하지 않았다.
사용자가 제공한 namespace는 `robotteam`이며 저장소는 아직 없다.
fixture 왕복은 실제 HF 접근이나 계정 권한의 증거가 아니다.
독립 정책 평가·승격·실물 실행 수용도 별도로 남아 있다.

CE: 해당 없음. 이번 경계와 pinned reader 형식은 코드·거부 회귀 시험·실행 안내에
직접 남겼으며 별도 교훈 문서로 중복하지 않는다.
