# OMX 구간 내보내기 공개 기준 검증

공개 기준 commit `0e23802dac7f` 위에 구간 내보내기와 ACT receipt 소비 부분만 분리했다. 공유 로컬 main의 다른 미게시 작업은 포함하지 않는다. 소스 검증 commit은 `e7ba4f29eb17`이다. 화면·HTTP 연결은 후속 변경이며 이 기록으로 게시·실물 실행 완료를 주장하지 않는다.

## 범위와 계약

`native_segments.py`와 테스트는 로컬에서 검증한 구현을 그대로 분리했다. `native_cycle.validate_split`은 segment receipt만 새 검증기로 분기하고 기존 전체 Episode receipt, capture binding, 환경 coverage, 출력 hash 검증은 유지한다. D-833과 모듈 안내를 함께 기록했다. 기존 native/SIM 구현·장치 실행·정책 승격은 변경하지 않는다.

## 실행 증거

- 공식 원격 실행: `python tools/remote/remote_pytest.py --log-dir <scratch>/native-focused -- learning/curation/omx/test/test_native_segments.py learning/training/omx/test/test_native_cycle.py`. SHA `e7ba4f29eb`, 시험 PC에서 44 passed/1 skipped, NEW/known/flaky 0. 생략된 1개는 기본 환경에 LeRobot이 없어 importorskip한 실제 파일 검사다. baseline의 listed-but-not-failing 5개는 수정하거나 실패 수용에 사용하지 않았다.
- 실제 파일 실행: 같은 커밋에서 추출한 5개 runtime 파일을 별도 scratch로 보내 기존 `lerobot==0.4.4` 환경에서 `export_segments`와 실제 `native_cycle.validate_split`을 실행했다. SYNTHETIC 표식이 있는 genuine LeRobot 원본 36프레임과 에이전트 테스트용 선택 JSON을 사용했으며 실제 사람 성공 정답이나 실물 녹화가 아니다.
- 실제 결과: train 4·eval 4·test 2프레임을 새 폴더에 내보냈다. 별도 원본 session/cycle과 원본 구간 `[2,6)`, `[2,6)`, `[7,9)`를 유지한다. selection/receipt 일치, 실제 child reader의 state/action/source clock 배열 정확 일치, 2^53보다 큰 int64 clock 값, 대응 이미지 평균 채널 오차 8/255 이하, 원본 전체 파일 hash 불변을 확인했다. exit 0, `proof.json`의 revision은 위 SHA와 같다.
- 독립 검토: 다른 읽기 전용 에이전트가 공개 base/head의 실제 producer/consumer와 의존 함수를 확인해 중요 지적 없음으로 보고했다. 검토자는 시험을 별도 실행하지 않았다.

로그·소스 추출·실제 파일 proof는 외부 `rosy-omx-publish-20261021` 작업 폴더에 보존한다. 고정 환경의 실제 파일 검증은 기본 시험의 skip을 숨기거나 pytest 실행으로 바꿔 보고하지 않는다. 실물 파지·학습 모델 품질·데이터 절감 효과는 검증하지 않았다. 최종 게시 SHA의 pre-push와 GitHub CI는 PR에 별도로 기록한다.
