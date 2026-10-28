# 기존 Pinky 녹화의 공통 Episode

D-704: 원본 Twist의 여섯 축이 모두 유한한 숫자여야 하며, 평면 자료에 포함하지 않는 linear.y/z·angular.x/y는 0이어야 한다. 다른 축의 움직임·NaN·Infinity를 버리거나 null/0으로 보간하지 않고 원본 검증을 거절한다. 최종 속도 기록만으로 모델의 불필요 개입이나 전체 수집 범위·재발 0건을 입증하지 않는다.

닫힌 `rosy.recording.session/1` 원본 폴더와 `bag_to_video.py`의
`rosy.teleop.video/1` metadata·영상·JSONL·선언된 scan 파일을 입력으로 받는다.

```powershell
python learning/curation/pinky/pinky_episode.py <raw-session> <video.json> <new-output-on-X> --environment real --clock-domain ros_system
python learning/registry/policy/dataset_store.py --root <registry-on-X>/datasets <output>
```

environment/clock은 입력 provenance의 선언이며 물리 장치 인증이 아니다.
출력은 `source/raw/`, `source/video/`, `source/binding.json`, `episode.json`,
`dataset-manifest.json`이다. 새 디렉터리에 원본을 복사하고 해시를 검사한다.
원본·기존 출력은 덮어쓰지 않는다. 파일·원장의 위치는 X 드라이브다.

카메라 header stamp와 bag log time을 보존한다. cmd_vel의 linear/ angular는
CORE 최종 출력 기록(m/s·rad/s)이며 프레임 시각 이전 lookback을 검사한다.
dt는 원본 변환기가 소수 4자리로 반올림해 최대 50 us 모호성이 남는다.
stamped 관측은 1 us capture stamp, capture 이후 및 log time +0.5 s 규칙을 검사한다.

task는 녹화 reason(수집 목적), events stream은 원본 session lifecycle metadata다.
Action/Attempt/Fleet ID와 task/action outcome은 추론하지 않는다. task_id는 원본에만
보존한다. policy/calibration은 null, camera/model은 원본 null 또는 revision을 유지한다.

`verify_raw.py`는 ROS 2 CDR/MCAP의 camera·cmd_vel·odom·JSON 관측·scan을
sidecar 및 NPZ에 대조한다. 단일 namespace·표준 schema·CRC·원본 시각을 검사하며
검증 전후 Episode의 모든 파일이 DatasetManifest에 같은 해시/크기로 선언되어야 한다.
영상은 전체 decode의 프레임 수와 크기를 검사한다. 손실 압축 pixel provenance,
expert 정답, 실제 움직임과 과제 성공은 여전히 확인되지 않았다.

```powershell
python -m pip install -r learning/curation/pinky/requirements-raw.txt
python -B learning/curation/pinky/verify_raw.py <immutable-dataset> --out <new-report-on-X>
python -B learning/curation/pinky/prepare_behavior.py <immutable-dataset> <new-input-directory-on-X>
```

행동 입력 준비는 검증기를 직접 실행한다. 기존 pass 보고서를 입력으로 받지 않는다.
출력의 `research_input_only`, `split=unassigned`와 holds를 유지한다. 기록된 CORE
최종 속도는 expert intent로 인증되지 않았으며 미래 목표로 바꾸지 않는다.
고정 행동 평가·camera profile·task acceptance가 확보되기 전 학습/승격 준비로
해석하지 않는다. 이 도구의 MCAP/numpy/OpenCV 의존성은 호스트용이며 계약 wheel에는 없다.
CORE cmd_vel에 대한 새로운 publisher나 로봇 접속 기능은 없다.

```powershell
$RosyScratch = if ($env:ROSY_SCRATCH) { $env:ROSY_SCRATCH } else { [System.IO.Path]::GetTempPath() }
python -B -m pytest learning/curation/pinky/test -q -p no:cacheprovider --basetemp $RosyScratch/pinky-episode-tests
```


