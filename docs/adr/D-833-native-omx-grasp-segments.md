## D-833 원본 계보를 보존한 native OMX 파지 구간 검수와 학습

**Status:** Accepted for implementation (2026-10-21)

### Context

전체 Episode를 복제하거나 action만 변환하고 이미지를 재사용하면 파지 구간의 관측 대응과 독립 분할 근거가 깨진다. 기존 native inspection·capture/environment provenance는 원본 전체 Episode와 파일 bytes에 결속되어 있다. 짧은 파지 구간의 사람 결과를 전체 작업 성공으로 올려 쓰지 않는다.

### Decision

`native_segments.py`는 `rosy.omx-native-segments.v1` 문서에 원본 inspection의 canonical SHA-256, 원본 episode index/content hash/frame count/session/cycle, `[start_frame,end_frame)`와 사람의 대상·결과·개입·검수자·근거·분할을 기록한다. 성공을 직접 확인하고 개입이 없는 구간만 학습에 포함한다. 실패·미판정·개입은 제외로 보존한다. 원본 Episode/content/session/cycle의 후손은 같은 분할에 둔다.

OMX 화면은 등록된 원본 frame을 확인하고 구간을 표시한다. 기존 bounded JSON·token·origin·Account manage 권한을 적용한다. 검수는 원본 decisions.json을 변경하지 않고 review DB의 새 revision으로 추가한다. 프로젝트 계정에서는 검수자를 인증된 사용자로 기록한다. 구간 선택 JSON을 내려받아 모델 PC의 offline exporter에 전달한다.

Exporter는 기존 native reader로 원본을 재검증한다. 변환하지 않은 state/action과 대응 이미지·source clocks를 새 child Episode에 복사하고 frame index/timestamp를 index/fps로 다시 만든다. 각 구간은 별도 Episode이므로 ACT chunk가 구간을 넘지 않는다. 원본 report/capture/environment와 새 child frame 계보는 receipt에서 구분한다. 실제 reader의 수치·이미지 대응 확인 및 원본 bytes 불변을 확인한 뒤에만 split receipt를 쓴다. 기존 native ACT 경로는 구간 selection/child lineage/출력 hashes를 검증하고 train-only 통계를 유지한다. SIM rad와 native 단위는 섞지 않는다.

원본 환경 로그 coverage는 원본 parent Episode 범위다. 구간 coverage나 프레임별 환경 증거로 승격하지 않는다. 원본 outcome은 unknown이면 그대로 두며 구간 결과로 전체 Episode 성공을 추정하지 않는다.

Legacy `leader_native`의 원본 inspection에 session/cycle이 선언되지 않았으면 그 계보는 unknown으로 유지한다. 이 자료의 session 독립성은 보장하지 않는다. Production `scripted_teacher` intake의 byte-bound session/cycle 검증은 유지하며 선언된 그룹의 후손은 분할을 넘지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 learning curation/training 경로에서 offline 기능을 확장한다. 새 배포·device payload는 없다. |
| D-429 | 원본 단위·관절 순서·카메라·보정·source identity를 보존한다. |
| D-430 | 실행 권한·안전 owner를 바꾸지 않고 학습 자료 검수만 확장한다. |

### Consequences

사용자는 전체 시연에서 필요한 파지 구간만 학습할 수 있지만 구간 수를 독립 시연 수로 계산하지 않는다. 자동 구간 분할·증강·동작 변환·모델 승격·장치 실행은 범위 밖이다. 다른 카메라·장비·물체 위치의 호환과 데이터 절감은 별도 독립 평가가 필요하다. 원격 host tests, 실제 LeRobot reader readback, 학습, 실물·현장 수용은 각각 기록한다.

### 원본 프레임 화면 검증 — 2026-10-21

실제 Edge 실행에서 기존 `img-src 'self' data:` 정책이 OMX 미리보기의 `blob:` URL을 차단하는 결함을 확인했다. 프레임 응답은 기존 정책이 허용하는 data URL로 표시하며 보안 허용 출처를 늘리지 않는다. `test_mark_review_and_download_original_grasp_range`는 이미지 요소의 가시성에 더해 실제 `naturalWidth`를 검사한다. HTTP 200과 깨진 이미지 요소의 가시성만으로 원본 확인 성공을 선언하지 않는다. 검증 목표는 [화면 실행 계획](../plans/2026-10-21-omx-ui-walkthrough.md)에 기록한다.
