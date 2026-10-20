# 웹·CLI 공통 Isaac 실험 실행

모델 PC의 기존 Isaac SDK와 동일 계정의 학습 잠금을 사용한다. D-834는 Proposed이며 최초 시나리오는 `omx-f-import`의 모델·관절·120프레임 검사다. 항만 집기·적층·회수·협응 복구는 D-826의 후속 물리 검증 전까지 비활성이다.

## 운영 binding

실험 요청에는 경로·명령·호스트를 넣지 않는다. 운영자가 별도 JSON binding으로 승인 source checkout, SDK Python, 설치된 model-code root와 외부 run 데이터 루트를 고정한다. 모든 경로는 해당 모델 PC의 값이며 공개 문서에는 실제 계정·주소를 쓰지 않는다.

```json
{
  "uid": 1000,
  "source_root": "/ABSOLUTE/COMMITTED/SOURCE",
  "source_sha": "FULL_40_LOWERCASE_HEX_COMMIT",
  "sdk_python": "/ABSOLUTE/EXISTING/SDK_VENV/bin/python",
  "sdk_python_sha256": "SHA256_OF_INTERPRETER_BYTES",
  "sdk_version": "5.1.0.0",
  "model_code_root": "/ABSOLUTE/INSTALLED/MODEL_CODE_ROOT",
  "data_root": "/ABSOLUTE/EXTERNAL/RUN_DATA"
}
```

binding과 경로는 같은 계정 소유이며 group/world 쓰기를 허용하지 않는다. `data_root`는 미리 만든 외부 디렉터리다. SDK Python의 마지막 symlink는 venv 관례대로 허용하되 실행 파일 지문을 확인한다. source는 실행 모듈이 있는 깨끗한 전체 SHA checkout이어야 한다. `~/.config/rosy/model-code.json`의 설치 root와 다르면 거절한다. SDK 설치나 서비스 enable은 이 실행기의 기능이 아니다.

## 실행·중지·증거

로컬 공통 진입은 `/usr/bin/python3 SOURCE/learning/envs/isaac/run_control.py --binding BINDING.json`의 stdin JSON이다. `catalog`, `check`, `start`, `list`, `status`, `stop`, `artifact`만 처리한다. `check`는 SDK 배포 metadata·GPU 관찰과 두 잠금을 확인하며 SimulationApp을 시작하지 않는다.

- `check`: `scenario_id`, `config`(`{"seed":0}`), `source_sha`를 받아 정규화 입력과 `input_sha256`을 반환한다.
- `start`: `request`에 새 32자리 hex `request_id`, 같은 시나리오·설정·SHA와 `expected_input_sha256`을 넣는다. 선택적 `parent_run_id`는 새 재실행의 출처다.
- `status`: 같은 `run_id`를 조회한다. `stop`은 여기에 현재 `expected_revision`을 추가한다. 중지 요청과 실제 종료 확인은 구분한다.
- `artifact`: 최종 manifest의 `artifact_id`만 조회한다. 결과 JSON은 bounded base64이며 클라이언트가 해시와 크기를 다시 확인한다. SDK 원시 로그·USD는 웹 공개 산출물에 등록하지 않는다.

start는 저장소에 launch intent를 먼저 예약한다. 같은 요청을 재전송해도 동일 run이며 새 unit을 시작하지 않는다. `rosy-isaac-RUN_ID.service`는 한 번만 시작하는 transient user unit이다. RuntimeMaxSec=180, TimeoutStopSec=10, KillMode=control-group, MemoryMax=12G를 적용한다. worker는 `work.lock` 다음 `gpu.lock`을 잡고 SDK child에 FD를 상속한다. 부모가 죽어도 살아 있는 child의 잠금은 유지된다. 다른 계정이나 관리 밖 프로그램까지 잠금으로 차단하지는 못하므로 GPU 관찰 실패·외부 compute 점유는 시작을 거절한다.

SDK supervisor는 실행165초, 원시 로그16MiB, 관찰 output 합계256MiB·256파일을 상한으로 감시한다. 출력 상한은 짧은 주기의 감시·종료이며 filesystem quota는 아니다. 한 파일128MiB 초과·symlink·비정규 출력도 종료 사유다. SDK가 종료되어도 보고서·전체 프레임·관절·자산·SDK 지문과 소유 프로세스/GPU 해제 확인이 있어야 모델 검사 성공이다. seed는 이 import에 사용되지 않는다. 기본 import에는 영상이 없다.

## 연결 유실·복구

receipt의 run을 다시 조회한다. `UNKNOWN`은 unit 소유권·결과·cleanup을 확인할 수 없다는 뜻이며 자동 재실행하지 않는다. 같은 run ID의 systemd unit을 reset/reuse하지 않는다. 중지 전에 unit·InvocationID·boot ID·cgroup·worker PID 시작 시각을 대조하며, 다르면 신호를 보내지 않는다. 일치하면 열린 pidfd로 해당 worker에만 SIGUSR1을 보내고 worker가 소유 SDK를 종료한다. 확인 뒤 unit/PID가 바뀌어도 다른 프로세스로 신호가 향하지 않는다. 강제 종료·재부팅 후 결과가 없으면 실패나 성공을 추정하지 않는다.

SDK 원시 로그는 run 디렉터리의 `sdk.log`이며 내부 경로가 포함될 수 있다. 외부 공유 전 별도 검토한다. 불변 input·최종 result·artifact manifest는 덮어쓰지 않는다. 실제 SDK 실행·웹/CLI 교차 조회 증거는 별도 실험 기록으로 남긴다. host pytest는 실물 집기·학습 적합·정책 승격의 증거가 아니다.
