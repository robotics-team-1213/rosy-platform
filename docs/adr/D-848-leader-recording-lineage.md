## D-848 봉인한 리더 녹화의 세션·사이클 계보

**Status:** Accepted for implementation (2026-10-23)

### Context

학습센터의 native 변환과 검수 분할은 Episode마다 `session_id`·`cycle_id`를 요구한다. 같은 세션이나 사이클이 학습과 평가에 함께 들어가지 않게 하는 장치다(D-833, `check_capture_groups`). 자동 교사 수집은 이 값을 원본 manifest에서 받는다. 반면 `lerobot-record` 리더 녹화(1팔 `omx_follower`, 2팔 `bi_omx_follower`)에는 이 값이 없다. 그래서 `bind_capture`가 리더 녹화의 계보를 받지 않았고, 센터 변환은 계보 없는 리더 녹화를 일부러 거부했다. 결과적으로 실물 리더 시연이 센터 학습에 들어갈 길이 없었다.

2026-10-23 사용자 결정: 봉인할 때 ID를 자동으로 부여한다.

### Decision

- 현장 PC의 `deploy/robot/omx/record_seal.py`는 안전 종료·녹화 모드·종료 코드 0인 세션만 봉인한다. 봉인 이름이 `session_id`이고, Episode `i`의 `cycle_id`는 `<이름>-ep<i 네 자리>`다. 녹화 하나가 세션 하나이고, Episode 하나가 독립 사이클 하나다.
- 리그 버전(`--rig-revision`)과 사용한 보정 파일(`--calibration`)은 운영자가 명시한다. 도구는 추정하지 않는다. 보정 파일은 수집 폴더의 `calibration/`에 복사하고, `calibration_revision`은 그 파일들의 경로·해시 목록의 SHA-256이다.
- 모델 PC의 `collection_pipeline.py prepare-native <수집 폴더>`는 봉인 manifest가 모든 파일을 정확히 덮는지 다시 해시한다. 보정 revision을 다시 계산하고, 폴더 이름이 봉인한 `session_id`와 같은지 확인한다. 이어서 실제 LeRobot reader로 검사하고, 기존 prepared intake 파일 5개를 쓴다. 모든 Episode 판정은 `unknown`/`exclude`로 시작한다.
- `bind_capture`는 `source_mode=leader_native`의 계보를 받는다. 이 계보는 `collection_manifest_sha256`을 가져야 하고 `teacher_sha256`을 가질 수 없다. 단위·리그·보정·dataset bytes·Episode 범위 검사는 자동 교사와 같다. 계보 없는 리더 녹화는 이전처럼 그룹 없이 남고 센터 변환에서 거부된다.

| 기존 결정 | 관계 |
|---|---|
| D-756 | 첫 실물 녹화는 LeRobot 0.4.4 native 리더 경로다. SIM rad 자료와 섞지 않는다. |
| D-770 | 수집은 현장 PC, 학습·평가는 모델 PC다. 전송은 기존 `omx_collection_transfer.py`가 해시로 검증한다. |
| D-833 | 세션·사이클 후손은 같은 분할에 둔다. 이 결정은 그 값을 리더 녹화에도 공급한다. |

### Consequences

녹화 하나의 Episode들은 모두 같은 세션이라 한 분할에만 들어간다. 학습과 평가를 나누려면 녹화를 둘 이상 해야 한다. 한 녹화 안의 Episode를 서로 독립 시연으로 세지 않는다는 보수적 선택이다. 보정 revision은 운영자가 지정한 파일의 봉인 시점 내용이다. 녹화 중 보정이 바뀌지 않았음을 독립적으로 입증하지는 않는다. 실물 녹화·사람 검수·학습 품질·장치 실행은 각각 별도로 수용한다.
