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

MCAP 메시지와 변환 sidecar의 실제 대조, 영상 pixel 및 scan NPZ 내용은 아직
검증하지 않는다. SHA·메타데이터·sidecar 시계/명령 검사를 변환 진위, expert 정답,
정책 학습/과제 성공 또는 runtime activation 수용으로 해석하지 않는다.
CORE cmd_vel에 대한 새로운 publisher나 로봇 접속 기능은 없다.

```powershell
python -B -m pytest learning/curation/pinky/test -q -p no:cacheprovider --basetemp X:/DevTemp/pinky-episode-tests
```
