# 학습 인식 모델 운영자 안내 (D-373)

팀에 새로 들어온 운영자를 위한 문서다. 학습한 차선 인식 모델을 로봇의 **섀도 슬롯**에
넣고 빼는 일, 로봇에서 녹화를 가져오는 일을 다룬다. 섀도 모델은 주행에 쓰이지 않는다.
주행 선택은 D-205 P3 게이트 뒤의 별도 결정이다.

명령은 `rosy_ml` 하나다(`learning/training/perception/rosy_ml.py`). 아래 예시는 저장소 루트에서
`python learning/training/perception/rosy_ml.py ...`로 실행하고, 편의상 `rosy_ml`로 줄여 쓴다.
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
   기록한다. 키는 주소가 아니라 **로봇 id** 이름으로 기록한다(`ssh -o HostKeyAlias=<robot>`로 읽는다).
   현장 네트워크가 바뀌어 IP가 달라져도 핀이 그대로 유효하다.

   ```bash
   ssh-keyscan -t ed25519 <hostname>.local | sed 's/^[^ ]* /<robot> /' >> <known_hosts>
   ```

   이후에는 `StrictHostKeyChecking=yes`라서 키가 바뀌면 접속이 거부된다(종료 코드 79).
   SD를 다시 구운 로봇이면 관리자와 확인한 뒤 `ssh-keygen -R <robot> -f <known_hosts>`로
   지우고 다시 기록한다. 검사를 끄지 않는다. 예전에 주소(IP) 이름으로 기록해 둔 핀은
   `rosy_ml doctor`가 알려 주며, `rosy_ml repin <robot>` 한 줄이 그 키를 로봇 id 이름으로
   복사한다(옛 줄은 그대로 둔다. 알아서 고쳐 쓰지 않는다).

4. **설정 파일을 만든다.** 비밀값은 설정에 넣지 않는다. 토큰은 *파일 경로*만 적는다.

   ```bash
   rosy_ml init --robot pinky-005=<hostname>.local --robot pinky-007=<hostname>.local \
     --store <store 폴더 경로> --core-token-file <CORE viewer 토큰 파일>
   ```

   - 호스트는 로봇의 mDNS 이름(`<hostname>.local`, avahi, `rosy-pinky-<4자>`)을 쓴다. IP도 되지만
     권장하지 않는다. 현장 네트워크가 바뀌면 주소가 달라지고, init과 doctor가 IP를 경고한다.
   - `--store`는 팀의 store 폴더다(아래 "store 폴더"). HF는 필요 없다.
   - HF도 쓰는 팀만 `--hf-repo <hf-org>/<model-repo> --hf-token-file <내 HF 토큰 파일>`을 더한다.
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

## store 폴더

데이터셋과 모델의 정본은 **store 폴더** 하나다(D-373 결정 8). **HF는 선택이다.** HF 계정이 없어도
녹화 → 데이터셋 → 학습 → intake → 섀도 배포 전체가 돈다.

- 지금은 사이트 PC의 로컬 폴더다. 나중에 NAS나 Google Drive로 옮길 때는 그 폴더를 마운트하고
  (사이트 PC의 Google Drive for desktop, 또는 SMB/NFS 마운트) 설정의 `store` 경로만 바꾼다.
  구조와 명령은 그대로다. 운영자 PC도 같은 폴더를 마운트한 경로를 `--store`로 적는다.
- 구조:

  ```text
  <store>/datasets/<name>/<content_sha>/   데이터셋 (한 번 쓰면 바꾸지 않는다)
  <store>/models/inbox/<폴더>/             학습자가 넘긴 모델
  <store>/models/accepted/<revision>/      intake 통과
  <store>/models/rejected/<폴더>/          intake 탈락 (REJECTED.txt에 이유)
  ```

- **버전은 내용 해시다.** `content_sha`는 폴더 안 파일의 상대 경로와 sha256을 정렬해 해시한 값이다.
  같은 내용이면 어느 PC, 어느 OS에서 계산해도 같다.
- **READY 규칙.** inbox 폴더는 안에 `READY` 파일이 있고 그 내용이 폴더의 `content_sha`와 같을 때만
  완성으로 본다. Drive나 NAS에서 아직 동기화 중인 폴더는 표식이 없거나 맞지 않으므로 사이트 PC가
  건드리지 않는다. 노트북과 `handover.py`는 파일을 모두 쓴 **뒤에** `READY`를 쓴다.
