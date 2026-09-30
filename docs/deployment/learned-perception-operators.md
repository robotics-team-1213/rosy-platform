# 학습 인식 모델 운영자 안내 (D-373)

팀에 새로 들어온 운영자를 위한 문서다. 학습한 차선 인식 모델을 로봇의 **섀도 슬롯**에
넣고 빼는 일, 로봇에서 녹화를 가져오는 일을 다룬다. 섀도 모델은 주행에 쓰이지 않는다.
주행 선택은 D-205 P3 게이트 뒤의 별도 결정이다.

명령은 `rosy_ml` 하나다(`tools/perception/rosy_ml.py`). 아래 예시는 저장소 루트에서
`python tools/perception/rosy_ml.py ...`로 실행하고, 편의상 `rosy_ml`로 줄여 쓴다.
로봇은 이름(`pinky-005`)으로 부른다. 주소는 각자의 설정 파일에만 있고 저장소에는 없다.

## 처음 한 번

1. **내 SSH 키를 만든다.** 사람마다 자기 키를 쓴다. 남의 키를 복사하지 않는다.

   ```bash
   ssh-keygen -t ed25519 -C "<내 이름>@rosy"
   ```

   Windows 운영자 PC의 기본 위치는 `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519`,
   known_hosts는 `%LOCALAPPDATA%\Rosy\known_hosts`다.

2. **로봇마다 내 공개키를 `rosy` 계정의 `authorized_keys`에 넣어 달라고 한다.**
   이미 접속 권한이 있는 관리자가 기존 장치 접속 절차
   ([`.claude/skills/rosy-device-access/SKILL.md`](../../.claude/skills/rosy-device-access/SKILL.md))
   로 로봇에 들어가 `~rosy/.ssh/authorized_keys`에 `.pub` 한 줄을 추가한다.
   비밀번호 SSH와 `pinky` 계정은 쓰지 않는다.

3. **로봇 호스트 키를 known_hosts에 한 번 기록한다.** 믿을 수 있는 네트워크에서 첫 접속으로
   기록한다. 이후에는 `StrictHostKeyChecking=yes`라서 키가 바뀌면 접속이 거부된다.
   SD를 다시 구운 로봇이면 관리자와 확인한 뒤 `ssh-keygen -R <robot-ip> -f <known_hosts>`로
   지우고 다시 기록한다. 검사를 끄지 않는다.

4. **설정 파일을 만든다.** 비밀값은 설정에 넣지 않는다. 토큰은 *파일 경로*만 적는다.

   ```bash
   rosy_ml init --robot pinky-005=<robot-ip> --robot pinky-007=<robot-ip> \
     --hf-repo <hf-org>/<model-repo> --hf-token-file <내 HF 토큰 파일> \
     --core-token-file <CORE viewer 토큰 파일>
   ```

   - 위치: `ROSY_ML_CONFIG`가 있으면 그 경로, 없으면 Windows `%APPDATA%\Rosy\ml.yaml`,
     Linux `~/.config/rosy/ml.yaml`.
   - `operator`는 기본이 OS 사용자 이름이다. 로봇의 `history.jsonl`에 이 이름이 남는다.
   - 이미 있으면 덮어쓰지 않는다. 바꾸려면 파일을 직접 고치거나 `--force`.
   - Linux에서는 `--identity`, `--known-hosts`를 직접 주거나
     `ROSY_OPERATOR_KEY`, `ROSY_KNOWN_HOSTS`를 설정한다.

5. **점검한다.**

   ```bash
   rosy_ml doctor            # 모든 로봇
   rosy_ml doctor pinky-005  # 한 대만
   ```

   줄마다 `✓`(통과), `✗`(필수 실패), `!`(권고)가 나온다. `✗`마다 `fix:` 뒤에 할 일이 적혀
   있다. 모든 필수 항목이 통과해야 종료 코드가 0이다. 아래 "문제가 생기면" 표를 본다.

## 매일 쓰는 명령

