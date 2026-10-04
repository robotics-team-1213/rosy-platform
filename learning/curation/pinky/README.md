# 기존 Pinky 녹화의 공통 Episode

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
python -B -m pytest learning/curation/pinky/test -q -p no:cacheprovider --basetemp X:/DevTemp/pinky-episode-tests
```
