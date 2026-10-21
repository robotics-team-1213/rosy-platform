# 텔레옵 확인과 주행 기록

이 폴더는 로봇을 보며 확인한 내용과 주행 기록을 두는 자리다. 소스도 설치 절차도 아니다.
세션 안의 파일은 git에 들어가지 않는다.

## 저장소 밖 데이터

host 도구는 `ROSY_DATA_ROOT`가 설정되면 그 **절대 경로** 아래의 기존 상대 구조를 사용한다. 설정하지 않으면 기존 기본 경로를 유지한다. 예를 들어 `$env:ROSY_DATA_ROOT = 'D:/local-data/platform'`로 지정하면 세션은 `teleop/`, `drive/`, perception 자료는 `perception/`, PC 보정 자료는 `calibration/` 아래에 둔다. 빈 값·상대 경로는 거절한다.

지원 범위는 `tools/run_data.py`와 perception의 autolabel·bag_to_video·catalog·geometry·fetch_http·harvest·reclaim/media_pipeline·map_projected_drivable·edge_capture_session의 host 기본 경로다. 개별 `--root`·`--out`·`--dest`·`--work`와 설정에 명시한 store/보정 경로는 그대로 사용한다. model intake/deliver, watcher, `rosy_ml`의 모델 출력·store는 기존 명시적 CLI/설정을 사용하며 이 환경변수가 장치 모델 pointer나 운영 profile을 바꾸지 않는다.

환경변수 값이 비정상인 경우에는 기본 경로를 해석하는 도구의 시작을 거절한다. 명시적 CLI 경로를 사용하더라도 먼저 이 환경변수를 해제하거나 올바른 절대 경로로 고친다. 정상 설정에서 명시적 CLI 옵션이 기본값보다 우선한다.

PC 보정 mirror의 소비자인 `tools/calibration/{store_cli,run_calibration,camera_board,analyze_session}.py`와 `tools/capture/edge_drive.py`도 같은 환경변수를 사용한다. PC의 자료 경로만 바꾸며 accepted record의 identity·상태·허용 범위나 로봇의 `/var/lib/rosy/calibration`을 변경하지 않는다. 환경변수만으로 자료를 생성·승인·장치에 적용하지 않는다.

이관 전 쓰기 상태·백업을 확인하고 원본과 새 위치의 파일 목록·bytes·SHA-256, catalog·manifest·실제 reader를 대조한다. store 내부 상대 경로·사람 판정·train/eval 계보를 바꾸거나 symlink로 우회하지 않는다. 환경변수 지원만으로 운영 state 이관이 완료되지는 않는다.

| 폴더 | 담는 것 |
|---|---|
| `teleop/` | 수동 주행으로 확인하면서 적은 명령과 메모. 세션은 커밋하지 않음 |
| `teleop/learning/` | 학습용으로 남기는 텔레옵 영상. 이 폴더만 커밋한다 |
| `drive/` | 주행 기록. 궤적 줄과 rosbag/MCAP. 세션은 커밋하지 않음 |

세션을 만들 때:

```text
python tools/run_data.py new teleop forward-check
python tools/run_data.py new drive map-loop
python tools/run_data.py list teleop
python tools/run_data.py write data/teleop/<session> "{\"linear\":0.1,\"angular\":0}"
```

각 세션에는 `session.json`과 `notes.md`가 생긴다. 텔레옵 세션은 `commands.jsonl`, 주행 세션은 `trace.jsonl`과 `bags/`를 가진다.