## 실제 규칙 선택 export

D-701의 규칙 선택 원장을 모델 평가와 독립적으로 내보낸다:

```powershell
python learning/curation/pinky/fleet_rules.py <fleet-journal.sqlite3> <new-rule-json-on-X> --subject-id <robot-id> --case-id <case-id> --owner-id <owner> --config-sha256 <rule-config-hash> --policy-revision <policy> --start <epoch-start> --end <epoch-end>
```

정상 선택은 `--case-id`를 생략해 null로 유지한다. 최대 24시간·4,096행·전체 JSON과 줄바꿈 1MiB를 검증하고 기존 DB와 출력 파일을 덮어쓰지 않는다. `retained_selections_only`는 보존된 선택 기록만 뜻한다. 실행 성공·모델 호출 0건·정상 명령 0건·재발 0건은 별도 완전한 근거가 필요하다.

## Fleet 관측 이력의 학습 준비 원본

D-699의 기록 창 검증은 전체 원본 export와 별도로 수행한다:

```powershell
python learning/curation/pinky/fleet_observations.py <fleet-journal.sqlite3> <new-window-json-on-X> --window --robot-id <robot-id> --start <epoch-start> --end <epoch-end> --max-gap-s <accepted-capture-gap>
```

최대 24시간·4,096행 범위에서 양끝 capture 전체 roster와 같은 producer run의 sequence·수신 시계·capture monotonic 간격을 확인한다. 기존 DB를 생성하거나 수정하지 않고 WAL을 포함한 동일 SQLite 읽기 snapshot을 사용한다. 누락·재시작·legacy·불완전 roster·subject 부재·한도 초과는 HOLD다. 수신 시계 역행이 보존 이력 어느 곳에라도 있으면 epoch 선택이 모호하므로 보수적으로 HOLD한다. 원문 state·좌표·다른 로봇 ID는 결과에 복사하지 않고 행 ID와 내용 해시만 남긴다. 출력 파일은 새로 생성하며 덮어쓰지 않는다.

`capture_complete:true`는 보존된 append 기록의 범위 검증이며 센서 최신성·append 전 poll 성공·CORE 명령·모델 호출·재발의 완전한 기록을 뜻하지 않는다. 정상 명령·모델 호출·재발 건수는 확인 전 `null`, 정답·훈련·현장 수용은 미승인이다. `max-gap-s`는 호출자가 수용한 관측 주기로 명시하며 도구가 임의 기준을 정하지 않는다.

기존 CORE/Task journal의 Fleet 상태 관측을 검증 가능한 unlabeled 원본으로 내보낸다:

```powershell
python learning/curation/pinky/fleet_observations.py <fleet-journal.sqlite3> <new-output-on-X> --robot-id <robot-id>
```

`observations.jsonl`과 `manifest.json`을 신규 폴더에만 만들며 read-only SQLite transaction으로 일관된 보존 이력을 읽는다. 행/파일 해시를 내보낸 뒤 다시 검증하고 `verify(output)`은 변경된 센서값/행 수/해시를 거절한다. `train_eligible:false`, `labels:null`이며 이 원본은 common Episode나 정답 dataset이 아니다. 원본 state와 clock/source/age를 유지하므로 분석·재생·학습 특징 준비에 사용할 수 있다. 같은 수신 시각이나 Fleet 목표만으로 실제 action/정답을 추정하지 않는다.

고속 camera/scan/odom/CORE 최종 cmd_vel은 위의 기존 기기 recording과 raw verifier가 근거다. 학습으로 넘길 때 원본·기기/사건/attempt·시간 도메인·지도/모델 revision을 대조하고, 기존 Episode와 DatasetManifest/registry 및 독립 평가·승격 경로를 따른다. 보존 기간 밖 자료는 이 export에 없으며 물리 장치 인증/수용은 따로 확인한다. 중단된 export는 manifest가 없거나 검증에 실패하므로 입력으로 쓰지 않는다.
