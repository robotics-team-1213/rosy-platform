## D-871 모든 호스트 서비스 자동 업데이트와 통합관제 업데이트 화면

**Status:** Accepted for implementation (2026-10-25, 사용자 결정). 1단계(셀 카메라·관측기)는 이 변경으로 구현한다. 나머지는 아래 순서로 따로 구현한다. 관제 PC 적용과 실물 확인은 별도다.

### Context

- D-805는 업데이트 경로를 둘로 나눴다. 서명 이미지 경로(사이트 스택)와 CI 통과 main을 따르는 네이티브 경로(OMX 셀 도구, AI PC 상황 서비스)다. D-852는 각 PC 사용자 유닛의 출처를 `deploy/hosts/services.yaml`에 적었다.
- 2026-10-25 `update_status.py` 실측: 다음은 `snapshot`이나 `installer`라 사람이 손으로 설치한다. 관제 PC의 카메라 3대, 화질 뷰어·준비 서비스, 토크 OFF 관측기 2개, 관측 브리지, 모델 PC·AI PC의 학습 센터, 모델 PC의 review v12·v13-eval이다. 업데이트 결과는 Fleet 화면 어디에도 보이지 않는다(D-805 열린 항목).
- 사용자 지시(2026-10-25):
  - 현장 PC와 기타 기기는 GitHub main을 보고 스스로 업데이트한다.
  - 카메라·관측기는 셀이 쉴 때만, 학습 센터는 작업이 없을 때만 바꾼다.
  - review v12·v13-eval도 포함한다.
  - 통합관제에서 PC·앱별 업데이트 정보를 본다. 관제는 중앙→현장→기기 트리이고, 한 현장에 셀(팔 1대 또는 2대)마다 관제 PC가 따로 붙을 수 있다.
  - 역할에 따라 보이는 화면이 다르다.

### Decision

1. **셀 장치 서비스는 셀 유휴 때만 자동으로 바꾼다.** 대상은 카메라(`rosy-omx-camera@`, camera-view, camera-readiness), 관측기(`rosy-omx-observer@`), 관측 브리지다.
   - 이들은 `omx_autoupdate.py`의 `kind: service` 설정 하나(`omx-devices-autoupdate.json`, 루트 `~/.local/share/rosy/omx-devices`)로 함께 움직인다.
   - `idle_gate: cell`이면 셀 도구와 같은 유휴 규칙을 쓴다. 셀의 `session.lock`을 쥐고 있는 세션이 없고, 관측기 말고 버스를 연 프로세스가 없고, 관측기 health가 모든 모터 토크 OFF를 보고해야 한다.
   - 잠금은 smoke 확인 뒤, 재시작 전에 놓는다. 관측기는 시작할 때 같은 잠금을 직접 확인하기 때문이다.
   - `restart_running_only`이면 바꾸기 전에 active였던 유닛만 다시 띄운다. 실제 owner로 넘기려고 손으로 멈춘 관측기는 멈춘 채로 둔다. 되돌릴 때도 같은 목록을 쓴다.
   - venv는 `requirements-observation.lock`을 호스트 Python 위에 만든다(`system_site_packages: true`). 관측기에는 시스템 ROS `rclpy`가 필요하다.
   - env 파일과 유닛에는 커밋 해시를 쓰지 않는다. 경로는 `current`를 가리킨다. 관측기의 health 파일은 템플릿이 인스턴스 이름(`%i`)으로 정한다. 브리지의 health 목록은 env `ROSY_OBSERVATION_ARM_HEALTH`가 주므로, 팔 1대 셀과 2대 셀이 같은 유닛을 쓴다.
2. **학습 센터는 실행 중인 작업이 없을 때만 바꾼다.** 2026-10-23 교훈의 수동 절차를 별도 업데이터가 그대로 수행한다.
   - 실험 프로세스가 없는지 본다.
   - `source/<sha>`에 clone하고, `prepare()`로 새 유닛을 만든다.
   - 유닛을 백업하고 서비스를 멈춘 뒤 `--apply`.
   - HTTP 200을 확인한다. 실패하면 백업을 되돌린다.
