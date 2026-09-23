# 텔레옵 확인과 주행 기록

이 폴더는 로봇을 보며 확인한 내용과 주행 기록을 두는 자리다. 소스도 설치 절차도 아니다.
세션 안의 파일은 git에 들어가지 않는다.

| 폴더 | 담는 것 |
|---|---|
| `teleop/` | 수동 주행으로 확인하면서 적은 명령과 메모 |
| `drive/` | 주행 기록. 궤적 줄과 rosbag/MCAP |

세션을 만들 때:

```text
python tools/run_data.py teleop forward-check
python tools/run_data.py drive map-loop
python tools/run_data.py list teleop
python tools/run_data.py write data/teleop/<session> "{\"linear\":0.1,\"angular\":0}"
```

각 세션에는 `session.json`과 `notes.md`가 생긴다. 텔레옵 세션은 `commands.jsonl`, 주행 세션은 `trace.jsonl`과 `bags/`를 가진다.