```bash
rosy_ml status                              # 모든 로봇: 섀도 포인터, 설치된 revision, 최근 기록
rosy_ml status pinky-005 --history 20       # 한 대, 기록 20줄
rosy_ml intake hf:<hf-org>/<model-repo>@<40자리 commit>   # 모델 검사 (통과 시 data/perception/models)
rosy_ml deliver pinky-005 <model_revision>  # 섀도에 넣기 (intake 통과본만)
rosy_ml rollback pinky-005                  # 바로 전 섀도로 되돌리기
rosy_ml release-hold pinky-005              # 되돌린 revision을 자동 반영이 다시 넣어도 되게 풀기
rosy_ml harvest pinky-005                   # 끝난 녹화 세션 가져오기
```

- `deliver`는 intake 보고서가 `pass`이고 파일 해시가 manifest와 같을 때만 보낸다.
- `harvest`는 로봇이 **서 있을 때만** 가져온다(D-136). 로봇 CORE의 `/api/v1/robot/state`를
  보고 모드 IDLE, 주행 없음, line follow OFF, 속도 0, 그리고 속도 값이 **최신(fresh)** 일
  때만 idle로 본다. 오도메트리가 끊겨 속도 값이 오래되었으면 idle이 아니라고 보고 멈춘다
  (종료 코드 4). 이것은 의도한 동작이다. CORE와 오도메트리가 정상인지 먼저 본다.
  `--assume-idle`은 벤치에서만 쓴다.
- 가져오는 도중에 로봇이 움직이기 시작하면, 이미 복사하고 해시를 맞춘 세션은 수거 표시를 하고
  거기서 멈춘다.

## 여러 사람이 같이 쓸 때

- **잠금.** 로봇의 섀도 포인터를 바꾸는 일(`deliver`, `rollback`, `release-hold`, 사이트 자동
  반영)은 로봇 안의 `/var/lib/rosy/models/.lock` 하나로 줄을 선다. 다른 사람이 작업 중이면
  30초 기다리고, 그래도 안 풀리면 "busy"로 실패한다. 잠시 뒤 다시 한다.
- **기록.** 포인터를 바꿀 때마다 로봇의 `/var/lib/rosy/models/history.jsonl`에 한 줄이
  남는다: 시각(UTC), 동작, revision, 이전 revision, 운영자, 운영자 PC 이름, 도구 commit.
  누가 무엇을 넣고 뺐는지는 `rosy_ml status`로 본다. 사이트 자동 반영은 `site:<hostname>`
  으로 남는다.
- **가장 새 모델이 섀도가 된다.** 여러 학습자가 같은 HF 모델 저장소에 올리면, intake를 통과한
  가장 새 commit이 섀도가 된다. 누가 올렸는지는 manifest의 `trainer`와 HF commit에 남는다.
- **운영자 보류(hold).** 누군가 `rollback`으로 어떤 revision을 뺐다면, 사이트 자동 반영은 그
  revision을 다시 넣지 않는다. 로봇의 마지막 포인터 기록이 그 rollback인 동안 보류가 유지된다.
  보류는 두 가지로 풀린다.
  - 누가 다른 revision을 `deliver`한다(더 새 모델이면 자동 반영도 그것을 따른다).
  - 문제를 확인한 사람이 `rosy_ml release-hold <robot>`을 실행한다. 다음 자동 반영 때 그
    revision이 다시 들어간다.
- 자동 반영은 넣기 전에 로봇의 실제 포인터와 기록을 읽는다. 사람이 이미 같은 revision을
  넣었으면 다시 보내지 않는다.

## 사이트 PC 자동 반영 켜기

사이트 PC(Ubuntu)의 `rosy-model-watch.timer`가 10분마다 HF 모델 저장소의 새 commit을 보고,
intake를 통과하면 설정된 로봇 모두의 섀도에 넣는다. 끝은 섀도다. 주행 반영은 하지 않는다.

1. 검토된 commit으로 `/opt/rosy/model-watch/src` 체크아웃과 venv를 준비한다
   ([`deploy/site/README.md`](../../deploy/site/README.md)의 "Automatic shadow delivery").