- **데이터셋 올리기.** 만든 데이터셋을 store에 넣고, 출력된 ref를 학습자에게 준다.

  ```bash
  python learning/training/perception/dataset/publish.py data/perception/datasets/<name>   # --store 기본값은 설정의 store
  # dataset: store:<name>@<content_sha>   ← 이 줄을 학습자에게 전달
  ```

  Drive를 못 쓰는 학습자에게는 `datasets/<name>/<content_sha>/` 폴더를 zip으로 묶어 준다.
  노트북이 풀고 내용 해시를 다시 확인한다.
- **모델 받기.** 학습자가 zip을 주면 store의 `models/inbox/`에 그대로 푼다(zip 안에 `READY`가 있다).
  Drive를 마운트한 학습자는 노트북이 inbox에 바로 넣는다.
- `rosy_ml store-status`: 데이터셋 목록과 inbox(완성/대기), accepted, rejected 개수.
  새 store에는 `rosy_ml store-status --init`이 폴더 구조를 만든다.

## 매일 쓰는 명령

```bash
rosy_ml status                              # 모든 로봇: 섀도 포인터, 설치된 revision, 최근 기록
rosy_ml status pinky-005 --history 20       # 한 대, 기록 20줄
rosy_ml store-status                        # store: 데이터셋, inbox/accepted/rejected
rosy_ml intake store-inbox:<폴더>           # inbox의 모델 검사 (통과 시 data/perception/models)
rosy_ml intake <모델 폴더>                   # 아무 폴더나 검사 (HF를 쓰면 hf:<org>/<repo>@<40자리 commit>도 된다)
rosy_ml deliver pinky-005 <model_revision>  # 섀도에 넣기 (intake 통과본만)
rosy_ml rollback pinky-005                  # 바로 전 섀도로 되돌리기
rosy_ml release-hold pinky-005              # 이 로봇의 자동 반영을 다시 켜기 (포인터는 그대로)
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

규칙은 하나다.

> 사람이 손으로 deliver/rollback 하면 그 로봇의 자동 반영은 멈춘다; `rosy_ml release-hold <robot>`로 다시 켠다.

- **보류(hold) 파일.** 손으로 한 `deliver`나 `rollback`은 로봇의
  `/var/lib/rosy/models/hold`(root:rosy-camera 0640)에 누가, 어디서, 언제, 무엇을, 왜 했는지를
  JSON으로 남긴다. 포인터를 옮기기 **전에** 쓰므로, 도중에 실패해도 보류는 남는다. 이 파일이
  있는 동안 사이트 자동 반영은 그 로봇에 아무것도 넣지 않는다. `rosy_ml status`와
  `rosy_ml doctor`가 보류를 보여 준다.
- **보류 풀기.** `rosy_ml release-hold <robot>`은 보류 파일만 지우고 기록을 남긴다. 섀도
  포인터는 바꾸지 않는다. 다음 자동 반영(10분 이내) 때 사이트가 그 로봇의 실제 포인터를 읽고,
  intake를 통과한 가장 새 모델이 아니면 그 모델을 다시 넣는다. 전에 받았던 모델이라도 되돌려져
  있으면 다시 넣는다.
- **잠금.** 포인터를 바꾸는 일(`deliver`, `rollback`, `release-hold`, 사이트 자동 반영)은 로봇
  안의 `/var/lib/rosy/models/.lock` 하나로 줄을 선다. 다른 사람이 작업 중이면 30초 기다리고,
  그래도 안 풀리면 종료 코드 `75`("busy")로 실패한다. 잠시 뒤 다시 한다.
- **기록은 감사용이다.** 포인터를 바꿀 때마다 `/var/lib/rosy/models/history.jsonl`에 한 줄이
  남는다: 시각(UTC), 동작, revision, 이전 revision, 운영자, 운영자 PC 이름, 도구 commit.
  사이트 자동 반영은 `site:<hostname>`으로 남는다. 보류 여부는 기록이 아니라 보류 파일로
  정하므로, 기록 파일을 정리(rotation)해도 보류는 사라지지 않는다. 포인터를 옮기기 전에 기록
  파일에 쓸 수 있는지 확인하고, 쓸 수 없으면 아무것도 바꾸지 않고 종료 코드 `3`으로 멈춘다.
  옮긴 뒤 기록만 실패하면 "pointer changed, history not written"을 출력하고 `3`으로 끝난다.
- **가장 새 모델이 섀도가 된다.** 여러 학습자가 같은 store inbox에 넘기면, intake를 통과한
  가장 새 폴더(`READY`가 가장 늦은 것)가 섀도가 된다(보류 중인 로봇은 제외). 누가 넘겼는지는
  manifest의 `trainer`에 남는다. HF 백엔드를 쓰면 가장 새 commit이 같은 규칙을 따른다.
- 사이트 자동 반영은 로봇 잠금 안에서 보류 파일을 한 번 더 본다. 그 사이에 누가 보류를 걸었으면
  종료 코드 `76`("held")으로 아무것도 바꾸지 않고 물러난다.

## 사이트 PC 자동 반영 켜기

사이트 PC(Ubuntu)의 `rosy-model-watch.timer`가 10분마다 store의 `models/inbox/`에서 `READY`가 맞는
새 폴더를 찾아 intake하고, 통과하면 `models/accepted/<revision>/`으로 옮기고 설정된 로봇 모두의
섀도에 넣는다. 탈락하면 `models/rejected/<폴더>/`로 옮기고 `REJECTED.txt`에 이유를 쓴다.
디스크·런타임 같은 설비 오류면 inbox에 그대로 두고 다음 실행에 다시 한다. 끝은 섀도다.
주행 반영은 하지 않는다. HF 모델 저장소를 보게 하려면 설정에 `backend: hf`와 `repo:`를 쓴다(선택).

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
4. `sudoedit /etc/rosy/model-watch.yaml`에 로봇 이름과 주소, `store`(기본 `/srv/rosy/store`),
   `replay_root`를 채운다. `replay_root` 아래 `data/teleop/learning/*.mp4` 재생 클립이 있어야
   intake가 돈다. 스크립트가 store 폴더와 구조를 만들고, 서비스가 그 경로에 쓸 수 있게
   unit drop-in(`ReadWritePaths`)을 넣는다. store를 NAS나 Drive로 옮길 때는 마운트한 뒤
   `store`만 바꾸고 스크립트를 다시 실행한다.
5. **HF 토큰은 `backend: hf`일 때만.** 비공개 HF 저장소를 보게 할 때만 read 권한 토큰을
   `sudoedit /etc/rosy/site/secrets/hf_token`에 붙여 넣는다. store만 쓰면 토큰 파일은 만들지 않는다.
6. 스크립트를 다시 실행하면 타이머를 켜고, 서비스 사용자로 `rosy_ml doctor --watch-config`를
   돌린다.

## 문제가 생기면

`rosy_ml doctor` 출력의 `✗` 줄을 보고 아래를 한다.

| doctor 줄 | 뜻 | 할 일 |
|---|---|---|
| `no config at ...` | 설정이 없다 | `rosy_ml init` |
| `SSH key ... ✗` | 키 파일이 없다 | `ssh-keygen`으로 만들고 공개키 등록을 요청한다 |
| `SSH key ... is readable by others` | 키 권한이 넓다 (Linux) | `chmod 600 <key>` |
| `host name resolves ✗` | 설정의 호스트 이름이 이 네트워크에서 풀리지 않는다 | 설정의 이름 확인, 로봇 전원, mDNS(avahi/Bonjour) 차단 여부 |
| `host key pinned under <robot> ✗` | 호스트 키가 로봇 id 이름으로 기록돼 있지 않다 | 줄에 `rosy_ml repin <robot>`이 있으면 그것을, 없으면 믿을 수 있는 네트워크에서 한 번 기록한다 |
| `host is an IP` (경고) | 주소가 바뀌면 끊긴다 | 설정의 호스트를 `<hostname>.local`로 바꾼다 |
| `TCP 22 reachable ✗` | 로봇이 꺼졌거나 주소·네트워크가 다르다 | 전원, 설정의 주소, 같은 네트워크인지 확인 |
| `ssh as rosy (BatchMode) ✗` | 내 키가 그 로봇에 없다, 또는 호스트 키가 바뀌었다 | 공개키 등록 요청, 재플래시였다면 known_hosts 정리 |
| `sudo -n works ✗` | `rosy`의 비밀번호 없는 sudo가 없다 | 오래된 이미지다. 관리자에게 이미지 확인 요청 |
| `/var/lib/rosy/models is root:rosy-camera 750 ✗` | 모델 디렉터리가 없거나 권한이 다르다 | 벤치 로봇은 `deploy/robot/pinky_pro/dev/install-learned-perception.sh`, 아니면 D-373 이미지 |
| `robot python3 imports onnxruntime ✗` | 로봇에 추론 런타임이 없다 | 위와 같은 설치 스크립트 또는 재플래시 |
| `store ... exists ✗` | store 폴더가 없다, 또는 NAS·Drive가 마운트되지 않았다 | 마운트하거나 폴더를 만든다. 설정의 경로가 마운트된 경로인지 확인 |
| `store ... is writable ✗` | store에 쓸 권한이 없다 | 내 사용자(사이트 PC는 `rosy-model-watch`)에게 쓰기 권한 |
| `store layout: missing ... ✗` | `datasets`나 `models/inbox` 같은 폴더가 없다 | `rosy_ml store-status --init` |
| `! no store configured` | 설정에 `store`가 없다 | `rosy_ml init --store <경로> --force` 또는 설정에 `store:` 추가 |
| `HF token file ... ✗` | (HF를 쓸 때만) 적어 둔 토큰 파일이 없다 | 파일을 만들거나 공개 저장소면 `hf_token_file`을 뺀다 |
| `replay clips for intake (0) ✗` | 재생 클립이 없다 | `replay_root`(또는 저장소 루트) 아래 `data/teleop/learning/*.mp4` |
| `! local onnxruntime` / `! local onnx` | 내 PC에서 intake를 못 돌린다 (권고) | venv에 `pip install onnxruntime onnx` |
| `local onnx importable ✗` (사이트 PC, `--watch-config`) | watcher venv에 `onnx`가 없다. intake가 모델 정밀도를 못 읽어 watch가 매번 `6`으로 멈춘다 | `deploy/site/README.md`의 pip 줄(`onnx==1.23.1`)로 설치 |

### 종료 코드

`rosy_ml`의 종료 코드는 감싼 도구의 코드 그대로다(`deliver`, `rollback`, `release-hold`, `status`는
deliver, `harvest`는 harvest). 사이트 자동 반영(watch)은 journal에 남는다.

| 도구 | 코드 | 뜻 |
|---|---|---|
| deliver | `0` | 성공 |
| deliver | `1` | 실패(SSH·scp·원격 단계, 시간 초과). 다시 한다 |
| deliver | `2` | 내 PC에서 거부(인자, intake 보고서, 해시, 키 설정). 메시지대로 고친다 |
| deliver | `3` | 로봇의 `history.jsonl`에 쓸 수 없다(디스크, 권한). "pointer changed, history not written"이면 포인터는 이미 바뀌었으니 `rosy_ml status`로 확인한다 |
| deliver | `75` | busy: 다른 사람이 같은 로봇에서 작업 중이다. 잠시 뒤 다시 한다 |
| deliver | `76` | held: 사이트 자동 반영(`--unless-held`)만 받는다. 그 로봇에 보류가 있다 |
| deliver | `77` | 호스트 이름이 풀리지 않는다(DNS/mDNS). 설정의 이름, 로봇 전원, 같은 네트워크인지 확인한다 |
| deliver | `78` | 접속 거부·시간 초과·경로 없음. 로봇이 꺼졌거나 다른 네트워크에 있다 |
| deliver | `79` | 호스트 키를 모르거나 바뀌었다. 자동 수락하지 않는다. 로봇을 확인한 뒤 다시 핀한다(3단계, `rosy_ml repin`) |
| harvest | `0` | 모두 가져왔다 |
| harvest | `1` | 일부 세션이 실패했다. 다시 하면 남은 것만 가져온다 |
| harvest | `2` | 인자가 잘못됐다 |
| harvest | `4` | 로봇이 움직이는 중이거나 속도 값이 최신이 아니다. 로봇을 세우고 CORE와 오도메트리를 확인한다 |
| doctor | `0` | 필수 점검 모두 통과 |
| doctor | `1` | 필수 점검 중 `✗`가 있다 |
| doctor | `2` | 설정이나 인자가 잘못됐다 |
| watch | `0` | 끝났고 재시도할 것이 없다(탈락, 보류, busy는 기록된 결과다) |
| watch | `1` | intake 설비 오류, store 이동 실패, 로봇 push 실패. 다음 실행에 다시 한다 |
| watch | `2` | 설정이나 상태 파일 오류 |
| watch | `5` | 목록을 못 읽었다(store가 없거나 마운트되지 않음, HF 백엔드면 HF 목록 실패). 아무것도 기록하지 않았다 |
| watch | `6` | 설정 오류: watcher venv에 필요한 패키지(`onnx`, `onnxruntime` 등)가 없다. 아무것도 기록하지 않고 시도 횟수도 쓰지 않는다. venv를 고치고 `rosy_ml doctor --watch-config`로 확인한다 |
| intake | `4` | 설정 오류: 이 PC의 venv에 필요한 패키지가 없다(모델 탓이 아니다) |

그 밖에:

- 자동 반영이 어떤 로봇에 안 들어간다: `rosy_ml status <robot>`의 `hold:` 줄에 누가 걸었는지
  나온다. 그 사람과 확인한 뒤 `rosy_ml release-hold <robot>`.

> **참고 (2026-10-03, D-434):** 이 문서의 "사이트 PC"(모델 watch·store·사이트 SSH 키)는 모델 PC를 뜻한다. 관제 PC는 사이트 스택만 돌린다.
