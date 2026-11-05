# Decision·VLA 후속 수용: 저장 통계 검증과 실자료 준비 상태

## 고정 소스와 검증 범위

기존 파이프라인 구현·회귀는 [이전 기록](../omx-smolvla-reviewed-cycle-2026-11-05/result.md)을 따른다. 이번 후속은 보류했던 정규화 통계 비교를 실제 SDK에서 검증하고, 실자료·미사용 사람 정답·물체 작업·실물 수용의 입력 상태를 조사했다.

통계 시험 소스 commit은 `cb9f4a77d3bd76265587d0241f94cc9afabb8a2a`다. main26752318cf를 통합한 소스는 `7883232cb56fffae24a3b0504a6c7366c2376ffd`이며, 이 병합 전후의 OMX 학습·수집·계약·integration·통계 시험 파일에 차이가 없음을 git diff로 확인했다. 최종 문서 변경과 착지·게시·배포의 실제 소스는 후속 실행 기록과 구분한다.

| 검증 | 실제 결과 |
|---|---|
| helper 계약 RED | helper가 없는50d4e6a32c에서 수집 오류1, NEW1을 먼저 확인 |
| 최초 helper GREEN | 65f396b47f에서9 passed/0 skipped, exit0/NEW0 |
| 최종 helper14개 + 실제 ACT6/12관절 | model PC의 현재 정본 CPU SDK,16 passed/0 skipped,37.21초, exit0/NEW0 |
| 실제 SmolVLA6/12관절 | AI PC의 기존 별도 SDK,2 passed/0 skipped,340.47초, exit0/NEW0 |

모든 pytest는 커밋 소스를 공식 remote runner로 실행했다. 두 SDK 모두 CUDA를 비활성화했고 타 세션의 GPU·모델·자료를 변경하지 않았다. ACT는 정본 export requirements9개 pin과 일치하는 CPU SDK, SmolVLA는 기존 LeRobot0.4.4/torch2.7.1+cu128/transformers4.57.6 SDK를 CPU로 사용했다. 환경을 서로 같은 것으로 표시하지 않는다.

각 정책/관절 조합은 실제 optimizer1회, 모델 이동, 원래 SmolVLA 기반 snapshot 숨기기, 빈 HF cache·오프라인 새 프로세스 재적재, 실제 bench loader 추론을 수행했다. 그 새 프로세스가 checkpoint에서 읽은 normalizer와 unnormalizer에 stats override를 넣지 않고 실제 학습 설정의 유효 train 통계와 직접 비교했다. 관절 열별 값과 train/eval/test 평균을 다르게 만들어 순서와 누출을 구분했다. `physical_task_success`는 null이다.

## 직접 비교에서 확인한 SDK 의미

처음 원본 `meta/stats.json` 전체를 비교하자 영상 평균과 일부 단일 값 shape가 달랐다. 실제 학습/재적재 오류라고 단정하지 않고 같은 설치 SDK의 `datasets/factory.py`, `configs/default.py`, trainer와 processor 소스를 대조했다.

- `DatasetConfig.use_imagenet_stats=True`가 기본이며 공식 dataset factory는 영상 mean/std만 고정 ImageNet 값으로 대체한다. 따라서 기대값은 raw JSON 자체가 아니라 저장된 `train-config.json`으로 같은 공식 factory가 산출한 **유효 train 통계**다. 기존 ACT/SmolVLA의 정규화 동작은 바꾸지 않았다.
- normalizer의 사용 feature 집합이 action·state·front image, unnormalizer는 action임을 별도 검사했다. 사용하지 않는 index/timestamp의 저장 shape를 정책 검증으로 혼동하지 않는다.
- 표본 수 count는 스칼라와 길이1 배열로 저장될 수 있다. 값은 정확히 같아야 하며 여러 값·변조는 거절한다. 실제 정규화 vector의 shape·열 순서·값 검사는 유지한다.
- 작은 회귀는 pre/post 각각의 held-out 누출, 관절 열 뒤집기, feature/stat 누락, shape 변경, nonfinite, count 변조를 거절한다. count만 다른 무력한 누출 fixture도 거절한다.

처음 ACT 확장 시 없던 외부 기반 snapshot 폴더를 이동하려던 fixture 오류와, 위 raw/effective 통계 차이로 실패한 시도는 이력으로 보존한다. 실패를 baseline에 추가하거나 제품 가드를 약화하지 않았다. 이전 리뷰의 통계 직접 비교 Minor는 이 네 실제 SDK 조합으로 검증 범위에서 해소했다.

