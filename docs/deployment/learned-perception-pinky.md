# 학습 인식을 Pinky에 처음 올리기 (D-373)

처음 이 일을 맡은 팀 운영자를 위한 순서다. 학습 차선 모델을 로봇의 **섀도**로 돌려 보고,
규칙 기반과 어긋난 장면을 캡처해 가져오는 데까지 간다. 섀도 결과는 주행에 쓰이지 않는다.
주행 선택은 D-205 P3 재생 게이트 뒤의 별도 결정이고, 이 문서의 어떤 단계도 그 선을 넘지 않는다.

- 결정: [D-373](../adr/D-373-learned-perception-on-pinky-and-capture-loop.md), 계층 규칙은
  [D-225](../adr/D-225-update-without-reflash-and-faster-card-writes.md).
- `rosy_ml` 명령, SSH 키, 설정 파일, 보류(hold) 규칙은 [운영자 안내](learned-perception-operators.md)에
  있다. 여기서는 되풀이하지 않는다. `rosy_ml doctor`가 통과하는 상태에서 시작한다.
- 로봇 접속은 [rosy-device-access](../../.claude/skills/rosy-device-access/SKILL.md), 페이로드
  배포는 [rosy-release-push](../../.claude/skills/rosy-release-push/SKILL.md) 스킬을 따른다.
- 로봇은 `<robot>`(예: `pinky-005`), 주소는 `<robot-ip>`로 쓴다. 이 저장소는 공개다. 실제 주소,
  토큰, 로그인 코드는 어떤 기록에도 적지 않는다.

아래에서 "로봇에서"는 `rosy` 계정 SSH 세션을 뜻한다. 로봇에서 ROS 명령을 칠 때는 먼저 이
환경을 한 번 연다. `runtime.env`는 root 전용(0600)이라 `sudo -n`으로 읽는다.

```bash
sudo -n bash   # 이후 명령은 이 root 셸에서
set -a; . /etc/rosy/runtime.env; set +a
source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash
NS="${ROSY_NAMESPACE:+/$ROSY_NAMESPACE}"   # 네임스페이스가 비어 있으면 빈 문자열
```

## A. 무엇이 어느 계층인가

| 계층 (D-225) | D-373에서 바뀐 것 | 어디서 오나 | 기존 카드에 넣는 법 |
|---|---|---|---|
| 이미지 (SD 재굽기) | `onnxruntime`과 의존 wheel(해시 고정)을 전용 prefix `/opt/rosy/learned-perception/site-packages`에, `/var/lib/rosy/models` `root:rosy-camera 0750` | `deploy/robot/pinky_pro/image/learned-perception-requirements.txt`, `deploy/robot/pinky_pro/image/customize-rootfs.sh`, `deploy/robot/pinky_pro/native/tmpfiles-rosy-state.conf` | 벤치 설치 스크립트 (C절) |
| 부트·호스트 (유닛) | `rosy-camera.service`의 `EnvironmentFile=-/etc/rosy/learned-perception.env` | `deploy/robot/pinky_pro/native/rosy-camera.service` | 릴리스 사본에서 유닛 손 설치 (D절 2) |
| 페이로드 (서명 릴리스) | `learned_lane_node`, `capture_trigger_node`, 스냅샷 녹화, `camera_preview.launch.py`의 두 스위치 | `src/runtime/sensing/` | 페이로드 푸시 (D절 1) |
| 운영자 설정 (로봇 한 대) | `/etc/rosy/learned-perception.env`의 `ROSY_LEARNED_SHADOW`, `ROSY_CAPTURE` | 예시: `deploy/robot/pinky_pro/native/learned-perception.env.example` | `sudo install` (D절 3) |

스위치 파일이 없으면 두 기능 모두 꺼진다(유닛의 `-`). 값은 `true`와 `false`만 인정한다. 그 밖의
값(`True`, `1`, `yes`, 빈 값, CRLF 끝의 `true\r`)은 꺼짐이고, `journalctl -u rosy-camera`에
경고가 남는다.

## B. 새 SD로 시작하는 경우

D-373 이후 커밋으로 구운 이미지는 A절의 이미지·유닛 계층을 이미 갖는다. C절은 건너뛴다.

1. **이미지 빌드.** native ARM64 러너 워크플로
   [`build-pinky-image.yml`](../../.github/workflows/build-pinky-image.yml)을 `release_id`
   (`YYYY.MM.DD-NNN`, 재사용 금지)로 돌린다. 어느 산출물이 필요한지 판단은
   [릴리스 산출물 선택](pinky-release-artifact-selection.md)(`deploy/robot/pinky_pro/release/artifact_impact.py`)을
   따른다. 이 변경은 `flashable-image`로 분류된다.

   ```bash
   gh workflow run build-pinky-image.yml --ref main -f release_id=<id>
   ```

