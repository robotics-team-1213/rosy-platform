# Native ACT 모델 전송 후 SDK 재적재 검증

실행 source commit `3c67e4237ed442ab79b146b272bb7f6b209ff00e`에서 단일 팔 6관절과 양팔
12관절 모델의 fixture Hub 왕복 → 새 프로세스 공식 ACT 재적재 → 독립 eval을 통과했다.
실제 HF 서비스 전달이나 실물 양팔 실행의 증거는 아니다.

## 변경과 회귀

`native_cycle._evaluate`는 split/repo 검사를 유지한 뒤 기존 `_artifact_files`를 호출해
필수 모델·processor 파일과 링크를 SDK 로딩 전에 검사한다. 단독 `verify` 진입점도
학습 직후와 같은 완전성 검사를 받는다. 실행용 profile·관절 상한·owner 권한은 바꾸지 않았다.

- RED `5e3708bb70`: 원격 새 사례5개 모두 실패. 누락·링크를 거부하지 않고 SDK import에 도달했다.
- GREEN `0673a845e3`: 원격39 passed / 2 skipped, known_failures 신규0.
  skip2는 일반 시험 환경의 SDK 부재이며 아래 실제 실행과 구분한다.
- 독립 코드 검토: Important 없음. 계획은 두 독립 검토의 2회 검토 뒤 승인됐다.

## 실제 SDK 시험

고정 CPU 환경의 MODEL runner로 두 사례를 순차 실행했다. runner 설정은 각8CPU·6GiB·
20분이며 trainer/reload 각300초, 전송 후 verify300초, 누락 거부30초를 적용했다.
Python3.12.3에서 저장소 CPU 요구 패키지9개와 SciPy1.15.3·pytest8.3.5의 버전11개를
검사한 뒤 pytest를 시작했다. 버전 검사는 전이 의존성 전체의 파일 해시 증명을 뜻하지 않는다.

각 사례는 명시적 합성 출처·단위·보정과 서로 다른 session/cycle의2episodes×8frames,
32×32 HWC RGB에서 train3/eval3을 만들고 공식 ACT를 batch2로2steps 학습했다.
완전한 checkpoint를 fixture Hub의 immutable commit으로 왕복하고 다운로드 경로만
기존 `native_cycle.py verify`의 새 프로세스에 전달했다.

| 관측 | 단일 팔 | 양팔 |
|---|---|---|
| 실제 시험·회수 | 1 passed / 0 skipped, EXIT0 | 1 passed / 0 skipped, EXIT0 |
| pytest 소요 | 17.81초 | 15.98초 |
| 관절·eval 표본 | 6 / 3 | 12 / 3 |
| 모델 파일·바이트 | 7 / 45,261,168 | 7 / 45,265,279 |
| 전송 후 공식 ACT | 새 프로세스 재적재 true, 유한 MAE/기준 배열의 길이6 | 새 프로세스 재적재 true, 유한 MAE/기준 배열의 길이12 |
| processor 누락 | 별도 readback 복사본에서 명시적 거부, 성공 출력 없음 | 같은 거부·성공 출력 없음 |

회수 후 별도 stdlib 감사가 원본 모델·payload·readback의 전체 파일 목록/해시와 cycle
receipt를 대조했다. 원본 데이터·분할 파일·split receipt도 대조했다. native 단위는
몸 관절 정규화와 gripper0..100이며 SIM rad로 재해석하지 않았다.
전송 receipt의 `bytes_verified=True`, `reader_verified=False`는 유지한다. 모델 재적재는
이 별도 통합 시험의 증거다. 물리 task success는 null, 장치 실행·승격은 false다.

## 원자료와 재현

외부 자료 기준 경로는 `C:/DevTemp/learning-execution-20261023/`이다.
`run_native_model_readback_sdk.py --sha 3c67e4237e
--layout single|paired --log-dir <새 경로>`가 공식 MODEL runner를 호출한다.
wrapper의 별도 스크립트와 CLI 인자를 함께 보존한다. 회수된 `out/inner.sh`는 runner의
공통 외피이며 SDK 시험 명령 전체가 들어 있다고 해석하지 않는다.

- 단일 팔: `native-model-readback-sdk-single-locked/`.
- 양팔: `native-model-readback-sdk-paired-locked/`.
- 독립 감사: `audit_native_model_readback.py`와 `native-model-readback-audit.json`.
  감사 JSON SHA256 `1bf5ed5e72e665f3f6c07261a80cb2ae22b9c43b975865fe2dd71193e3156f42`.
- 최종 wrapper SHA256 `7780ac50b1e0cc83d3fd84acc3b69587d7a507f961cacdcd8546973e7ed093f8`.
- 두 환경 JSON SHA256 `ea96b3b0ac1f0e48cb0e4d7589c352632d39b96b39f05e5f586d811f995d6275`.
- 단일 팔 전송 후 평가 SHA256 `dbecd271e7a5b1af68661df21b22a1e603ccd78515d0f65dcb58f9228881301b`.
- 양팔 전송 후 평가 SHA256 `261bd1f7e630c510ad75c0addf3c1f4a059551d76b84fc3cf5f764d1a2f101c4`.

초기 `native-model-readback-sdk-single/`은 시험 PASS였지만 임시 NumPy2.4.6 설치로
고정 환경 수용에서 제외했다. 다음 `native-model-readback-sdk-single-pinned/`는
Pillow10.2.0 불일치로 pytest 전에 EXIT1이다. 두 자료를 지우거나 최종 PASS에 합산하지 않았다.
최종 실행은 NumPy2.2.6·Pillow12.3.0을 임시 prefix에 고정하고 불필요한 시스템 경로를 뺐다.

CE: 새 교훈 기록 — [SDK 임시 패키지 경로와 고정 버전](../../solutions/workflow-issues/isolated-sdk-overlay-bypasses-dependency-pins-2026-10-24.md).
고정 환경의 전송 후 재적재 연결만 수용한다. 실제 HF 인증·private repo 전달은 유예 중이고,
모델 품질·양팔 streaming 권한·실물 수용·기존 단일 팔 독립 SIM HOLD 해소는 남아 있다.
