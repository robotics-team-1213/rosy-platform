# Pinky 녹화의 공통 Episode 연결

기준 `573e2a024`. D-449가 정한 Pinky Episode에 실제 기존 녹화를 연결한다.
원본 `rosy.recording.session/1`과 MCAP, `rosy.teleop.video/1` 및 sidecar를 함께 보존한다.
새 원본·관측·명령·판정 결과를 만들어 내지 않는다.

1. 공통 stdlib profile에서 닫힌 세션, identity, 영상/sidecar 수, capture/log 시계,
   finite m/s·rad/s 최종 명령과 lookback dt를 검사한다. 원본·변환 session 메타데이터는 일치해야 한다.
2. curation 변환기는 별도 출력에 파일을 복사·재검증하고 Episode/DatasetManifest를 만든다.
   sim/real과 clock_domain은 입력 provenance에 명시한다. 역사적 null revision은 유지한다.
3. task는 녹화 reason(수집 목적)이며 task_id를 Fleet/Action ID로 바꾸지 않는다.
   outcome은 task/action 모두 unknown, judge unknown이다. cmd_vel은 CORE 최종 명령의
   기록이며 새 정책 후보, 원인 행동, expert 정답 또는 실제 이동 성공 판정이 아니다.
4. DatasetStore profile dispatch에 추가하고 downgrade/원본 불일치/미래 명령/위조 dt를 시험한다.
5. 고정 평가 세션을 제외한 기존 실제 녹화를 변환·등록·독립 재독출한다.

이 단계는 원본 파일 해시와 sidecar 의미 검증이다. MCAP 메시지와 sidecar를 다시
대조하는 변환 진위 검증, 영상 pixel/scan NPZ 내용 검증, 행동 정책 학습/독립 과제
평가·owner 실행·Fleet 결과 join은 후속이다. 이 검증만으로 해당 수용을 주장하지 않는다.
Pinky는 이미 완료된 실제 녹화를 읽기만 하며 새로운 로봇 연결·motion은 수행하지 않는다.