## 실자료·현장 조사

운영 앱의 실제 `--omx-center-config`가 가리키는 center를 확인했다. 기본 설치 폴더의 빈 state와 혼동하지 않았다. DB는 WAL이 없었고 `mode=ro&immutable=1`, query_only로 조회했으며 조회 전후 DB hash가 같았다.

| 입력/조건 | 조사 시점의 관측 | 현재 판정 |
|---|---|---|
| 운영 OMX center | datasets/runs/inputs/native_reviews/learning_profiles 모두0, workspace binding1; 자료·run·업로드 폴더도 비어 있음 | 적격 실자료 학습 입력 없음 |
| 기존5개 검수 state의 학습 작업 연결 | learning_task_records/datasets 모두0 | 기존 인식 자료가 native 행동 시연의 사람 검수라는 뜻은 아님 |
| 준비된 실물 녹화 설정 | 목표 raw 데이터 디렉터리가 아직 존재하지 않음 | 준비 설정과 실제 녹화 완료를 구분 |
| Decision 미사용 사람 정답·검수된 calibration profile | 이번 조사에서 적격 bundle을 확보하지 못함; 별도 보관 경로/담당자를 요청함 | 미사용 정답 평가·품질 수용 미실행 |
| top 카메라 | 현재640×480 YUYV/30fps, USB2 480M. preview만 중지한70초 직접 V4L2 읽기에서0바이트, 이후 원래 preview 서비스를 active로 복구 | 센서 입력 미준비 |
| 저장된 photometric readiness | STOPPED, photometric_ready=false, motion_admitted=false, expires_ns0 | 이 저장 상태를 동작 승인으로 사용하지 않음 |

이 표는 확인한 운영 경로의 상태이며 모든 과거 원본의 부재를 주장하지 않는다. 별도 보관 자료는 봉인·실제 사람 검수·미사용 여부·독립 session·관절/단위·카메라·rig/보정/새 집게 지문을 확인한 뒤 채택한다. 검수자나 정답을 에이전트가 대신 만들지 않는다.

기존 upkeep의 최신 양팔 보고도 top 프레임 부재로 광량/지도 점검을 건너뛰었다. 그 운영 도구는 main에 포함되지 않은 과거 source를 참조하므로 현재 D-932 수용 근거로 승격하지 않았다. 이번에는 해당 도구를 실행하지 않고 보고만 읽었다. 표준 V4L2 진단은 다른 카메라 소비자가 없음을 확인한 뒤 top preview만 잠시 정지했으며 팔·직렬 버스·카메라 설정을 바꾸지 않았다.

## 남은 완료 조건과 다음 입력

- 실제 ACT/SmolVLA 비교: 봉인된 실제 시연과 사람 검수 revision, 독립 train/eval/test session, 동일 과제·사전 고정 학습 예산이 필요하다. 아직 실제 데이터 학습이나 품질 PASS는 없다.
- Decision: 미사용 사람 정답과 사전 검수된 calibration limits가 필요하다. 개발 사례 재생 PASS를 그 정답으로 재사용하지 않는다.
- 시뮬 물체 작업: 적격 고정 checkpoint와 독립 물체 judge로 기존20회 중18회 목표를 검증해야 한다. 타 세션의 진행 중인 v13 시뮬/GPU 작업은 보존했다. 이번 synthetic optimizer를 물체 성공으로 세지 않는다.
- 실물: 카메라 프레임을 복구하고 현재 main의 보정 절차로 형상·카메라·지도와 owner/정지/HOLD를 확인해야 한다. 팔 동작은 D-911의 동작별 현장 사람 확인을 유지한다. 검수/실물 수용 없이 모델을 승격하지 않는다.
- 착지·게시·배포: 이번 요청에서 승인된 범위이며 별도의 정본 FULL·독립 리뷰·PR CI·서명·실제 적재 검증으로 처리한다. 이 통계 시험만으로 완료 처리하지 않는다.

원본 로그·실행 원장·사람 입력 요청·후속 배포 결과는 작업 공간의 `Rosy/docs/workspace-records/2026-11-05/decision-vla-acceptance/`에 보존한다. 실제 host 주소·계정·녹화 경로는 공개 저장소에 넣지 않는다.

CE: 새 교훈 기록 — [비동기 도움말 표와 실제 착지를 구분](../../solutions/workflow-issues/land-async-help-is-a-stopped-snapshot-2026-11-05.md). 통계의 유효 설정과 scalar 처리 근거는 코드·회귀·이 README/검증 기록에 남겨 별도 중복 교훈을 만들지 않았다.
