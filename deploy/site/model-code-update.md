# 모델 PC 코드 업데이트 (D-446)

모델 PC도 갱신 대상이다. 로봇은 D-412의 signed runtime, 관제 PC는 D-441의 signed site stack, 모델 PC는 D-446의 signed perception code를 쓴다. 자동 코드 적용과 GPU 환경 변경·학습 시작·주행 모델 승격은 별개다.

## 설치와 첫 적용

운영자 PC의 저장소 밖에 모델 코드 전용 Ed25519 개인 키/공개 키를 준비한다. 다른 역할의 signing key를 재사용하지 않는다. 개인 키는 모델 PC로 보내지 않는다. 모델 PC에는 `rosy_model_code.py`, `candidate_signing.py`, `install-model-code.sh`, `rosy-model-code-*.service/.timer`와 공개 키만 전달한다. 다음은 모델 PC 운영자 사용자로 실행한다. `--enable` 없이 설치하면 timer를 시작하지 않는다.

```bash
bash deploy/site/install-model-code.sh \
  --python "$HOME/rosy-ml/.venv/bin/python" \
  --public-key /path/outside/repo/model-code-public.pem --key-id model-code-v1 \
  --work-dir "$HOME/rosy-ml/rosy-platform" \
  --legacy-root "$HOME/rosy-ml" --legacy-root "$HOME/isaac-sim-workspace"
```

모델 PC의 고정 업데이트기를 기존 학습 Python으로 실행하여 `fingerprint` 결과의 `sha256`을 받는다. 이 명령은 의존성 메타데이터만 읽으며 패키지를 설치하지 않는다.

```bash
"$HOME/rosy-ml/.venv/bin/python" -I "$HOME/.local/lib/rosy-model-code/rosy_model_code.py" fingerprint
```

운영자 PC에서 **검증·승인한 full SHA**를 지정하여 생성한다. sequence는 이전 승인보다 큰 정수여야 한다. `git archive`는 해당 commit의 perception subtree와 import 의존성 control/core_common을 읽고 저장소 상대 경로를 보존한다. 새 candidate가 기존 환경과 맞는지는 사전에 GPU·변환·평가로 검증한다. 실제 진입점의 isolated `--help` 검사도 후보 활성화 전에 수행한다. 코드를 최신 main이라는 이유만으로 자동 승인하지 않는다.

```bash
python deploy/site/rosy_model_code.py build --repo /path/to/repo \
  --commit <40-hex-approved-commit> --sequence <increasing-integer> \
  --environment-sha256 <model-pc-environment-sha256> \
  --output /scratch/model-code-candidate \
  --key-id model-code-v1 --private-key /outside/repo/private.pem --public-key /outside/repo/public.pem
```

SSH host key를 이미 pin한 모델 PC의 inbox에 후보 폴더를 전달한다. `code.tar`, `release.json`, `release.json.sig`를 먼저 보내고 **READY를 마지막에** 보낸다. 부분 전송은 소비하지 않는다. 전송 완료 후 한 번 run을 실행하여 결과를 확인한다. `held`이면 현재 작업/hold를 보존하고 다음 timer를 기다린다.

```bash
python3 -I "$HOME/.local/lib/rosy-model-code/rosy_model_code.py" \
  --config "$HOME/.config/rosy/model-code.json" run
systemctl --user enable --now rosy-model-code-update.timer
systemctl --user status rosy-model-code-update.timer
journalctl --user -u rosy-model-code-update.service -n 20
```

사용자 서비스의 재부팅 후 실행에는 기존 linger가 필요하다. 없으면 관리자에게 `loginctl enable-linger <model-pc-user>`를 요청한다. 설치가 관리자 권한이나 계정/SSH 변경을 대신 수행하지 않는다. 후보 생성·서명·전달은 이 단계에서 명시적 릴리스 작업이며, main push→CI→서명 PC 자동 발행 연결은 후속이다.

## 작업과 model-watch

관리 작업은 고정 실행기를 사용한다. 한 번 잡은 작업 lock과 source는 종료까지 유지되며 자식 프로세스에도 lock이 전달된다. GPU 작업끼리도 직렬화한다. Python isolated bootstrap에는 고정 후보의 import 경로만 추가하므로 NCNN helper의 sibling import도 같은 후보를 쓴다. 후보 ROOT/data는 controller가 등록된 work_dir/data로 연결하고 작업 cwd는 기존 외부 work_dir로 유지한다. 코드 archive에는 data나 symlink가 들어가지 않는다. 따라서 기존 CLI 기본 출력 경로도 외부 데이터로 연결되며 기존 파일을 복사·삭제하지 않는다. 인수 원문은 receipt에 쓰지 않으며 source commit·환경 지문·script·인수 hash·종료 코드를 기록한다. 기존 notebook/직접 실행 작업은 legacy/GPU 관측으로 보호하지만 새 작업은 실행기를 사용하도록 전환한다.

```bash
python3 -I "$HOME/.local/lib/rosy-model-code/rosy_model_code.py" \
  --config "$HOME/.config/rosy/model-code.json" exec rosy_ml.py doctor
```

기존 model-watch YAML을 별도로 유지한다. store·replay·gate·SSH key/known_hosts는 payload 밖의 기존 경로를 지정하고, 운영용 state_file/intake_out은 타 세션의 검증 디렉터리와 나눈다. `install-model-code.sh --watch-config /outside/repo/model-watch.yaml --enable`은 기존 YAML을 덮어쓰지 않으며 doctor 성공 후에만 watch timer를 활성화한다. doctor 실패 또는 legacy/GPU 작업 때문에 준비가 끝나지 않으면 watcher는 활성화하지 않는다. 운영 config를 바꾼 뒤에는 같은 doctor를 다시 실행한다.

model-watch도 같은 실행기와 lock을 사용한다. 평가 후 shadow까지만 전달하고 로봇의 실제 hold를 존중한다. updater 성공은 학습 결과·모델 품질·주행 수용 증거가 아니다.

## 보류와 복구

- `$ROOT/HOLD`가 있으면 updater만 보류한다. 작업을 중단하지 않는다.
- GPU 관측 실패, 사용률/compute job, legacy learning/Isaac job 또는 work lock은 `held`다. GPU 사용률 0만으로 유휴 판정하지 않는다.
- 환경 fingerprint 불일치는 별도 환경 릴리스를 요구한다. updater는 pip/apt/CUDA/Isaac 업그레이드를 실행하지 않는다.
- 잘못된 서명·payload 경로·hash·환경은 source를 바꾸지 않는다. 실패 sequence는 자동 재시도하지 않는다. 수정한 코드를 더 큰 sequence의 새 서명 후보로 공급한다.
- 전환 뒤 검사 실패는 이전 symlink로 복귀한다. 전환 중 중단되어 pending이 남으면 다음 run이 먼저 이전 symlink를 복구한다. 데이터와 checkpoints는 복구 대상에서 제외된다.
- `status`의 desired_commit/source_commit/sequence/result와 user journal을 함께 읽는다. 후보·receipt는 별도 상태 경로에 보존되며 자동 pruning은 하지 않는다. 운영자가 보존할 후보를 확인한 후 releases/inbox만 정리한다.
