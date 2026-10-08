## D-534 Pinky Pilot 녹화는 모델 PC가 정지 확인 후 자동 수신하고 검수 대기로 넘긴다

**Status:** Accepted (2026-10-09, 사용자 지시; SOURCE 계약·수신 타이머, 모델 PC 활성화와 실제 녹화 수신은 별도 확인).

### Context

Pinky의 Pilot 녹화는 `/var/lib/rosy/pilot-recordings`에 남는다(D-411). 기존 `rosy_ml fetch --http`는 CORE의 정지 판정 뒤 원본을 받고 manifest SHA-256을 확인해 MP4와 프레임·조작 사이드카를 만든다. `edge_capture_session.py`는 별도 수동 검수 초안 경로다. 모델 PC에서 주기 실행 중인 것은 코드 업데이트 타이머뿐이었으므로, 녹화를 마치면 모델 PC까지 자동으로 들어온다는 기대와 설치 상태가 달랐다. 모델 배포를 감시하는 D-373의 `rosy-model-watch`는 녹화 수집기가 아니다.

### Decision

1. **수집 권한과 시작점.** 모델 PC의 사용자 타이머가 등록된 Pinky별로 `fetch_http.py`를 실행한다. CORE `GET /api/v1/recordings`가 `download_allowed`를 반환한 종료 세션만 받는다. Operator 토큰 파일과 장치 CA는 모델 PC 로컬 비밀 설정이며 Git에 넣지 않는다. 토큰·CA·코드·저장 경로 중 하나라도 없으면 설치를 활성화하지 않고 실패를 기록한다. 현장 설정의 `SINCE_ID`로 첫 자동 수집 세션을 명시해 과거의 조작 짝 없는 녹화를 반복 실패시키지 않는다. 만료되는 페어링 토큰은 재발급과 마지막 성공 시각을 감시한다. SSH `sudo tar`로 정지 가드를 우회하지 않는다.
2. **불변 원본과 재시도.** 임시 파일로 받은 뒤 manifest의 크기와 SHA-256을 모두 확인하고 세션 ID 폴더로 확정한다. 중단·이동·401/403·해시 불일치는 미수신/실패로 남겨 다음 주기에 재시도한다. 이미 확정한 ID는 건너뛴다. 변환 실패 뒤 남은 원본은 다시 내려받지 않으므로 별도 재변환이 필요하다. 로봇 원본을 자동 삭제하거나 `harvested`로 표시하지 않는다. 수집 단계의 로그에는 세션 ID·종료 코드·시각을 남기고 토큰을 쓰지 않는다.
3. **검수·학습 경계.** MP4·사이드카에서 프레임과 조작 짝이 확인돼도 정답은 아니다. 검수 앱에 넣는 초안은 원본 manifest와 세션 ID를 참조해 별도 생성하고 사람에게 `pending`으로 보인다. 객체와 픽셀 승인은 각각의 클래스 계약에 따른다(D-485). 사람 승인·평가 세트 분리·학습 자격 확인 전에는 `v13-drivable` 학습 입력이나 모델 접수로 자동 승격하지 않는다(D-464, D-475, D-532). 주행 사용은 더 별도다.
4. **운용 증거.** 타이머 활성 상태, 마지막 실행 결과, Pinky의 종료 세션 ID, 모델 PC의 원본/영상/사이드카와 해시 검증을 대조한다. 실제 녹화에서 변환 및 짝 검사 결과와 검수 대기 반입 여부를 각각 보고한다. SOURCE 테스트나 시뮬레이션만으로 설치·실물 수신을 주장하지 않는다.
5. **반복 개선.** 수신한 실물 녹화에 고정 revision 모델을 오프라인 적용하고, 프레임 시각·로봇 pose·지도/차로 구간과 Rosy Cam·Fleet 위치 기록을 같은 시간축에서 대조한다. 이 위치 기록은 주행 궤적의 독립 관측이며 픽셀 경계의 정답은 아니다. 모델 간 불일치, 경계 위반, 과노출, 인식 불확실 장면을 우선 검수 큐로 보낸다. 사람이 확정한 객체/픽셀 정답만 다음 데이터 버전에 포함한다. 새 후보는 기존 고정 평가 세트와 별도 실물 녹화 재생, 시뮬레이션, shadow 판정을 통과해야 하며, 반복 자체가 자동 주행 허가를 주지 않는다.

### Consequences

기존 D-411 수신기를 재사용해 수집을 자동화한다. 2026-10-09 모델 PC에서 새 Pilot 녹화 두 건의 정지 가드·수신·변환·조작 짝을 확인했고, 사용자 선택에 따라 Operator 페어링을 마쳤다. 타이머의 지속 성공, Rosy Cam/Fleet pose 연계, 검수 초안·학습은 각각 별도 증거다. 이 결정은 로봇 주행·녹화 시작, 자동 승인·학습·배포 권한을 추가하지 않는다.

**Related:** [D-136](D-136-.md), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md), [D-411](D-411-pilot-robot-recording-control-descriptor-and-gripper.md), [D-434](D-434-model-pc-and-site-pc-roles.md), [D-464](D-464-pinky-indexed-review-dataset-build.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-485](D-485-review-app-class-sets.md), [D-532](D-532-v13-drivable-model-lineage.md).