2. **서명과 검증.** 운영 PC에서 `deploy/robot/pinky_pro/release/sign_image_release.py`로 서명하고
   `deploy/robot/pinky_pro/sd/verify-image-release.py`로 공개키 재검증한다. 순서와 인자는
   [첫 장치 런북 0절](pinky-pro-first-device-runbook.md#0-build-and-sign-the-g0-release)과 같다.
3. **카드 쓰기.** Windows 운영 PC에서 `deploy/robot/pinky_pro/sd/prepare-rosy-sd.ps1`로 장치별 plan을
   만들고(`-PlanOnly`, 로봇 번호·Fleet·CORE 자격은 여기서 정해진다), 검토한 뒤
   `deploy/robot/pinky_pro/sd/write-card.ps1 -PlanPath ... -ReleaseDir ... -WifiProfile ... -Detach`로
   쓴다. 쓰기 뒤의 전체 readback(`deploy/robot/pinky_pro/sd/verify-media-readback.py`)이 권위 있는
   검증이다. 실패 문구의 `next:`를 따른다. 자세한 절차와 장애 대응은
   [첫 장치 런북](pinky-pro-first-device-runbook.md)의 "카드 쓰기 중 문제가 생겼을 때"와
   "Guided operator path"에 있다. 이미 쓰던 로봇 번호를 유지하려면 그 런북의 재프로비전 절차를 따른다.
4. **첫 부팅 뒤 확인.** 운영 PC에서:

   ```bash
   rosy_ml doctor <robot>
   ```

   `/var/lib/rosy/models is root:rosy-camera 750`과 `robot python3 imports onnxruntime` 두 줄이
   `✓`여야 한다. 로봇에서 `systemctl cat rosy-camera | grep learned-perception.env`가 한 줄을
   보여야 한다. 둘 다 맞으면 D절 3으로 간다(D절 1, 2는 필요 없다).

## C. 지금 쓰는 카드에 올리는 경우 (벤치)

재굽기 전 카드에 이미지 계층만 같은 파일·같은 규칙으로 넣는다. 스크립트는
`deploy/robot/pinky_pro/dev/install-learned-perception.sh`다. 설치 위치는 전용 prefix
`/opt/rosy/learned-perception/site-packages`(`root:root 0755`, `pip --target`)이고, 학습 백엔드만
그 경로를 `sys.path` 끝에 붙인다. 그래서 apt의 numpy·protobuf·packaging이 모든 서비스에서 그대로
우선한다. `/usr/local`과 카드의 Python 런타임 기록(`python-runtime.sha256`)은 건드리지 않는다. 릴리스 페이로드에는 `dev/`가 없으므로
운영 PC에서 필요한 파일만 묶어 보낸다(경로 구조를 유지해야 스크립트가 파일을 찾는다).

```bash
# 운영 PC, 저장소 루트. git archive는 .gitattributes의 LF 규칙을 지킨다.
git archive -o d373-bench.tar HEAD \
  deploy/robot/pinky_pro/dev/install-learned-perception.sh \
  deploy/robot/pinky_pro/image/learned-perception-requirements.txt \
  deploy/robot/pinky_pro/image/inputs.lock.yaml \
  deploy/robot/pinky_pro/native/tmpfiles-rosy-state.conf \
  deploy/robot/pinky_pro/verify/measure-resident-cpu.sh
scp d373-bench.tar rosy@<robot-ip>:
```

로봇에서:

```bash
mkdir -p ~/d373-bench && tar -xf ~/d373-bench.tar -C ~/d373-bench && cd ~/d373-bench
bash deploy/robot/pinky_pro/dev/install-learned-perception.sh --dry-run       # 바꾸는 것 없음
sudo -n bash deploy/robot/pinky_pro/dev/install-learned-perception.sh
```

- `--dry-run`은 `requirements_sha256=`(`inputs.lock.yaml`의 `learned_perception_runtime`과 같아야
  실행된다), `target=/opt/rosy/learned-perception/site-packages`,
  `dir d /var/lib/rosy/models 0750 root rosy-camera`, 설치할 파일 내용을 출력한다. `onnxruntime==`
  줄이 있는지 본다.
- 실제 실행은 root가 아니면 거절한다. 설치 뒤 prefix를 붙여 `onnxruntime`을 import하고, 버전이 잠금과
  다르면 멈춘다.
- 성공하면 마지막 줄에 기록 한 줄이 나오고 `/var/log/rosy/bench-installs.log`에도 남는다:
  `<UTC> d373-learned-perception requirements_sha256=<sha> onnxruntime=<ver> target=<prefix>`.
  이 줄을 E절의 증거 기록에 옮겨 적는다. 여러 번 실행해도 된다.

페이로드 Python 런타임 id(D-189, `device-python-requirements.txt`의 sha256)는 D-373으로 바뀌지 않는다.
그래서 이 설치를 했든 안 했든 새 릴리스는 모든 카드에서 활성화된다. 설치하지 않은 카드에서
`learned_shadow`를 켜면 노드는 멈추지 않고 `perception/learned/status`에 런타임이 없다는 이유를 낸다.

## D. 페이로드 반영과 스위치 켜기

1. **페이로드 푸시.** [rosy-release-push](../../.claude/skills/rosy-release-push/SKILL.md) 1–5단계대로
   `build-native-payload.yml` 빌드, 서명, `deploy/robot/pinky_pro/rosy-release-push.ps1`(먼저
   `-PrintCommands`)로 활성화한다. 성공 표시는 `current release: <id>`와 `CORE readiness: PASS`다.
2. **카메라 유닛 손 설치 (B절 이미지가 아닌 카드만).** 유닛은 이미지 계층이라 페이로드가 바꾸지
   않는다. 스킬 6단계대로 백업한 뒤 릴리스 사본에서 설치한다.

   ```bash
   B=/var/lib/rosy-bench-backup/$(date -u +%Y%m%dT%H%M%SZ)
   sudo -n install -d -m 0700 "$B"
   sudo -n cp -a /etc/systemd/system/rosy-camera.service "$B/"
   sudo -n install -m 0644 -o root -g root \
     /opt/rosy/current/deploy/robot/native/rosy-camera.service /etc/systemd/system/
   sudo -n systemctl daemon-reload
   systemctl cat rosy-camera | grep learned-perception.env
   ```

   마지막 줄이 `EnvironmentFile=-/etc/rosy/learned-perception.env`를 보여야 한다. 손 설치는
   `deploy/logs.md`에 남긴다(E절).
3. **섀도 켜기.** 예시 파일을 설치하고 섀도만 켠다. 캡처는 F절에서 켠다.

   ```bash
   sudo -n install -m 0644 -o root -g root \
     /opt/rosy/current/deploy/robot/native/learned-perception.env.example \
     /etc/rosy/learned-perception.env
   sudo -n sed -i 's/^ROSY_LEARNED_SHADOW=false$/ROSY_LEARNED_SHADOW=true/' /etc/rosy/learned-perception.env
   cat /etc/rosy/learned-perception.env | grep -v '^#'
   sudo -n systemctl restart rosy-camera
   journalctl -u rosy-camera -n 50 --no-pager | grep -E 'learned_lane_node|WARNING'
   ```

   `ROSY_LEARNED_SHADOW=true`와 `ROSY_CAPTURE=false`가 보여야 한다. 모델을 넣기 전이라
   `learned_lane_node`는 떠 있지만 "모델 없음"을 알린다(D-62). E절에서 모델을 넣는다.

## E. 첫 섀도 배포와 측정

1. **모델 접수와 전달.** 운영 PC에서 (자세한 설명은 [운영자 안내](learned-perception-operators.md)):

   ```bash
   rosy_ml store-status                         # inbox에 READY가 맞는 폴더가 있는지
   rosy_ml intake store-inbox:<inbox 폴더>       # PASS <model_revision> -> data/perception/models/<rev>
   rosy_ml deliver <robot> <model_revision>
   rosy_ml status <robot>
   ```

   손으로 한 `deliver`는 그 로봇에 보류를 건다. 사이트 자동 반영을 다시 받으려면 측정이 끝난 뒤
   `rosy_ml release-hold <robot>`.
2. **상태 확인.** 로봇에서(앞의 root 셸 환경):

   ```bash
   ros2 topic echo --once --qos-durability transient_local "$NS/perception/learned/status" std_msgs/msg/String
   ```

   `data`는 JSON이다. `model_revision`이 넣은 revision이고 `last_error`가 `null`이어야 한다.
   `frames_inferred`가 늘어나는지 몇 초 간격으로 두 번 본다. `last_error`가 있으면 그 문구가 이유다
   (모델 없음, 런타임 import 실패, 해시 불일치 등).
3. **지연과 건너뜀.** 같은 메시지의 `latency_ms_p50`과 `skip_ratio`를 카메라가 앞을 보는 평소 상태로
   2분 이상 돌린 뒤 읽는다. `skip_ratio`는 카메라가 낸 프레임 중 추론하지 못한 비율이다(바쁨으로
   건너뜀, 큐 버림, 모델 없는 동안의 프레임 포함).
4. **CPU.** C절에서 함께 보낸 `deploy/robot/pinky_pro/verify/measure-resident-cpu.sh`로 잰다. 섀도가
   켜진 상태에서 `rosy-camera.service` A/B를 120 s로 돌리면 카메라 유닛이 멈췄을 때와의 차이가
   나온다. 결과는 `/var/lib/rosy/resident-cpu-<ts>.md`에도 남는다. 기준 절차는
   [측정 기준선](../plans/2026-09-29-on-demand-activation-measurement-baseline.md)이다.

   ```bash
   sudo -n bash ~/d373-bench/deploy/robot/pinky_pro/verify/measure-resident-cpu.sh --ab-unit rosy-camera.service 120
   ```

   섀도를 끈 상태(`ROSY_LEARNED_SHADOW=false` → restart)로 한 번 더 재면 섀도 노드 몫이 나온다.
5. **기록할 값과 판정.**

   | 값 | 기준 | 비고 |
   |---|---|---|
   | `latency_ms_p50` | 125 ms 이하 (8 fps의 한 주기, D-373) | 넘으면 노드가 프레임을 건너뛴다 |
   | `skip_ratio` | 기록만 한다 | 합격선은 아직 정하지 않았다. 첫 실측 뒤 D-373 검토에서 정한다 |
   | `rosy-camera` CPU (섀도 켬/끔) | 기록만 한다 | D-185 CPU 예산과 비교해 적는다 |
   | 카드 이미지 release, 페이로드 release, `model_revision` | 필수 | 어떤 조합에서 잰 값인지 |
   | C절 벤치 설치 기록 줄 | 벤치 카드면 필수 | |

6. **기록 위치.** 저장소의 장치 증거 관례를 따른다.
   - `docs/validation/d373-learned-shadow-pinky-<YYYY-MM-DD>/README.md`에 범위, 위 표, 측정 명령과
     원문 요약을 적는다. 주소, 토큰, 로그인 코드, 영상은 넣지 않는다(예:
     [Pinky 카메라 캡처 기록](../validation/pinky-camera-capture-2026-09-26/README.md)). 원문 파일이
     필요하면 저장소 밖(`private/`, gitignore)에 둔다.
   - `deploy/logs.md`에 하네스 형식(변경·증거·gate 변화·결정·교훈)으로 한 항목을 추가하고, 손 설치를
     했으면 그것도 적는다. DEVICE gate를 바꾸는 판정은 검토를 거쳐 `deploy/progress.md`에 반영한다.

## F. 캡처 켜고 수거

1. **캡처 켜기.** 로봇에서:

   ```bash
   sudo -n sed -i 's/^ROSY_CAPTURE=false$/ROSY_CAPTURE=true/' /etc/rosy/learned-perception.env
   sudo -n systemctl restart rosy-camera
   ```

   이제 `camera/front/compressed`가 로봇 안에서만 나오고, `capture_trigger_node`와 스냅샷 녹화기가
   뜬다. 최근 60 s가 메모리 링버퍼에 있고, 섀도와 규칙 기반이 연속으로 어긋나면(또는 한쪽만 차선을
   보면) 스냅샷 하나가 세션 하나로 `/var/lib/rosy/camera/recordings` 아래에 남는다. 자동 트리거 뒤에는
   쿨다운이 있다. 섀도가 꺼져 있으면 자동 트리거는 없고 운영자 요청만 남는다.
2. **운영자 트리거.** 어긋난 장면을 봤을 때 사유를 적어 요청한다(연속 요청에는 짧은 제한이 있다).

   ```bash
   ros2 topic pub --once "$NS/capture/request" std_msgs/msg/String "{data: 'curve left, glare'}"
   ls -lt /var/lib/rosy/camera/recordings | head
   ```

   녹화기가 할당량이 차서 멈추면 이유를 로그에 남기고, 트리거 노드는 버린 트리거마다 로그를 남긴다.
   `journalctl -u rosy-camera`에서 본다. 수거 전 세션은 지우지 않는다.
3. **수거.** 로봇이 **서 있을 때만** 가져온다(D-136). 운영 PC에서:

   ```bash
   rosy_ml harvest <robot>        # data/perception/raw/<robot>/<session>/
   ```

   종료 코드 4는 움직이는 중이거나 속도 값이 오래된 것이다. 운영자 안내의 "문제가 생기면"을 본다.
4. **프레임 추출과 초벌 라벨.** 운영 PC에서 (`data/perception/`은 gitignore다):

   ```bash
   python tools/perception/dataset/extract.py data/perception/raw/<robot>/<session> --out data/perception/frames/<name>
   python tools/perception/dataset/prelabel.py data/perception/frames/<name> \
     --model data/perception/models/<model_revision> --classes <classes.yaml> --out data/perception/prelabel/<name>
   ```

   `extract.py`는 세션에 압축 토픽이 있으면 그것을 쓰고, 섀도 결과와 규칙 판단을 프레임에 붙인다.
   `prelabel.py`의 출력(`cvat_import.zip`, `images/`, `ranking.csv`)을 CVAT에 올린다. 이후 학습은
   [Colab 안내](../../tools/perception/training/COLAB.md)를 따른다.

## G. 되돌리기

| 상황 | 할 일 |
|---|---|
| 캡처만 끈다 | `ROSY_CAPTURE=false`로 고치고 `sudo -n systemctl restart rosy-camera` |
| 섀도와 캡처 모두 끈다 | `sudo -n rm /etc/rosy/learned-perception.env` 후 restart. 파일이 없으면 둘 다 꺼짐 |
| 새 모델이 이상하다 | `rosy_ml rollback <robot>` (바로 전 섀도로. 보류가 걸린다) |
| 사이트 자동 반영을 다시 받는다 | `rosy_ml release-hold <robot>` (포인터는 그대로) |
| 새 페이로드가 이상하다 | `deploy/robot/pinky_pro/rosy-release-push.ps1 -Robot <robot-ip> -Rollback` (스킬 5단계) |
| 손 설치한 유닛을 되돌린다 | D절 2의 백업에서 `rosy-camera.service`를 되돌리고 `daemon-reload` |

자동으로 **일어나지 않는** 일:

- 섀도 모델이 주행에 쓰이는 일. 사이트 자동 반영의 끝은 섀도다. 주행 활성화는 D-205 P3 게이트 뒤의
  별도 결정이고, 이 절차의 어떤 명령도 하지 않는다.
- 스위치가 켜지는 일. `/etc/rosy/learned-perception.env`는 사람만 만든다. 이미지와 페이로드는 이 파일을
  만들지 않는다.
- 녹화가 로봇 밖으로 나가는 일. `rosy_ml harvest`를 사람이(또는 사람이 켠 도구가) 서 있는 로봇에서
  돌릴 때만 나간다.
- 수거 전 세션이 지워지는 일.

## 부록. 첫 Pi 5 실측 (2026-09-30, `rosy-pinky-8kcn`)

시스템을 바꾸지 않은 측정이다. onnxruntime과 의존 휠을 `/tmp`에만 풀고, 서비스(core·io·camera)가 도는 상태에서 쟀다.

- **장치:** Pi 5, aarch64, 4코어, 메모리 8 GB, Ubuntu 24.04.5, Python 3.12.3
- **런타임:** apt numpy 1.26.4 + onnxruntime 1.30.0(이미지 블록과 같은 휠 해시). import와 추론 모두 정상, 출력은 유한값이다.
- **모델:** 0930 LaneUNet, 입력 1×3×240×320. 프레임 30장의 지연(ms)이다.

| 형식 | 1 스레드 | 2 스레드 | 3 스레드 | 4 스레드 |
|---|---|---|---|---|
| FP32 p50 | 332 | 215 | **198** | 247 |
| INT8 QDQ p50 | 157 | **136** | 140 | 166 |

- **INT8 산출 방식:** 개발 PC에서 `onnxruntime.quantization.quantize_static`으로 만들었다. QDQ, per-channel, teleop 프레임 200장으로 보정했다.
- **INT8 정확도:** teleop 프레임에서 FP32와 픽셀 argmax 일치율이 평균 0.990, 최소 0.982였다.
- **해석:** FP32는 8 fps 예산(125 ms)을 넘어 약 5 fps다. INT8 2 스레드는 약 7.4 fps로 예산에 가깝다.
  - 4 스레드가 느린 것은 다른 서비스와 CPU를 다투기 때문으로 본다.
  - 섀도 배포의 첫 후보는 INT8, 2 스레드다.
- **남은 조건:**
  - INT8 파일도 별도 산출물로 intake를 통과해야 한다(D-356).
  - 이 측정은 노드 없이 추론만 잰 값이다. 섀도 노드를 실제로 켠 상태의 `skip_ratio`, 지연, CPU는 E절 절차로 다시 기록한다.