3. **나머지 snapshot 서비스도 `kind: service`로 main을 따른다.** 대상은 review v12·v13-eval, cam-stream, site-discovery, account-tls다. 인증서·토큰은 데이터 폴더에 남긴다. `signed` 경로(D-446 model-code, review v13)와 D-441 사이트 스택은 그대로 둔다.
4. **모든 새 업데이트 유닛은 D-805 동결 관문을 지난다.** 신뢰 기준은 셀과 같다. GitHub Actions `ci-result` 성공과 설치된 커밋의 후손이어야 한다.
5. **통합관제 업데이트 화면.**
   - Fleet `GET /api/fleet/hosts`가 호스트마다 업데이터 상태를 낸다. 상태에는 경로, 현재·이전 커밋, 마지막 판정과 시각, 실패 커밋, STUCK(6시간 안에 정상 판정 없음), 동결 여부가 들어간다.
   - 수집은 기존 host-guard pull 경로를 넓혀서 한다. 새 에이전트는 만들지 않는다.
   - 역할별 화면은 D-270·D-757을 따른다. 패널은 숨기지 않고 서버가 capability로 막는다.
     - viewer: 요약.
     - operator: 실패 사유와 기록. 그리고 "지금 확인"과 "이전 버전으로" 실행(기명 operator만).
     - policy-admin: 현장 동결 걸기·풀기.
6. **트리.** 현장 아래 노드는 셀 관제 PC N대(각 셀의 팔·카메라), AI·모델 PC, 로봇이다. 호스트 목록은 현장별 목록에서 만든다. 고정 `site/ai/model` 세 개로 두지 않는다. 중앙 Fleet이 현장 요약을 읽기 전용으로 모으는 일은 D-454 §10.1 다음 단계에서 정한다.

### 일부러 하지 않는 것

- 카메라·관측기를 셀 도구(`~/rosy-omx`) 릴리스에 섞지 않는다. 셀 도구 env는 Python 3.12이고 lerobot이 들어 있다. 관측기 env는 시스템 Python과 ROS를 쓴다. 둘을 한 venv로 만들 수 없다.
- 업데이트가 관측기를 새로 시작시키지 않는다. 토크 OFF 관측이 실제 owner를 막는 일을 자동으로 만들지 않는다.

### Consequences

- 관측기가 멈춰 있으면 토크 OFF 근거가 없다. 이때 셀 장치 업데이트는 `follower_torque_not_off`로 보류된다. 이는 안전한 쪽으로 실패하는 것이다.
- 관제 PC를 처음 적용할 때는 사람이 다음을 확인한다.
  - env 경로를 `current`로 바꾸고, SHA가 박힌 drop-in을 지운다.
  - 실제 전환 1회, `rollback` 1회.
  - 카메라 스트림, 관측기 health, `/console/cell`.
- 셀이 쉬는 동안 smoke 확인과 재시작 사이에 세션이 시작될 수 있다. 그러면 관측기가 시작을 거부하고, 그 릴리스는 `rolled_back` → `known_bad`로 남는다. 다음 main 커밋에서 다시 시도한다.

### Validation

- SOURCE: `test/test_omx_autoupdate.py`
  - 셀 게이트 서비스가 바쁜 셀, 장치 사용, 토크 ON에서 보류되는지.
  - 재시작 전에 잠금을 놓는지.
  - 설정 검사.
  - 시스템 패키지 위 venv.
  - 실행 중인 유닛만 다시 띄우는지, 되돌릴 때 같은 목록인지.
- SOURCE: `test/test_omx_workcell_observation_bridge.py`: env의 health 목록. `test/test_update_gate.py`: 새 업데이트 유닛의 관문. `test/test_update_status.py`: services.yaml.
- DEVICE: 관제 PC 적용 기록은 적용한 뒤 이 문서에 덧붙인다.

**References:** D-805, D-852, D-530, D-441, D-446, D-454, D-270, D-757, D-785.
