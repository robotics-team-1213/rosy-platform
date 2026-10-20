# Fleet application

Fleet 앱을 수정할 때는 이 폴더에서 시작한다. 플랫폼 API·원장·실행 조정 변경은 `operations/fleet`에서 한다.

| 위치 | 책임 |
|---|---|
| `web/` | 정적 ES module 화면. 기존 Fleet 서버가 `/console`에서 제공한다. |
| `gateway/` | `rosy-app-gateway` wheel. 기존 `rosy-site-gateway` 명령과 Fleet CLI를 조립한다. |
| `../../operations/fleet/` | HTTP API·인증·Mission 원장·admission·dispatch와 기존 Fleet 배포 |

화면은 별도 Node 서버나 빌드 단계 없이 제공된다. gateway는 기존 `rosy-palletizing`·`rosy-execution`에 의존하고 실행 시 Fleet 패키지가 필요하다. 화면은 Fleet HTTP API와 저장소의 `shared/web` 자산을 사용한다. 패키지 버전은 gateway의 `pyproject.toml`을 따른다.

저장소 루트에서 기존 [현장 PC 실행 안내](../../deploy/site/README.md)와 [개발 환경 안내](../../docs/reference/developer-guide.md)를 따른다. 화면 수정은 `web/`, 앱 진입점·공정 조립 수정은 `gateway/src/rosy_gateway/`에서 한다. `/console` URL과 설치된 `fleet.server.web` 이름은 유지한다.

검증은 루트 지침대로 커밋한 SHA를 원격 시험 PC에서 실행한다. 대상은 `operations/fleet/test`, `test/test_platform_installed_entrypoints.py`, `test/test_platform_minimal_install.py`와 변경 화면에 대응하는 browser suite다. 브라우저 검증에는 `ROSY_RUN_BROWSER_TESTS=1`이 필요하다. skip은 실행 증거가 아니다.

## 백엔드 없이 화면 개발

저장소 루트에서 Python 3.10 이상으로 실행한다. 패키지 설치·Node 빌드·Fleet·ROS·DB가 필요하지 않다.

```powershell
python applications/fleet/dev/serve.py --mode sample --scenario normal --port 4173
```

`http://localhost:4173/console`에서 로그인 `sample`, 비밀번호 `CHANGE_ME`를 사용한다. 별도 검토자는 `sample-reviewer`와 같은 비밀번호다. 기명 운영자 토큰 전용 카메라 승인 화면에서는 샘플 토큰 `sample-operator`를 사용한다. 이 값들은 샘플 호스트에서만 유효하다.

화면 위 샘플 제어에서 초기화·읽기 전용 사용자·작업 완료/실패/보류·Cell 진행·AI 응답·합성 음성·영상 상태를 선택한다. 새로고침은 상태를 유지하며 초기화나 서버 재시작은 메모리 상태를 지운다. `--scenario viewer`로 권한 거절부터 확인할 수도 있다. 모든 샘플 작업은 로컬 상태 변경이며 실제 장치·마이크·카메라·모델에 연결하지 않는다.

Cell 제안은 제안자와 다른 운영자가 승인한다. 제안 후 `검토자로 로그인`을 선택하고 같은 작업 ID를 다시 조회해 승인한다. 같은 사람이 승인하면 실제 API와 같은 403 거절을 받는다.

`web/`의 실제 화면과 HTTP 호출을 그대로 제공하고 `app-runtime.js` 공급자만 바꾼다. `web/assets.json`이 페이지·공개 자산 경로의 기준이며 Fleet 서버와 개발 서버가 함께 읽는다. 새 파일은 이 목록에 등록한다. `dev/sample`은 기능별 상태를 소유하고 모르는 요청은 501로 드러낸다.

샘플은 대표 흐름을 위한 데이터다. Cell 컴파일은 기록된 예제 문서만 지원하고, 정책 실행 lease는 발급하지 않는다. 캘리브레이션은 표시용이며 물리 교정이나 장치 성공을 증명하지 않는다. 한 샘플 서버는 한 개발 세션의 로그인 상태를 공유하므로 여러 개발자는 각자 포트/프로세스를 사용한다.

## 실제 API에 연결

```powershell
python applications/fleet/dev/serve.py --mode connected --origin https://localhost:4174 --upstream https://site.example --cert private/dev-cert.pem --key private/dev-key.pem --ca private/site-ca.pem
```

로컬 인증서에는 `localhost`가 포함돼야 하며 브라우저도 해당 인증서를 신뢰해야 한다. `--ca`는 사설 upstream CA를 쓰는 경우에만 필요하다. 인증서·키·실제 접속 주소와 자격 증명은 저장소에 올리지 않는다. `--upstream`은 Fleet API와 Vision 프레임을 함께 제공하는 사이트 HTTPS 게이트웨이 origin이다. 경로·사용자 정보·쿼리를 넣지 않는다.

이 모드에서 실제 로그인·권한·API 오류를 그대로 사용한다. Fleet 쿠키는 단일 upstream의 Fleet 요청으로만 보내며 Vision 프레임에는 lease Bearer만 보낸다. 승인된 로봇 영상은 기존 미디어 경로로 직접 연결한다. 샘플로 자동 전환하거나 임의 URL을 프록시하지 않는다. 샘플 제어는 제공하지 않는다.

## 검증과 운영 배포

```powershell
python applications/fleet/dev/serve.py --check
python tools/remote/remote_pytest.py --log-dir private/frontend-checks -- applications/fleet/test
python tools/remote/remote_pytest.py --log-dir private/frontend-browser -- ROSY_RUN_BROWSER_TESTS=1 applications/fleet/test/test_sample_browser.py applications/fleet/test/test_feature_browser_flows.py applications/fleet/test/test_browser_adapters.py
```

Python 시험은 커밋한 SHA를 원격 시험 PC에서 실행한다. 브라우저 시험은 opt-in이며 skip은 통과 증거가 아니다. `test/feature_matrix.json`에서 API 소유자·관찰된 응답·대표 흐름의 증거를 찾는다. 샘플 브라우저 시험, 실제 백엔드의 HTTP 계약 시험, 배포 환경/장치 인수는 서로 다른 증거다.

운영 Fleet은 기존 wheel·이미지·URL로 배포하며 native `runtime.js`와 등록된 자산을 포함한다. `dev/`와 샘플 제어는 운영 패키지에 포함하지 않는다. gateway는 공개 `fleet.cli.run(argv)`을 사용한다. [D-830](../../docs/adr/D-830-fleet-independent-frontend-development.md)과 [개발 분리 계획](../../docs/plans/2026-10-21-fleet-frontend-separation.md)을 따른다.
