## D-841 공통 모듈 재사용과 독립 앱의 계약 검증 범위를 정한다

**Status:** Accepted for implementation (2026-10-22). 사용자의 목표 등록·구현 지시와 두 독립 검토자의 2차 검토 합의를 반영한다. 구현·시험·배포·장치 수용 완료를 뜻하지 않는다.

### Context

공통 계약과 UI 모듈은 이미 소비되고 있으나 일부 화면의 HTTP 처리와 학습 산출물 경로 정책이 반복된다. Port는 HTTP 어댑터와 가짜 서버 시험을 갖췄지만 실제 플랫폼·관측 producer 연결은 후속이다. Vault는 고정 계약 fixture와 명시적으로 실행하는 실제 Fleet 시험을 가진다.

조사 플랫폼은 `238af6c8990f`, Port는 `c5bb3cf39efc`, Vault는 `ad7030b319d5`다. 공유 모듈이 존재한다는 사실과 실제 소비·배포·물리 연동 증거를 구분해야 한다.

### Decision

1. 기존 `contracts/foundation`·`contracts/learning`·`contracts/motion`·`contracts/skill`의 정본을 소비한다. 업무 절차·산출물 저장 정책을 계약 wheel에 넣거나 새 전역 utils 패키지를 만들지 않는다.
2. Fleet의 `applications/fleet/web/devices/enrollment.js`와 `camera-pairing.js`는 기존 `shared/web/request.js:createRequest`를 소비한다. 화면별 오류 의미·`detail.code`·`attempts_left`·`reason`, 자격 선택과 취소·수명 검사를 보존한다. 공통 API는 확장하지 않는다. POST 자동 재전송을 추가하지 않는다.
3. `installation/camera-peer.js`는 1차 전환에서 제외한다. 현재 응답 헤더 수신 직후 권한 거절을 처리하고 성공 JSON 파싱 실패를 던진다. 공통 request는 파싱 후 반환하고 파싱 실패·204를 null로 돌려주므로 단순 치환은 허위 성공 표시를 만들 수 있다. 헤더 시점 처리·엄격 JSON을 함께 지원하는 후속 설계와 body 지연·malformed/empty 2xx·204 시험이 마련될 때 재검토한다.
4. 학습 경로 정책은 `learning/curation/omx`와 `learning/registry/policy` 안에서 각각 합친다. 표준 라이브러리만 사용하는 `in_source_checkout(path) -> bool`을 소유 모듈에 두고 `.git` 디렉터리·worktree 파일·미생성 출력·resolve된 조상 검사를 보존한다. 두 모듈이나 Fleet·로컬 실행 사이에 내부 import를 새로 만들지 않는다.
5. 독립 Port/Vault 앱은 공개 HTTP 계약을 소비한다. 앱 업무 모델·장부를 플랫폼 모델에 합치지 않는다. 고정 플랫폼·앱 SHA로 실제 Fleet route를 검증하고 fixture 출처 SHA와 호환성 시험 SHA를 구분한다. test-only 서버 조립의 플랫폼 import는 앱 런타임으로 전파하지 않는다.
6. 공식 플랫폼 runner는 외부 앱 저장소·임의 서버 명령을 전달하지 않는다. 앱 전달·전체 SHA 확인·독립 시험 환경·서버 ready/종료 경로를 먼저 확인한다. 없으면 인프라 blocker로 기록하고 fake 통과나 skip을 실제 연동 성공으로 보고하지 않는다.
7. 기존 Fleet admission·장치 owner 권한을 유지한다. 같은 요청 키 재접수·다른 본문 충돌·권한 거절·busy·불명 접수·오래된 관측을 검증한다. 관측 producer의 ID·시도·시각·출처와 장치 수용이 없으면 물리 연동은 미완료다. Vault DEFERRED는 픽업 완료 근거가 아니다.
8. 독립 배포 CORE/Fleet proof helper의 복제와 `test/architecture/test_peer_proof_ownership.py` 동일성 검사는 유지한다. 중복 개수만 줄이기 위해 배포 경계를 결합하지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-425 | 공통 HTTP 기계 처리와 화면별 오류 의미 분리를 적용한다 |
| D-427 | middleware·operations·learning 소유·배포 경계를 유지한다 |
| D-429 | API 경계·device/site owner를 유지하며 내부 구현 import로 우회하지 않는다 |
| D-430 | 안전 판단과 장치 명령 권한을 UI·업무 앱으로 이동하지 않는다 |
| D-442 | 기존 교차 파트 계약을 사용하고 경로 정책용 wheel을 만들지 않는다 |
| D-836 | 기존 공정·후보 admission을 소비한다. simulation 계약은 실물 활성화가 아니다 |

### Alternatives

- 모든 중복을 전역 패키지로 이동: 복제는 가장 작아지나 독립 배포·Python 버전·장치 payload가 결합되므로 기각한다.
- 기존 공통 모듈 소비 + 소유 범위 내 통합 + 실제 계약 검증: 선택한다. 일부 복제를 남기되 현재 구조를 활용한다.
- 계약 시험만 강화: 변경 위험은 작지만 반복 처리 유지보수는 남는다. 짧은 guard 통합을 별도 커밋·검증하는 절충안을 택한다.

### Consequences and verification

Fleet 전송, OMX curation, policy registry를 별도 커밋·시험 범위로 처리한다. 새 공통 자산 변경이 필요하면 소비자 변경과 분리한다. 실패 시 해당 소비자 또는 소유 모듈 변경만 복구하며 원본·장부·장치 설정을 이관하지 않는다.

완료 기준은 대상 두 화면의 공통 소비와 인증·오류·취소 회귀 통과, 지정 학습 여덟 파일의 경로 정의를 두 모듈로 축소한 뒤 CLI·거절 순서 보존, Port/Vault 실제 route의 SHA·실행·skip 증거 기록이다. 플랫폼 pytest는 커밋 SHA를 공식 원격 runner로 검증한다. host 시험은 물리 관측·장치·현장 수용을 대체하지 않는다.

구조·critic 독립 검토 2라운드를 거쳤으며 camera-peer 제외와 외부 앱 시험 인프라 조건을 보완한 선택안에 모두 APPROVE했다. 이번 등록은 사용자가 허용한 작업용 worktree 1개 추가 예외를 사용한다. 예외가 기존 worktree 정리·main 착지·push 허가를 뜻하지 않는다.
