## D-943 Rosy Learning OMX 한 바퀴: GPU 학습, 장치 초안, 작업대 녹화 버튼, HF 업로드 버튼

**Status:** Accepted (2026-11-01). 사용자가 "GPU 학습, 앱에서 녹화, 팔 자동 인식, HF 업로드 버튼"을 지시했다. 구현·시험·착지 증거는 `docs/logs.md`와 착지 기록이 가진다.

### Context

2026-11-01 실물 점검에서 Rosy Learning(모델 PC `rosy-edge-review`)의 OMX 학습 센터는 떠 있었지만 한 바퀴를 버튼으로 돌 수 없었다.

- 학습은 CPU만 받았다(`CPU only until shared GPU admission is connected`). 모델 PC의 RTX 5080을 쓰지 못했다.
- 팔 프로필은 팔 ID·관절·카메라를 모두 손으로 입력한다. 관제 PC에는 OpenRB-150 네 개, 카메라 네 대, LeRobot 보정 파일이 이미 있다.
- 녹화는 관제 PC에서 `record_session.py`를 셸로 실행하고, 봉인(`record_seal.py`)·전송(`omx_collection_transfer.py`)도 명령이다.
- HF 전송은 `learning/registry/policy/hub_sync.py` CLI뿐이고 토큰은 서버의 `HF_TOKEN`·login cache다. Learning에는 이미 암호화된 HF 연결과 `publish` 권한·`write-repos` 범위 검사(`learning_accounts.management_credential`)가 있다.

### Decision

1. **GPU 학습.** 센터는 학습기 Python이 CUDA를 보고할 때만 ACT에 `cuda`를 제공한다. 지속 SAC는 CPU로 둔다. `cuda` 작업자는 학습 내내 `~/.cache/rosy-learning/gpu.lock`(Isaac admission·perception 학습기와 같은 잠금)을 잡고, 다른 compute 프로세스가 있으면 `GpuBusy`로 시작하지 않는다. 학습기 Python은 센터 설정의 `python`이 가리키는 별도 CUDA venv다. CPU venv는 남긴다.
2. **장치 초안(팔 자동 인식).** 관제 PC가 읽기 전용 장치 목록을 낸다. 내용은 by-id serial 보드, 그 보드에 붙은 역할(관찰 서비스 env·녹화 설정에 이미 선언된 것만), LeRobot 보정 파일 이름, `omx-cameras.json` 카메라 역할·해상도다. Learning 프로필 화면의 「연결된 작업대에서 채우기」는 이 목록으로 **초안**만 채운다. 역할을 모르는 보드는 「미지정」으로 보여 주고 추측하지 않는다. 저장은 지금처럼 사람이 확인한 뒤에만 하며, 저장된 프로필은 장치 권한을 얻지 않는다.
3. **녹화 버튼은 작업대 화면에 둔다.** 팔이 움직이는 녹화는 사람이 리더 팔을 잡고 다른 손을 follower 전원 스위치에 둔다. 그래서 시작 버튼은 관제 PC의 작업대 화면에 두고, 모델 PC의 Learning은 그 화면으로 가는 링크와 수집 결과만 보여 준다. 모델 PC에서 관제 PC로 팔을 움직이는 원격 시작 경로는 만들지 않는다. 버튼은 기존 `record_session.py`(caps·카메라 인계·torque OFF 종료)와 `record_seal.py`, 전송을 순서대로 실행하는 래퍼를 부른다. 안전 동작은 바꾸지 않는다. 시작 전 「작업대에 있고 전원 스위치를 잡고 있음」 확인과 관찰 서비스의 포트 인계가 필요하다.
4. **HF 업로드 버튼.** 센터의 등록 자료나 끝난 학습 결과를 고르면, 서버가 `hub_sync.prepare_bundle`로 묶음을 만들어 파일 목록·해시를 보여 준다. 사람이 「업로드」를 누를 때만 프로젝트 HF 연결의 `management_credential(scope='write-repos')`로 `hub_sync.upload_bundle`을 실행한다. 대상은 기존 private 저장소만이며 새 저장소 생성·공개 전환은 하지 않는다(D-756 §4·§5). 토큰은 요청·로그·영수증에 남기지 않는다. 업로드는 사람이 누른 버튼으로만 일어나며 에이전트·타이머가 대신 누르지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-756 | 녹화·업로드를 별도 명시 작업으로 유지한다. 버튼이 그 명시 작업이다. Hub 전송은 registry `hub_sync`만 한다 |
| D-770 | 자동 교사 출처 표시와 수집 계보를 그대로 쓴다 |
| D-834 | GPU 공유 잠금 `gpu.lock`을 같은 경로로 쓴다 |
| D-857 | Rosy Learning 센터 하나의 5단계 메뉴 안에 둔다 |
| D-430 | `record_session.py`의 owner·정지·복구 동작은 바꾸지 않는다. 바꿀 때는 독립 안전 검토를 받는다 |

### Consequences

- 모델 PC 디스크를 CUDA venv(약 4 GB)가 더 쓴다.
- GPU가 Isaac에 잡혀 있으면 GPU 학습은 거절되고 CPU로 다시 요청해야 한다.
- 녹화 버튼은 관제 PC 화면에 생기므로 원격지에서는 녹화할 수 없다. 이는 의도한 제한이다.
- HF 업로드는 프로젝트에 `write-repos` 범위의 HF 연결과 private 저장소가 있어야 동작한다.
