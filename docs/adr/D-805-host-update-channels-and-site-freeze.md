## D-805 호스트 업데이트: 장치 owner는 네이티브, 나머지는 컨테이너 — 역할별 두 경로와 현장 전체 동결 관문

**Status:** Proposed (2026-10-19). 사용자 지시: "나머지 PC들도 오토 업데이트가 필요하고, 각 PC를 docker로 실행하는 것도 고려". 이 결정은 D-246(네이티브 기본, 컨테이너 보조)·D-441(사이트 스택 서명 자동 업데이트)·D-530(역할별 원하는 상태)·D-225/D-412(Pinky payload)를 바꾸지 않고 그 위에 역할별 업데이트 경로와 동결 관문을 정한다. 검토: ralplan(아키텍처·비판 독립 2인) 1회.

### Context

- 관제 PC의 사이트 스택(Fleet·Vision·proxy)은 Docker이고 D-441 서명 자동 업데이트가 동작한다. OMX 셀 도구는 네이티브이고 `deploy/robot/omx/omx_autoupdate.py`(사용자 타이머)가 CI 통과 main을 유휴 때만 전환한다(#97).
- AI PC는 Docker 없이 네이티브 사용자 유닛(상황 서비스·ollama·SAM 작업기 등)을 손으로 배포한다(`deploy/ai_pc/deploy-situation.sh`는 커밋별 폴더 + `current`). 모델 PC도 유닛을 손으로 복사한다.
- 스스로 코드·이미지·모델·엔진을 바꾸거나 호스트를 재부팅하는 타이머가 여러 개다: `rosy-site-autoupdate`, `rosy-docker-upgrade`, `rosy-nightly-reboot`(site·model·ai), `rosy-model-watch`, `rosy-model-code-update`, `rosy-review-release-update`, `rosy-omx-autoupdate`, Pinky `rosy-auto-update`(D-412)·`rosy-update-check`. 시연 날 이들이 따로 움직이면 막을 한 곳이 없다.
- 역할별 원하는 상태는 이미 D-530 `rosy-host-state`가 역할 폴더(`deploy/site|model_pc|ai_pc/host-state/`)로 설치·유지한다(새 `deploy/hosts/<role>/` 트리를 만들지 않는다, D-530 1). 호스트 상태는 `/api/fleet/hosts`가 보여 준다.

### Decision

1. **실행 단위.** 장치를 직접 여는 것(OMX owner·셀 도구·카메라 캡처, Pinky CORE)은 네이티브다. 나머지(사이트 스택, AI 추론·상황 서비스, 모델 PC 학습·평가)는 컨테이너가 목표다(D-246 그대로 호스트별로 적용).
2. **배포 단위는 역할이다.** 역할은 D-530의 `site`·`model`·`ai`에 Pinky `robot`을 더한 것이고, OMX 셀은 `site` 호스트의 일부다. 역할별 업데이트 대상과 관문은 그 역할의 `host-state/manifest`에 둔다.
3. **업데이트 경로는 둘이다.** 컨테이너 경로 = D-441(서명 이미지, 건강 확인·롤백)을 역할별로 넓힌다(AI·모델은 후속). 네이티브 경로 = `omx_autoupdate.py`(셀)와 D-225/D-412(로봇). 하나의 호스트 에이전트로 합치는 일은 11/21 시연 이후다.
4. **현장 전체 동결 관문.** 업데이트하는 모든 유닛은 시작 전에 `/usr/local/bin/rosy-update-gate`를 `ExecCondition=`으로 돈다(`deploy/hosts/common/host-state/rosy-update-gate`). 동결 조건은 셋 중 하나다: 코드 저장소에 태그 `ops-update-freeze`가 있다(현장 전체, 태그 메시지에 누가·왜·해제 예정일), `/etc/rosy/update-freeze`가 있다(그 호스트), `~/.config/rosy/update-freeze`가 있다(그 사용자). 태그를 확인하지 못하면(네트워크·git 오류·10 s 초과) **건너뛴다**(fail closed). 실행 판정은 `git ls-remote`가 성공했고 태그가 없을 때뿐이다. 관문은 0(실행) 또는 1(건너뜀, 사유 한 줄)만 낸다. 255를 내지 않아 유닛이 실패로 표시되지 않는다.
   - 태그는 main 저장소 규칙(기본 브랜치 대상) 밖이다. push 권한이 있는 사람은 누구나 동결·해제할 수 있다 — 받아들인 위험이다.
   - 동결은 새 실행만 막는다. 동결한 뒤 `systemctl list-units 'rosy-*'`(system·user)로 도는 업데이트가 끝났는지 확인한다.
5. **설치 경로.** 관문 스크립트(`deploy/hosts/common/host-state/rosy-update-gate`)는 host-state `common` manifest의 `safe file`로 `/usr/local/bin/rosy-update-gate`에 설치·유지된다. 유닛은 `ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'`로 부른다: 관문이 아직 없으면 sh가 127을 내 그 실행은 건너뛴다(fail closed)(사이트 유닛이 저장소나 `current`에서 관문을 읽지 않는다). 시스템 유닛은 drop-in `<unit>.service.d/10-update-gate.conf`(host-state가 설치 후 `daemon-reload`), 사용자 유닛(`rosy-omx-autoupdate`·`rosy-model-code-update`·`rosy-review-release-update`)은 유닛 파일에 `ExecCondition=`을 직접 둔다. 크기 동결 파일 `rosy_site_autoupdate.py`는 바꾸지 않는다.
6. **시연 동결.** 2026-11-14에 태그를 올리고 시연(11/21)이 끝난 뒤 해제한다.
7. **신뢰.** 컨테이너 경로는 D-441 서명을 쓴다. 네이티브 셀 경로는 서명 키가 준비될 때까지 CI 통과(Actions 보고)·조상 확인에 기대고, 준비되면 같은 서명으로 맞춘다. 자동 반영 범위가 넓어지므로 main 규칙의 필요 승인 수를 1 이상으로 올리기를 권한다(사용자 결정).

### 일부러 하지 않는 것

- 새 역할 파일 트리나 별도 호스트 상태 도구를 만들지 않는다(D-530의 manifest·status·`/api/fleet/hosts`를 쓴다).
- 로봇(D-412) 유닛에 관문을 이 결정에서 넣지 않는다. 로봇은 이미지·payload로만 바뀐다(D-225). 그때까지 시연 동결은 로봇 자동 업데이트 타이머를 멈추는 절차로 한다.
- AI PC 서비스의 컨테이너 전환과 모델 PC 학습 이미지는 후속(P1·P2)이다.

### 열린 항목

- 각 PC에 host-state를 다시 설치해야 관문과 drop-in이 놓인다: `sudo python3 deploy/hosts/common/rosy-host-state install <site|model|ai>`(사람, sudo). 사용자 유닛은 다시 복사하고 `systemctl --user daemon-reload`.
- AI PC에서 기계 사이 DDS 유닛(`pinky-nav2`, `pinky-rosbridge-d12`, `pinky-rosbridge-d13`)이 아직 돈다. 정리는 그 결정 기록과 공동 사용자 동의(D-530 §6)를 거친 뒤 의존 관계(역의존 유닛, 연결, backend/frontend 설정)를 확인하고 한다.
- 업데이트 결과·동결 상태를 `/api/fleet/hosts`에 보이게 하는 일(host-state status 확장).

### Consequences

- 업데이트하는 유닛 하나를 늘릴 때는 관문을 같이 붙인다(`test/test_update_gate.py`가 현재 목록을 고정한다).
- GitHub에 닿지 않는 동안에는 모든 관문 유닛이 건너뛴다. 업데이트는 그동안 멈추고, 그 밖의 서비스는 영향이 없다.

### Validation

- SOURCE: `test/test_update_gate.py`(태그 없음·있음, git 실패·시간 초과·부재, 로컬 동결 파일, 유닛·manifest 연결), `test/test_host_state.py`.
- DEVICE: 관제 PC에서 태그를 만들면 다음 `rosy-omx-autoupdate` 실행이 건너뛰고(조건 실패 기록), 지우면 다시 돈다.

**References:** D-225, D-246, D-301, D-412, D-441, D-524, D-530.
