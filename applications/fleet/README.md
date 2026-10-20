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

현재는 소스 개발 경계를 모은 상태다. 별도 레포로 분리하려면 Fleet wheel에 포함되는 화면 패키징, gateway의 Fleet CLI 의존성, 공통 자산 공급과 인증 origin을 먼저 정리해야 한다. [D-822](../../docs/adr/D-822-fleet-application-source-boundary.md)를 따른다.
