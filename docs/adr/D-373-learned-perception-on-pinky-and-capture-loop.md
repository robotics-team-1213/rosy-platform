## D-373 학습 인식 두 번째 바퀴 — Pinky 이미지 탑재, 불일치 캡처, 섀도 자동 반영

**Status:** Proposed (2026-09-30). 잇는 결정:

- [D-356](D-356-perception-learning-loop-and-model-delivery.md)(Proposed): 학습은 저장소 밖이다. manifest 약속, 접수, 데이터 세대 전달, 섀도 전용 추론은 저장소 안이다.
- D-225: 변경은 세 계층이다. 이미지(재굽기), 부트·호스트(유닛), 페이로드(`install/`, 서명 전환).
- D-189·D-192: pip 런타임과 `/var/lib/rosy` 배치. 유닛마다 `StateDirectory=rosy/<unit>`을 쓴다.
- D-136·D-152: 원본 영상은 로봇 안에만 둔다. 고화질 원본은 로봇 안 60 s 링버퍼에만 두고, 주행하지 않을 때만 올린다.
- D-185: 최신 값만 의미 있는 구독은 KEEP_LAST 1. 실행기는 `executor_choice`로 고른다.
- D-62: 꺼진 기능은 조용히 무시하지 않고 꺼졌다고 말한다.
- D-205: 학습 모델의 주행 선택은 P3 재생 게이트 뒤다. 이 결정은 그 선을 넘지 않는다.

**Context:**

1. D-356 첫 바퀴는 모델 계약, 접수, 전달 도구, 섀도 노드, 녹화 CLI를 만들었다. 그러나 장치 이미지에 onnxruntime이 없다. `/var/lib/rosy/models`를 만드는 곳도 없다. 전달 도구는 존재하지 않는 SSH 사용자(`pinky`)와 sudo 없는 쓰기를 가정했다.
2. 장치 제품 런타임은 systemd다. 카메라 노드는 `rosy-camera.service`(`User=rosy-camera`, `ProtectSystem=strict`)가 `camera_preview.launch.py`로 띄운다. D-356의 노드는 어느 유닛에도 연결되지 않았다.
3. 앞 카메라는 원본 `Image`만 낸다. 원본을 계속 녹화하면 D-136 영상 예산을 어기고, 4 GiB 할당량이 30여 분이면 찬다.
4. 학습에 필요한 것은 모든 주행이 아니다. 규칙 기반과 학습 모델이 어긋난 장면이다. 지금은 그 장면을 골라 남길 수단이 없다.
5. 새 모델을 로봇에 반영하려면 사람이 intake와 deliver를 차례로 쳐야 한다.

**Decision:**

1. **이미지 계층(SD 재굽기)에 학습 인식 런타임을 넣는다.**
   - `onnxruntime`을 `device-python-requirements.txt`에 해시 고정으로 넣는다(cp312, aarch64와 x86_64). `inputs.lock.yaml`의 `requirements_sha256`을 같은 커밋에서 바꾼다.
   - `/var/lib/rosy/models`는 `root:rosy-camera 0750`이다. 카메라 유닛은 읽기만 한다. 쓰기는 운영자 전달(`rosy` + `sudo -n`)만 한다. `customize-rootfs.sh`와 `tmpfiles-rosy-state.conf` 두 곳에서 같은 규칙으로 만든다.
   - 녹화는 카메라 유닛의 `StateDirectory` 아래 `/var/lib/rosy/camera/recordings`에 둔다. 새 쓰기 경로를 열지 않는다.
   - 재굽기 전 벤치 장치에는 같은 해시 파일과 같은 디렉터리 규칙을 적용하는 스크립트 하나로 설치하고, 설치를 기록한다.
2. **페이로드 계층에서 섀도 노드와 캡처를 켠다.** `camera_preview.launch.py`에 `learned_shadow`와 `capture` 인자를 둔다. 기본값은 둘 다 꺼짐이다. 켜졌는데 런타임이나 모델이 없으면 노드는 `perception/learned/status`에 이유를 1 Hz로 알린다(D-62). 주행 경로는 여전히 이 결과를 읽지 않는다.
3. **앞 카메라 압축 토픽은 캡처용이다.** `camera_detect_node`가 이미 가진 프레임을 JPEG으로 `camera/front/compressed`에 낸다. 기본 꺼짐이고 `capture`가 켤 때만 낸다. 로봇 밖으로 나가지 않는다(D-136). 녹화는 원본 대신 이 토픽을 기록한다.
4. **캡처는 불일치 스냅샷이다.**
   - rosbag2 snapshot 모드로 최근 60 s를 메모리 링버퍼에 둔다(D-136).
   - 트리거 조건: 섀도와 규칙 기반의 차선 오차 차이가 임계값을 연속 N프레임 넘을 때, 또는 한쪽만 차선을 볼 때. 운영자 요청도 트리거다. 재트리거에는 쿨다운이 있다.
   - 스냅샷 하나가 세션 하나이고, `session.json`에 트리거 사유와 두 판단값을 남긴다.
   - 할당량 규칙은 D-356을 따른다. 수거 전 세션은 지우지 않는다.
   - 수거는 로봇이 주행 중이 아닐 때만 한다.
5. **사이트 PC가 새 모델을 섀도까지 자동 반영한다.**
   - `rosy-model-watch` 타이머가 HF model 저장소의 새 commit을 본다. 새 commit이 있으면 intake를 돌리고, 통과하면 설정된 로봇에 섀도로 전달한다.
   - 상태 파일로 같은 commit을 두 번 처리하지 않는다.
   - HF 토큰은 사이트 비밀 파일로만 읽는다.
   - **자동 반영의 끝은 섀도다.** 주행 활성화는 자동화하지 않는다.
6. **전달 도구는 실제 장치 규칙을 따른다.** SSH 사용자 `rosy`, 운영자 키와 known_hosts(BatchMode)를 쓴다. 모든 쓰기는 `sudo -n install`로 소유권과 권한을 정해서 한다. 로봇 주소는 저장소에 쓰지 않는다.

**Consequences:** 섀도 결과와 불일치 스냅샷이 쌓이면 D-356 데이터셋 도구의 입력이 되고, 나중에 D-205 P3 재생 게이트의 재료가 된다. onnxruntime과 디렉터리 규칙은 다음 이미지 릴리스부터 SD에 들어간다. 그 전의 벤치 장치는 기록된 수동 설치다. Pi 5에서의 지연과 CPU는 첫 장치 실측 전까지 모른다. 지연 예산(8 fps의 한 주기 125 ms)을 넘으면 노드는 프레임을 건너뛰고, 그 비율을 `status`에 낸다.

**Validation:**

- 호스트 pytest: 트리거 정책, 전달 스크립트, watcher 상태.
- WSL ROS 실행 증거: 섀도, 스냅샷, 수거.
- 이미지 계약 시험: 해시 고정, 디렉터리 규칙.
- 장치: 벤치 설치, 지연·CPU 실측, 섀도 배포, 첫 스냅샷 수거. 장치 합격은 이 목록을 실물에서 확인한 뒤다.