2. 설치 스크립트를 먼저 `--dry-run`으로 보고 실행한다. 여러 번 실행해도 된다.

   ```bash
   sudo /opt/rosy/model-watch/src/deploy/site/install-model-watch.sh --dry-run
   sudo /opt/rosy/model-watch/src/deploy/site/install-model-watch.sh
   ```

3. **사이트 전용 SSH 키.** 스크립트가 `/etc/rosy/model-watch/site-ed25519`를 만든다. 사람의
   키를 쓰지 않는다. 출력된 `.pub` 한 줄을 각 로봇 `rosy`의 `authorized_keys`에 넣는다.
   사이트를 끊을 때는 이 줄만 지우면 된다.
4. **읽기 전용 HF 토큰.** 비공개 저장소면 HF에서 read 권한 토큰을 만들어
   `sudoedit /etc/rosy/site/secrets/hf_token`에 붙여 넣는다. 파일이 비어 있거나 없으면
   토큰 없이 동작한다(공개 저장소).
5. `sudoedit /etc/rosy/model-watch.yaml`에 로봇 이름과 주소, 저장소, `replay_root`를 채운다.
   `replay_root` 아래 `data/teleop/learning/*.mp4` 재생 클립이 있어야 intake가 돈다.
6. 스크립트를 다시 실행하면 타이머를 켜고, 서비스 사용자로 `rosy_ml doctor --watch-config`를
   돌린다.

## 문제가 생기면

`rosy_ml doctor` 출력의 `✗` 줄을 보고 아래를 한다.

| doctor 줄 | 뜻 | 할 일 |
|---|---|---|
| `no config at ...` | 설정이 없다 | `rosy_ml init` |
| `SSH key ... ✗` | 키 파일이 없다 | `ssh-keygen`으로 만들고 공개키 등록을 요청한다 |
| `SSH key ... is readable by others` | 키 권한이 넓다 (Linux) | `chmod 600 <key>` |
| `<robot-ip> in known_hosts ✗` | 호스트 키 기록이 없다 | 믿을 수 있는 네트워크에서 한 번 기록한다 |
| `TCP 22 reachable ✗` | 로봇이 꺼졌거나 주소·네트워크가 다르다 | 전원, 설정의 주소, 같은 네트워크인지 확인 |
| `ssh as rosy (BatchMode) ✗` | 내 키가 그 로봇에 없다, 또는 호스트 키가 바뀌었다 | 공개키 등록 요청, 재플래시였다면 known_hosts 정리 |
| `sudo -n works ✗` | `rosy`의 비밀번호 없는 sudo가 없다 | 오래된 이미지다. 관리자에게 이미지 확인 요청 |
| `/var/lib/rosy/models is root:rosy-camera 750 ✗` | 모델 디렉터리가 없거나 권한이 다르다 | 벤치 로봇은 `deploy/robot/pinky_pro/dev/install-learned-perception.sh`, 아니면 D-373 이미지 |
| `robot python3 imports onnxruntime ✗` | 로봇에 추론 런타임이 없다 | 위와 같은 설치 스크립트 또는 재플래시 |
| `HF token file ... ✗` | 적어 둔 토큰 파일이 없다 | 파일을 만들거나 공개 저장소면 `hf_token_file`을 뺀다 |
| `replay clips for intake (0) ✗` | 재생 클립이 없다 | `replay_root`(또는 저장소 루트) 아래 `data/teleop/learning/*.mp4` |
| `! local onnxruntime` | 내 PC에서 intake를 못 돌린다 (권고) | venv에 `pip install onnxruntime` |

그 밖에:

- `deliver`가 `busy`로 실패: 다른 사람이 같은 로봇에서 작업 중이다. 잠시 뒤 다시 한다.
- `harvest`가 종료 코드 4: 로봇이 움직이는 중이거나 속도 값이 최신이 아니다. 로봇을 세우고,
  CORE와 오도메트리 상태를 확인한다.
- 자동 반영이 어떤 로봇에 안 들어간다: `rosy_ml status <robot>`에서 마지막 기록이 rollback이면
  보류 중이다. 확인 후 `rosy_ml release-hold <robot>`.
